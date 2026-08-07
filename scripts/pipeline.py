#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import rawpy
import tifffile
from PIL import ExifTags, Image, UnidentifiedImageError

from dng_diagnostics import diagnose_proraw


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DISPLAY_P3_PROFILE = SKILL_DIR / "assets" / "profiles" / "DisplayP3-v4.icc"
SRGB_PROFILE = SKILL_DIR / "assets" / "profiles" / "sRGB-v4.icc"
IMAGE_EXTENSIONS = {".dng"}
CHUNK_ROWS = 256
SHADOW_LUMA_MAX = 20
HIGHLIGHT_LUMA_MIN = 250
CLIPPED_BLACK_LUMA_MAX = 1
CLIPPED_WHITE_LUMA_MIN = 254

P3_TO_XYZ = np.array([
    [0.4865709486482162, 0.2656676931690931, 0.1982172852343625],
    [0.2289745640697488, 0.6917385218365064, 0.0792869140937450],
    [0.0000000000000000, 0.0451133818589026, 1.0439443689009760],
], dtype=np.float32)
XYZ_TO_SRGB = np.array([
    [3.2409699419045226, -1.5373831775700940, -0.4986107602930034],
    [-0.9692436362808796, 1.8759675015077202, 0.0415550574071756],
    [0.0556300796969937, -0.2039769588889765, 1.0569715142428786],
], dtype=np.float32)
P3_TO_SRGB = XYZ_TO_SRGB @ P3_TO_XYZ
P3_LUMA = P3_TO_XYZ[1]


@dataclass(frozen=True)
class Preset:
    exposure_ev: float
    chroma_compression: float
    saturation: float
    brightness: float
    contrast: float
    tone_y: tuple[float, ...]


@dataclass(frozen=True)
class FinishPreset:
    saturation: float
    vibrance: float
    max_chroma_scale: float


PRESETS = {
    "light": Preset(0.000, 0.020, 1.030, 0.002, 1.010, (0.000, 0.035, 0.170, 0.525, 0.840, 0.955, 0.995)),
    "standard": Preset(-0.180, 0.055, 1.020, 0.000, 1.025, (0.000, 0.022, 0.125, 0.430, 0.770, 0.925, 0.990)),
    "strong": Preset(-0.450, 0.110, 1.000, 0.000, 1.045, (0.000, 0.012, 0.075, 0.335, 0.690, 0.890, 0.982)),
}
FINISH_PRESETS = {
    "neutral": FinishPreset(1.000, 0.000, 1.000),
    "social": FinishPreset(1.105, 0.220, 1.320),
}
TONE_X = np.array([0.00, 0.08, 0.20, 0.45, 0.73, 0.90, 1.00], dtype=np.float64)
CONTRAST_SAMPLE_PIXELS = 1_000_000
CONTRAST_MIN_SPAN = 0.58
CONTRAST_MIN_BLACK_GAP = 0.035
CONTRAST_REFERENCE_MARGIN = 0.015
CONTRAST_TOE_PIVOT = 0.55
CONTRAST_BLEND_START = 0.35
CONTRAST_BLEND_END = 0.65
CONTRAST_MAX_GAMMA = 1.70
MIDTONE_MIN_PREVIEW_P50 = 0.25
MIDTONE_MIN_GAP = 0.06
MIDTONE_MIN_SPAN = 0.75
MIDTONE_MIN_P99 = 0.80
MIDTONE_PREVIEW_BLEND = 0.70
MIDTONE_PREVIEW_MARGIN = 0.035
MIDTONE_MAX_ABSOLUTE_LIFT = 0.17
MIDTONE_BASELINE_MAX_EV = 0.75
MIDTONE_BASELINE_WEIGHT = 0.65
MIDTONE_MAX_GAIN = 4.0
MIDTONE_SHADOW_START = 0.015
MIDTONE_SHADOW_END = 0.12
MIDTONE_HIGHLIGHT_START = 0.60
MIDTONE_HIGHLIGHT_END = 0.97
MIDTONE_SEARCH_STEPS = 18
MIDTONE_UNDEREXPOSURE_RATIO = 0.75
MIDTONE_UNDEREXPOSURE_GAP = 0.08


class RenderError(RuntimeError):
    pass


def _clean_text(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value or "").replace("\x00", "").strip()


def _read_tag(page: tifffile.TiffPage, name: str) -> Any:
    tag = page.tags.get(name)
    return None if tag is None else tag.value


def _read_metadata(path: Path, keep_gps: bool) -> tuple[dict[str, Any], bytes | None]:
    metadata: dict[str, Any] = {}
    with tifffile.TiffFile(path) as tif:
        page = tif.pages[0]
        for name in ("Make", "Model", "Software", "DateTime", "Artist", "Copyright"):
            value = _read_tag(page, name)
            if value is not None:
                metadata[name] = value

    exif_bytes: bytes | None = None
    try:
        with Image.open(path) as source:
            exif = source.getexif()
            metadata.setdefault("Make", exif.get(271))
            metadata.setdefault("Model", exif.get(272))
            metadata.setdefault("Software", exif.get(305))
            metadata.setdefault("DateTime", exif.get(306))
            try:
                exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
            except (KeyError, TypeError, ValueError):
                exif_ifd = {}
            for key, name in (
                (36867, "DateTimeOriginal"),
                (34855, "ISOSpeedRatings"),
                (33434, "ExposureTime"),
                (33437, "FNumber"),
                (37386, "FocalLength"),
                (42036, "LensModel"),
            ):
                if key in exif_ifd:
                    metadata[name] = exif_ifd[key]

            if not keep_gps:
                gps_tag = int(ExifTags.IFD.GPSInfo)
                if gps_tag in exif:
                    del exif[gps_tag]
            exif[274] = 1
            exif_bytes = exif.tobytes()
    except (OSError, UnidentifiedImageError, ValueError):
        pass

    metadata["Make"] = _clean_text(metadata.get("Make"))
    metadata["Model"] = _clean_text(metadata.get("Model"))
    metadata["LensModel"] = _clean_text(metadata.get("LensModel"))
    return metadata, exif_bytes


def _validate_apple_dng(path: Path, metadata: dict[str, Any]) -> None:
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise RenderError("Only Apple ProRAW .dng inputs are accepted.")
    make = metadata.get("Make", "").lower()
    model = metadata.get("Model", "").lower()
    if make != "apple" or "iphone" not in model:
        raise RenderError(
            f"Input is not an Apple iPhone DNG (Make={metadata.get('Make')!r}, Model={metadata.get('Model')!r})."
        )


def _srgb_oetf_inplace(values: np.ndarray) -> None:
    np.clip(values, 0.0, 1.0, out=values)
    mask = values <= 0.0031308
    values[mask] *= 12.92
    high = ~mask
    values[high] = 1.055 * np.power(values[high], 1.0 / 2.4) - 0.055


def _srgb_eotf(values: np.ndarray) -> np.ndarray:
    out = values.copy()
    mask = out <= 0.04045
    out[mask] /= 12.92
    high = ~mask
    out[high] = np.power((out[high] + 0.055) / 1.055, 2.4)
    return out


def _monotone_lut(y_points: tuple[float, ...]) -> np.ndarray:
    x = TONE_X
    y = np.asarray(y_points, dtype=np.float64)
    h = np.diff(x)
    delta = np.diff(y) / h
    slopes = np.zeros_like(y)
    slopes[0] = delta[0]
    slopes[-1] = delta[-1]
    for index in range(1, len(y) - 1):
        left = delta[index - 1]
        right = delta[index]
        if left * right <= 0:
            slopes[index] = 0.0
        else:
            w1 = 2 * h[index] + h[index - 1]
            w2 = h[index] + 2 * h[index - 1]
            slopes[index] = (w1 + w2) / (w1 / left + w2 / right)

    grid = np.linspace(0.0, 1.0, 65536, dtype=np.float64)
    segment = np.searchsorted(x, grid, side="right") - 1
    segment = np.clip(segment, 0, len(h) - 1)
    t = (grid - x[segment]) / h[segment]
    t2 = t * t
    t3 = t2 * t
    result = (
        (2 * t3 - 3 * t2 + 1) * y[segment]
        + (t3 - 2 * t2 + t) * h[segment] * slopes[segment]
        + (-2 * t3 + 3 * t2) * y[segment + 1]
        + (t3 - t2) * h[segment] * slopes[segment + 1]
    )
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def _apply_look_inplace(encoded_p3: np.ndarray, preset: Preset) -> None:
    lut = _monotone_lut(preset.tone_y)
    height = encoded_p3.shape[0]
    for start in range(0, height, CHUNK_ROWS):
        block = encoded_p3[start:start + CHUNK_ROWS]
        luma = np.sum(block * P3_LUMA, axis=2, keepdims=True)
        high = np.max(block, axis=2, keepdims=True)
        low = np.min(block, axis=2, keepdims=True)
        chroma = np.divide(high - low, np.maximum(high, 1e-6))
        scale = preset.saturation * (1.0 - preset.chroma_compression * chroma)
        block[:] = luma + (block - luma) * scale
        curve_input = (luma + preset.brightness - 0.5) * preset.contrast + 0.5
        np.clip(curve_input, 0.0, 1.0, out=curve_input)
        indices = np.rint(curve_input * 65535.0).astype(np.uint16)
        target_luma = lut[indices]
        ratio = np.divide(target_luma, np.maximum(luma, 1e-6))
        block *= ratio
        np.clip(block, 0.0, 1.0, out=block)


def _apply_finish_inplace(encoded_p3: np.ndarray, finish: FinishPreset) -> None:
    if finish.max_chroma_scale <= 1.0:
        return
    height = encoded_p3.shape[0]
    for start in range(0, height, CHUNK_ROWS):
        block = encoded_p3[start:start + CHUNK_ROWS]
        luma = np.sum(block * P3_LUMA, axis=2, keepdims=True)
        high = np.max(block, axis=2, keepdims=True)
        low = np.min(block, axis=2, keepdims=True)
        chroma = np.divide(high - low, np.maximum(high, 1e-6))
        desired = finish.saturation * (1.0 + finish.vibrance * (1.0 - chroma))
        np.minimum(desired, finish.max_chroma_scale, out=desired)
        shadow_weight = np.clip((luma - 0.025) / 0.100, 0.0, 1.0)
        highlight_weight = np.clip((0.985 - luma) / 0.160, 0.0, 1.0)
        weight = np.minimum(shadow_weight, highlight_weight)
        scale = 1.0 + (desired - 1.0) * weight
        block[:] = luma + (block - luma) * scale
        np.clip(block, 0.0, 1.0, out=block)


def _sample_luma_values(rgb: np.ndarray, weights: np.ndarray) -> np.ndarray:
    height, width = rgb.shape[:2]
    stride = max(1, int(math.sqrt((height * width) / CONTRAST_SAMPLE_PIXELS)))
    sampled = rgb[::stride, ::stride].astype(np.float32, copy=False)
    return np.sum(sampled * weights, axis=2)


def _sample_luma_percentiles(rgb: np.ndarray, weights: np.ndarray) -> dict[str, float]:
    luma = _sample_luma_values(rgb, weights)
    p01, p50, p99 = np.percentile(luma, (1.0, 50.0, 99.0))
    return {
        "p01": round(float(p01), 6),
        "p50": round(float(p50), 6),
        "p99": round(float(p99), 6),
        "span_p01_p99": round(float(p99 - p01), 6),
    }


def _embedded_preview_contrast(raw: rawpy.RawPy) -> dict[str, Any]:
    """Read only global tone statistics; never use preview pixels as output."""
    try:
        thumbnail = raw.extract_thumb()
        if thumbnail.format == rawpy.ThumbFormat.JPEG:
            with Image.open(io.BytesIO(thumbnail.data)) as image:
                image = image.convert("RGB")
                image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
                pixels = np.asarray(image, dtype=np.float32) * (1.0 / 255.0)
        else:
            pixels = np.asarray(thumbnail.data, dtype=np.float32) * (1.0 / 255.0)
        metrics = _sample_luma_percentiles(
            pixels,
            np.array([0.2126, 0.7152, 0.0722], dtype=np.float32),
        )
        return {"available": True, "role": "global_tone_reference_only", "metrics": metrics}
    except (rawpy.LibRawError, OSError, UnidentifiedImageError, ValueError, TypeError) as exc:
        return {"available": False, "role": "global_tone_reference_only", "error": str(exc)}


def _smoothstep(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, 0.0, 1.0)
    return values * values * (3.0 - 2.0 * values)


def _midtone_lift_luma(luma: np.ndarray, gain: float) -> np.ndarray:
    lifted = np.divide(
        gain * luma,
        1.0 + (gain - 1.0) * luma,
    )
    shadow_gate = _smoothstep(
        (luma - MIDTONE_SHADOW_START) / (MIDTONE_SHADOW_END - MIDTONE_SHADOW_START)
    )
    highlight_gate = 1.0 - _smoothstep(
        (luma - MIDTONE_HIGHLIGHT_START) / (MIDTONE_HIGHLIGHT_END - MIDTONE_HIGHLIGHT_START)
    )
    return luma + (lifted - luma) * shadow_gate * highlight_gate


def _adapt_scene_midtones_inplace(
    encoded_p3: np.ndarray,
    preview_contrast: dict[str, Any],
    baseline_exposure_ev: float | None,
) -> dict[str, Any]:
    before = _sample_luma_percentiles(encoded_p3, P3_LUMA)
    report: dict[str, Any] = {
        "method": "preview_guided_global_midtone_lift",
        "applied": False,
        "preview": preview_contrast,
        "before": before,
    }
    if not preview_contrast.get("available"):
        report["reason"] = "embedded_preview_unavailable"
        report["after"] = before
        return report

    reference = preview_contrast["metrics"]
    reference_p50 = float(reference["p50"])
    current_p50 = float(before["p50"])
    current_p99 = float(before["p99"])
    current_span = float(before["span_p01_p99"])
    gap = reference_p50 - current_p50
    positive_baseline_ev = float(np.clip(
        max(float(baseline_exposure_ev or 0.0), 0.0),
        0.0,
        MIDTONE_BASELINE_MAX_EV,
    ))
    preview_target = current_p50 + max(gap, 0.0) * MIDTONE_PREVIEW_BLEND
    baseline_target = current_p50 * (2.0 ** (positive_baseline_ev * MIDTONE_BASELINE_WEIGHT))
    target_p50 = min(
        reference_p50 - MIDTONE_PREVIEW_MARGIN,
        current_p50 + MIDTONE_MAX_ABSOLUTE_LIFT,
        max(preview_target, baseline_target),
    )
    target_p50 = max(current_p50, target_p50)
    report["decision"] = {
        "reference_p50": round(reference_p50, 6),
        "current_p50": round(current_p50, 6),
        "gap": round(gap, 6),
        "baseline_exposure_ev": None if baseline_exposure_ev is None else round(float(baseline_exposure_ev), 6),
        "positive_baseline_ev_used": round(positive_baseline_ev, 6),
        "preview_target_p50": round(preview_target, 6),
        "baseline_target_p50": round(baseline_target, 6),
        "selected_target_p50": round(target_p50, 6),
        "minimum_preview_p50": MIDTONE_MIN_PREVIEW_P50,
        "minimum_gap": MIDTONE_MIN_GAP,
        "minimum_span": MIDTONE_MIN_SPAN,
        "minimum_p99": MIDTONE_MIN_P99,
        "maximum_absolute_lift": MIDTONE_MAX_ABSOLUTE_LIFT,
    }

    if reference_p50 < MIDTONE_MIN_PREVIEW_P50:
        report["reason"] = "reference_scene_is_dark"
        report["after"] = before
        return report
    if gap < MIDTONE_MIN_GAP:
        report["reason"] = "midtone_already_open"
        report["after"] = before
        return report
    if current_span < MIDTONE_MIN_SPAN or current_p99 < MIDTONE_MIN_P99:
        report["reason"] = "scene_not_bright_high_contrast"
        report["after"] = before
        return report
    if target_p50 <= current_p50 + 1e-4:
        report["reason"] = "no_safe_midtone_lift"
        report["after"] = before
        return report

    sampled_luma = _sample_luma_values(encoded_p3, P3_LUMA)
    maximum_median = float(np.percentile(_midtone_lift_luma(sampled_luma, MIDTONE_MAX_GAIN), 50.0))
    achievable_target = min(target_p50, maximum_median)
    low_gain = 1.0
    high_gain = MIDTONE_MAX_GAIN
    for _ in range(MIDTONE_SEARCH_STEPS):
        candidate_gain = (low_gain + high_gain) * 0.5
        candidate_median = float(np.percentile(
            _midtone_lift_luma(sampled_luma, candidate_gain),
            50.0,
        ))
        if candidate_median < achievable_target:
            low_gain = candidate_gain
        else:
            high_gain = candidate_gain
    gain = high_gain

    height = encoded_p3.shape[0]
    for start in range(0, height, CHUNK_ROWS):
        block = encoded_p3[start:start + CHUNK_ROWS]
        luma = np.sum(block * P3_LUMA, axis=2, keepdims=True)
        target_luma = _midtone_lift_luma(luma, gain)
        block *= np.divide(target_luma, np.maximum(luma, 1e-6))
        np.clip(block, 0.0, 1.0, out=block)

    report["applied"] = True
    report["reason"] = "bright_high_contrast_scene_with_dense_midtones"
    report["gain"] = round(gain, 6)
    report["maximum_achievable_p50"] = round(maximum_median, 6)
    report["target_limited_by_curve"] = maximum_median < target_p50
    report["after"] = _sample_luma_percentiles(encoded_p3, P3_LUMA)
    return report


def _preserve_scene_contrast_inplace(
    encoded_p3: np.ndarray,
    preview_contrast: dict[str, Any],
) -> dict[str, Any]:
    before = _sample_luma_percentiles(encoded_p3, P3_LUMA)
    report: dict[str, Any] = {
        "method": "adaptive_global_shadow_anchor",
        "applied": False,
        "preview": preview_contrast,
        "before": before,
    }
    if not preview_contrast.get("available"):
        report["reason"] = "embedded_preview_unavailable"
        report["after"] = before
        return report

    reference_black = float(preview_contrast["metrics"]["p01"])
    current_black = float(before["p01"])
    span = float(before["span_p01_p99"])
    target_black = max(0.015, min(current_black, reference_black + CONTRAST_REFERENCE_MARGIN))
    black_gap = current_black - target_black
    report["decision"] = {
        "reference_black_p01": round(reference_black, 6),
        "target_black_p01": round(target_black, 6),
        "black_gap": round(black_gap, 6),
        "minimum_span": CONTRAST_MIN_SPAN,
        "minimum_black_gap": CONTRAST_MIN_BLACK_GAP,
    }
    if span < CONTRAST_MIN_SPAN:
        report["reason"] = "scene_not_high_contrast"
        report["after"] = before
        return report
    if black_gap < CONTRAST_MIN_BLACK_GAP or current_black <= 0.0:
        report["reason"] = "black_point_already_grounded"
        report["after"] = before
        return report

    required_gamma = math.log(target_black / CONTRAST_TOE_PIVOT) / math.log(
        current_black / CONTRAST_TOE_PIVOT
    )
    required_gamma = float(np.clip(required_gamma, 1.0, CONTRAST_MAX_GAMMA))
    activation = float(np.clip(
        (black_gap - CONTRAST_MIN_BLACK_GAP) / 0.08,
        0.0,
        1.0,
    ))
    gamma = 1.0 + (required_gamma - 1.0) * activation

    height = encoded_p3.shape[0]
    for start in range(0, height, CHUNK_ROWS):
        block = encoded_p3[start:start + CHUNK_ROWS]
        luma = np.sum(block * P3_LUMA, axis=2, keepdims=True)
        normalized = np.clip(luma / CONTRAST_TOE_PIVOT, 0.0, 1.0)
        toe_luma = CONTRAST_TOE_PIVOT * np.power(normalized, gamma)
        blend = np.clip(
            (luma - CONTRAST_BLEND_START) / (CONTRAST_BLEND_END - CONTRAST_BLEND_START),
            0.0,
            1.0,
        )
        blend = blend * blend * (3.0 - 2.0 * blend)
        target_luma = luma + (toe_luma - luma) * (1.0 - blend)
        block *= np.divide(target_luma, np.maximum(luma, 1e-6))
        np.clip(block, 0.0, 1.0, out=block)

    report["applied"] = True
    report["reason"] = "floating_black_in_high_contrast_scene"
    report["gamma"] = round(gamma, 6)
    report["after"] = _sample_luma_percentiles(encoded_p3, P3_LUMA)
    return report


def _p3_to_srgb8(encoded_p3: np.ndarray) -> np.ndarray:
    height, width, _ = encoded_p3.shape
    output = np.empty((height, width, 3), dtype=np.uint8)
    for start in range(0, height, CHUNK_ROWS):
        block = _srgb_eotf(encoded_p3[start:start + CHUNK_ROWS])
        block = block @ P3_TO_SRGB.T
        # Compress only out-of-gamut chroma toward Rec.709 luminance instead of
        # clipping channels independently, which preserves hue relationships.
        luma = np.sum(block * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axis=2, keepdims=True)
        delta = block - luma
        positive_limit = np.divide(1.0 - luma, np.maximum(delta, 1e-8))
        negative_limit = np.divide(luma, np.maximum(-delta, 1e-8))
        channel_limit = np.where(delta > 0.0, positive_limit, np.where(delta < 0.0, negative_limit, 1.0))
        gamut_scale = np.minimum(1.0, np.min(channel_limit, axis=2, keepdims=True))
        block = luma + delta * gamut_scale
        _srgb_oetf_inplace(block)
        output[start:start + CHUNK_ROWS] = np.rint(block * 255.0).astype(np.uint8)
    return output


def _percent(value: int, total: int) -> float:
    return round(value * 100.0 / total, 4)


def _histogram_percentile(histogram: np.ndarray, percentile: float) -> int:
    total = int(histogram.sum())
    if total <= 0:
        return 0
    target = max(1, int(np.ceil(total * percentile)))
    return int(np.searchsorted(np.cumsum(histogram), target, side="left"))


def _analyze_final_jpeg(
    path: Path,
    midtone_adaptation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure final encoded pixels without relying on scene-aware enhancement."""
    with Image.open(path) as image:
        pixels = np.asarray(image.convert("RGB"), dtype=np.uint8)

    histogram = np.zeros(256, dtype=np.int64)
    saturation_histogram = np.zeros(256, dtype=np.int64)
    for start in range(0, pixels.shape[0], CHUNK_ROWS):
        block = pixels[start:start + CHUNK_ROWS].astype(np.uint16)
        # Rec.709 luma coefficients, scaled to sum to 256 for an 8-bit histogram.
        luma = (54 * block[..., 0] + 183 * block[..., 1] + 19 * block[..., 2] + 128) >> 8
        histogram += np.bincount(luma.ravel(), minlength=256)
        high = np.max(block, axis=2)
        low = np.min(block, axis=2)
        valid = high > 20
        saturation = np.zeros_like(high)
        saturation[valid] = ((high[valid] - low[valid]) * 255 + high[valid] // 2) // high[valid]
        saturation_histogram += np.bincount(saturation[valid].ravel(), minlength=256)

    total = int(histogram.sum())
    black_clip = int(histogram[:CLIPPED_BLACK_LUMA_MAX + 1].sum())
    deep_shadow = int(histogram[:SHADOW_LUMA_MAX + 1].sum())
    bright_highlight = int(histogram[HIGHLIGHT_LUMA_MIN:].sum())
    white_clip = int(histogram[CLIPPED_WHITE_LUMA_MIN:].sum())
    metrics = {
        "black_clip_percent": _percent(black_clip, total),
        "deep_shadow_percent": _percent(deep_shadow, total),
        "bright_highlight_percent": _percent(bright_highlight, total),
        "white_clip_percent": _percent(white_clip, total),
        "luma_percentiles_8bit": {
            "p01": _histogram_percentile(histogram, 0.01),
            "p50": _histogram_percentile(histogram, 0.50),
            "p99": _histogram_percentile(histogram, 0.99),
        },
        "saturation_8bit": {
            "mean": round(float(np.dot(np.arange(256), saturation_histogram) / max(1, saturation_histogram.sum())), 2),
            "p50": _histogram_percentile(saturation_histogram, 0.50),
            "p75": _histogram_percentile(saturation_histogram, 0.75),
            "p90": _histogram_percentile(saturation_histogram, 0.90),
        },
    }

    warnings: list[str] = []
    median = metrics["luma_percentiles_8bit"]["p50"]
    if metrics["black_clip_percent"] >= 1.0 or (
        metrics["deep_shadow_percent"] >= 20.0 and median <= 40
    ):
        warnings.append(
            "possible_shadow_crush: inspect large dark areas for lost texture before delivery"
        )
    if metrics["white_clip_percent"] >= 1.0 or metrics["bright_highlight_percent"] >= 5.0:
        warnings.append(
            "possible_highlight_clipping: inspect bright areas for lost texture before delivery"
        )
    if midtone_adaptation and midtone_adaptation.get("preview", {}).get("available"):
        reference_p50 = float(midtone_adaptation["preview"]["metrics"]["p50"])
        final_p50 = float(metrics["luma_percentiles_8bit"]["p50"]) / 255.0
        midtone_gap = reference_p50 - final_p50
        midtone_ratio = final_p50 / max(reference_p50, 1e-6)
        metrics["scene_midtone_reference"] = {
            "preview_p50": round(reference_p50, 6),
            "final_p50": round(final_p50, 6),
            "gap": round(midtone_gap, 6),
            "ratio": round(midtone_ratio, 6),
        }
        if (
            reference_p50 >= MIDTONE_MIN_PREVIEW_P50
            and midtone_gap >= MIDTONE_UNDEREXPOSURE_GAP
            and midtone_ratio <= MIDTONE_UNDEREXPOSURE_RATIO
        ):
            warnings.append(
                "possible_global_underexposure: rendered midtones remain much darker than the global preview reference"
            )

    return {
        "status": "review_required" if warnings else "pass",
        "requires_visual_review": True,
        "metrics": metrics,
        "warnings": warnings,
    }


def _fraction_tuple(value: Any) -> tuple[int, int] | None:
    try:
        if hasattr(value, "numerator") and hasattr(value, "denominator"):
            numerator = int(value.numerator)
            denominator = int(value.denominator)
            return numerator, denominator or 1
        fraction = Fraction(float(value)).limit_denominator(1_000_000)
        return fraction.numerator, fraction.denominator
    except (TypeError, ValueError, OverflowError):
        return None


def _tiff_extratags(metadata: dict[str, Any], icc: bytes) -> list[tuple[Any, ...]]:
    tags: list[tuple[Any, ...]] = [(34675, "B", len(icc), icc, False)]
    ascii_tags = (
        (271, "Make"), (272, "Model"),
        (306, "DateTime"), (36867, "DateTimeOriginal"), (42036, "LensModel"),
    )
    for code, name in ascii_tags:
        value = _clean_text(metadata.get(name))
        if value:
            tags.append((code, "s", 0, value, False))

    iso = metadata.get("ISOSpeedRatings")
    try:
        if iso is not None:
            tags.append((34855, "H", 1, int(iso), False))
    except (TypeError, ValueError):
        pass

    for code, name in ((33434, "ExposureTime"), (33437, "FNumber"), (37386, "FocalLength")):
        rational = _fraction_tuple(metadata.get(name))
        if rational is not None:
            tags.append((code, "2I", 1, rational, False))
    return tags


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _versioned_outputs(output_dir: Path, stem: str, strength: str, finish: str, overwrite: bool) -> tuple[Path, Path, Path]:
    suffix = ""
    version = 1
    while True:
        jpeg = output_dir / f"{stem}-natural-{strength}-{finish}{suffix}-sRGB.jpg"
        tiff = output_dir / f"{stem}-natural-{strength}-{finish}{suffix}-16bit-P3.tif"
        diagnostic = output_dir / f"{stem}-natural-{strength}-{finish}{suffix}-diagnostic.json"
        if overwrite or (not jpeg.exists() and not tiff.exists() and not diagnostic.exists()):
            return jpeg, tiff, diagnostic
        version += 1
        suffix = f"-v{version}"


def _canonical_outputs(output_dir: Path, stem: str, strength: str, finish: str) -> tuple[Path, Path, Path]:
    return (
        output_dir / f"{stem}-natural-{strength}-{finish}-sRGB.jpg",
        output_dir / f"{stem}-natural-{strength}-{finish}-16bit-P3.tif",
        output_dir / f"{stem}-natural-{strength}-{finish}-diagnostic.json",
    )


def _remove_other_outputs(
    output_dir: Path,
    stem: str,
    keep: tuple[Path, Path, Path],
) -> list[str]:
    strengths = "|".join(re.escape(value) for value in sorted(PRESETS))
    finishes = "|".join(re.escape(value) for value in sorted(FINISH_PRESETS))
    rendered = re.compile(
        rf"^{re.escape(stem)}-natural-(?:{strengths})-(?:{finishes})"
        rf"(?:-v\d+)?-(?:sRGB\.jpg|16bit-P3\.tif|diagnostic\.json)$"
    )
    diagnose_only = re.compile(rf"^{re.escape(stem)}-proraw-diagnostic(?:-v\d+)?\.json$")
    keep_paths = {path.resolve() for path in keep}
    removed: list[str] = []
    for candidate in sorted(output_dir.iterdir()):
        if not candidate.is_file() or candidate.resolve() in keep_paths:
            continue
        if not rendered.fullmatch(candidate.name) and not diagnose_only.fullmatch(candidate.name):
            continue
        candidate.unlink()
        removed.append(str(candidate))
    return removed


def _temp_path(output_dir: Path, suffix: str) -> Path:
    # Dot-prefixed temporary names can acquire UF_HIDDEN on macOS and retain
    # it after an atomic rename. Avoid creating that Finder state at all.
    descriptor, name = tempfile.mkstemp(prefix="natural-camera-tmp-", suffix=suffix, dir=output_dir)
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return path


def _clear_platform_hidden_flag(path: Path) -> None:
    """Keep atomically published outputs visible in Finder on macOS.

    macOS can attach UF_HIDDEN to a dot-prefixed temporary file and preserve the
    flag when that file is renamed. Other supported platforms do not expose
    chflags/UF_HIDDEN, so this is intentionally a no-op there.
    """
    if not hasattr(os, "chflags") or not hasattr(stat, "UF_HIDDEN"):
        return
    current_flags = os.stat(path, follow_symlinks=False).st_flags
    hidden_flag = stat.UF_HIDDEN
    if current_flags & hidden_flag:
        os.chflags(path, current_flags & ~hidden_flag, follow_symlinks=False)


def _publish_visible(temporary: Path, destination: Path) -> None:
    # Clear the inherited flag before rename, then verify the destination too.
    # The rename remains atomic because both paths are in the output directory.
    _clear_platform_hidden_flag(temporary)
    os.replace(temporary, destination)
    _clear_platform_hidden_flag(destination)
    if (
        hasattr(os, "chflags")
        and hasattr(stat, "UF_HIDDEN")
        and os.stat(destination, follow_symlinks=False).st_flags & stat.UF_HIDDEN
    ):
        raise OSError(f"Published output remains hidden: {destination}")


def _render_one(
    path: Path,
    output_dir: Path,
    requested_strength: str,
    finish: str,
    overwrite: bool,
    keep_gps: bool,
    finalize: bool,
) -> dict[str, Any]:
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise RenderError("Only Apple ProRAW .dng inputs are accepted; JPEG and HEIC are not RAW inputs.")
    source_hash_before = _sha256(path)
    try:
        metadata, exif_bytes = _read_metadata(path, keep_gps)
    except (OSError, ValueError, tifffile.TiffFileError) as exc:
        raise RenderError(f"Unable to read DNG metadata: {exc}") from exc
    _validate_apple_dng(path, metadata)
    diagnostic = diagnose_proraw(path, metadata.get("Model"))
    recommended_strength = diagnostic["recommendation"]["recommended_strength"]
    strength = recommended_strength if requested_strength == "auto" else requested_strength
    diagnostic["strength_selection"] = {
        "requested": requested_strength,
        "recommended": recommended_strength,
        "selected": strength,
        "recommendation_used": requested_strength == "auto",
    }
    diagnostic["finish"] = {
        "selected": finish,
        "social_ready": finish == "social",
        "method": "global_perceptual_vibrance_and_gamut_compression" if finish == "social" else "neutral_base_only",
    }
    diagnostic["publication"] = {
        "mode": "final" if finalize else "candidate",
        "cleanup_other_variants": finalize,
    }

    try:
        with rawpy.imread(str(path)) as raw:
            preview_contrast = _embedded_preview_contrast(raw)
            decoded = raw.postprocess(
                use_camera_wb=True,
                use_auto_wb=False,
                no_auto_bright=False,
                auto_bright_thr=0.01,
                output_color=rawpy.ColorSpace.P3D65,
                output_bps=16,
                gamma=(1.0, 1.0),
                highlight_mode=rawpy.HighlightMode.Blend,
            )
    except rawpy.LibRawError as exc:
        raise RenderError(f"LibRaw could not decode the DNG: {exc}") from exc

    encoded_p3 = decoded.astype(np.float32)
    del decoded
    encoded_p3 *= 1.0 / 65535.0
    encoded_p3 *= 2.0 ** PRESETS[strength].exposure_ev
    for start in range(0, encoded_p3.shape[0], CHUNK_ROWS):
        _srgb_oetf_inplace(encoded_p3[start:start + CHUNK_ROWS])
    _apply_look_inplace(encoded_p3, PRESETS[strength])
    baseline_exposure = diagnostic.get("baseline_exposure", {})
    baseline_exposure_ev = (
        baseline_exposure.get("ev") if baseline_exposure.get("present") else None
    )
    midtone_adaptation = _adapt_scene_midtones_inplace(
        encoded_p3,
        preview_contrast,
        baseline_exposure_ev,
    )
    contrast_preservation = _preserve_scene_contrast_inplace(encoded_p3, preview_contrast)
    _apply_finish_inplace(encoded_p3, FINISH_PRESETS[finish])
    diagnostic["midtone_adaptation"] = midtone_adaptation
    diagnostic["scene_contrast_preservation"] = contrast_preservation

    output_dir.mkdir(parents=True, exist_ok=True)
    if finalize:
        jpeg_path, tiff_path, diagnostic_path = _canonical_outputs(output_dir, path.stem, strength, finish)
    else:
        jpeg_path, tiff_path, diagnostic_path = _versioned_outputs(
            output_dir,
            path.stem,
            strength,
            finish,
            overwrite,
        )
    jpeg_temp = _temp_path(output_dir, ".jpg")
    tiff_temp = _temp_path(output_dir, ".tif")
    diagnostic_temp = _temp_path(output_dir, ".json")
    display_p3_icc = DISPLAY_P3_PROFILE.read_bytes()
    srgb_icc = SRGB_PROFILE.read_bytes()

    try:
        p3_uint16 = np.rint(encoded_p3 * 65535.0).astype(np.uint16)
        tifffile.imwrite(
            tiff_temp,
            p3_uint16,
            photometric="rgb",
            metadata=None,
            software=_clean_text(metadata.get("Software")) or "Natural iPhone ProRAW",
            extratags=_tiff_extratags(metadata, display_p3_icc),
        )
        del p3_uint16

        srgb_uint8 = _p3_to_srgb8(encoded_p3)
        del encoded_p3
        image = Image.fromarray(srgb_uint8)
        save_args: dict[str, Any] = {
            "format": "JPEG",
            "quality": 96,
            "subsampling": 0,
            "optimize": True,
            "icc_profile": srgb_icc,
        }
        if exif_bytes:
            save_args["exif"] = exif_bytes
        image.save(jpeg_temp, **save_args)

        quality_check = _analyze_final_jpeg(jpeg_temp, midtone_adaptation)

        diagnostic["source"] = str(path)
        diagnostic["source_sha256"] = source_hash_before
        diagnostic["quality_check"] = quality_check
        diagnostic_temp.write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        _publish_visible(tiff_temp, tiff_path)
        _publish_visible(jpeg_temp, jpeg_path)
        _publish_visible(diagnostic_temp, diagnostic_path)
    except Exception:
        for temporary in (jpeg_temp, tiff_temp, diagnostic_temp):
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        raise

    source_hash_after = _sha256(path)
    if source_hash_before != source_hash_after:
        raise RenderError("The source DNG changed during rendering; outputs must not be trusted.")

    removed_candidates: list[str] = []
    if finalize:
        removed_candidates = _remove_other_outputs(
            output_dir,
            path.stem,
            (jpeg_path, tiff_path, diagnostic_path),
        )

    return {
        "ok": True,
        "source": str(path),
        "source_sha256": source_hash_after,
        "strength": strength,
        "finish": finish,
        "dimensions": {"width": int(srgb_uint8.shape[1]), "height": int(srgb_uint8.shape[0])},
        "camera": {"make": metadata.get("Make"), "model": metadata.get("Model")},
        "diagnostic": diagnostic,
        "quality_check": quality_check,
        "publication": {
            "mode": "final" if finalize else "candidate",
            "removed_candidates": removed_candidates,
        },
        "outputs": {"jpeg": str(jpeg_path), "tiff": str(tiff_path), "diagnostic": str(diagnostic_path)},
    }


def _versioned_diagnostic(output_dir: Path, stem: str, overwrite: bool) -> Path:
    version = 1
    while True:
        suffix = "" if version == 1 else f"-v{version}"
        result = output_dir / f"{stem}-proraw-diagnostic{suffix}.json"
        if overwrite or not result.exists():
            return result
        version += 1


def _diagnose_one(path: Path, output_dir: Path, overwrite: bool) -> dict[str, Any]:
    source_hash_before = _sha256(path)
    metadata, _ = _read_metadata(path, keep_gps=False)
    _validate_apple_dng(path, metadata)
    diagnostic = diagnose_proraw(path, metadata.get("Model"))
    diagnostic["source"] = str(path)
    diagnostic["source_sha256"] = source_hash_before
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = _versioned_diagnostic(output_dir, path.stem, overwrite)
    temporary = _temp_path(output_dir, ".json")
    try:
        temporary.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _publish_visible(temporary, report_path)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    if source_hash_before != _sha256(path):
        raise RenderError("The source DNG changed during diagnostics; report must not be trusted.")
    return {
        "ok": True,
        "source": str(path),
        "source_sha256": source_hash_before,
        "camera": {"make": metadata.get("Make"), "model": metadata.get("Model")},
        "diagnostic": diagnostic,
        "outputs": {"diagnostic": str(report_path)},
    }


def _expand_inputs(values: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        candidate = Path(value).expanduser().resolve()
        if candidate.is_dir():
            paths.extend(sorted(
                child.resolve() for child in candidate.iterdir()
                if child.is_file() and child.suffix.lower() == ".dng"
            ))
        else:
            paths.append(candidate)
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    return unique


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Develop Apple iPhone ProRAW DNG files with a deterministic natural-camera rendering.",
    )
    parser.add_argument("inputs", nargs="+", help="Apple ProRAW DNG files or directories")
    parser.add_argument("--strength", choices=["auto", *sorted(PRESETS)], default="auto")
    parser.add_argument("--finish", choices=sorted(FINISH_PRESETS), default="social")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--keep-gps", action="store_true")
    parser.add_argument("--diagnose-only", action="store_true", help="Write the ProRAW metadata report without rendering images")
    parser.add_argument(
        "--finalize",
        action="store_true",
        help="Publish this rendering as the sole final JPEG/TIFF/JSON group and delete other recognized outputs for the same source stem",
    )
    args = parser.parse_args()
    if args.finalize and args.diagnose_only:
        parser.error("--finalize cannot be combined with --diagnose-only")
    return args


def main() -> int:
    args = _parse_args()
    inputs = _expand_inputs(args.inputs)
    if not inputs:
        print(json.dumps({"ok": False, "error": "No DNG files were found."}, ensure_ascii=False, indent=2))
        return 1

    results: list[dict[str, Any]] = []
    for path in inputs:
        try:
            if not path.is_file():
                raise RenderError("Input file does not exist.")
            output_dir = args.output_dir.expanduser().resolve() if args.output_dir else path.parent / "natural-camera-output"
            if args.diagnose_only:
                result = _diagnose_one(path, output_dir, args.overwrite)
            else:
                result = _render_one(
                    path,
                    output_dir,
                    args.strength,
                    args.finish,
                    args.overwrite,
                    args.keep_gps,
                    args.finalize,
                )
        except Exception as exc:
            result = {"ok": False, "source": str(path), "error": str(exc)}
        results.append(result)

    payload = {
        "ok": all(item["ok"] for item in results),
        "backend": f"rawpy {rawpy.__version__} / LibRaw {'.'.join(map(str, rawpy.libraw_version))}",
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
