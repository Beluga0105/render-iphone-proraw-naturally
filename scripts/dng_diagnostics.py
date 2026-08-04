from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import tifffile


MODEL_STRENGTH_RULES = {
    # Calibrated from the supplied iPhone 15 Pro main-camera ProRAW samples.
    "iphone16,1": "standard",
}


def _clean_text(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value or "").replace("\x00", "").strip()


def _all_pages(tif: tifffile.TiffFile) -> Iterable[tifffile.TiffPage]:
    def descend(page: tifffile.TiffPage) -> Iterable[tifffile.TiffPage]:
        yield page
        if page.pages:
            for child in page.pages:
                yield from descend(child)

    for root in tif.pages:
        yield from descend(root)


def _find_tag(pages: list[tifffile.TiffPage], name: str, code: int) -> Any:
    for page in pages:
        tag = page.tags.get(name) or page.tags.get(code)
        if tag is not None:
            return tag.value
    return None


def _rational(value: Any) -> float | None:
    try:
        if isinstance(value, (tuple, list)) and len(value) == 2:
            denominator = float(value[1])
            return float(value[0]) / denominator if denominator else None
        if hasattr(value, "numerator") and hasattr(value, "denominator"):
            denominator = float(value.denominator)
            return float(value.numerator) / denominator if denominator else None
        return float(value)
    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        return None


def _tone_curve_summary(value: Any) -> dict[str, Any]:
    if value is None:
        return {"present": False}
    try:
        numbers = np.asarray(value, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError):
        return {"present": True, "readable": False}
    if numbers.size < 4 or numbers.size % 2:
        return {"present": True, "readable": False, "value_count": int(numbers.size)}

    points = numbers.reshape(-1, 2)
    x = points[:, 0]
    y = points[:, 1]
    sample_x = np.asarray([0.10, 0.25, 0.50, 0.75, 0.90], dtype=np.float64)
    sample_y = np.interp(sample_x, x, y)
    return {
        "present": True,
        "readable": True,
        "point_count": int(points.shape[0]),
        "monotonic_x": bool(np.all(np.diff(x) >= 0)),
        "monotonic_y": bool(np.all(np.diff(y) >= -1e-9)),
        "endpoints": {
            "first": [round(float(x[0]), 7), round(float(y[0]), 7)],
            "last": [round(float(x[-1]), 7), round(float(y[-1]), 7)],
        },
        "samples": {
            f"x_{point:.2f}": round(float(result), 7)
            for point, result in zip(sample_x, sample_y)
        },
        "sha256": hashlib.sha256(numbers.astype(">f8", copy=False).tobytes()).hexdigest(),
    }


def _map_data_summary(value: Any, dims: tuple[int, ...] | None) -> dict[str, Any]:
    if value is None:
        return {"present": False}
    try:
        numbers = np.asarray(value, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError):
        return {"present": True, "readable": False}
    summary: dict[str, Any] = {
        "present": True,
        "readable": True,
        "value_count": int(numbers.size),
        "sha256": hashlib.sha256(numbers.astype(">f8", copy=False).tobytes()).hexdigest(),
    }
    if dims is not None:
        summary["expected_value_count"] = int(np.prod(dims)) * 3
        summary["count_matches_dims"] = summary["expected_value_count"] == summary["value_count"]
    if numbers.size and numbers.size % 3 == 0:
        triples = numbers.reshape(-1, 3)
        summary["channels"] = {
            name: {
                "min": round(float(np.min(triples[:, index])), 7),
                "max": round(float(np.max(triples[:, index])), 7),
                "mean": round(float(np.mean(triples[:, index])), 7),
            }
            for index, name in enumerate(("hue_shift", "saturation_scale", "value_scale"))
        }
    return summary


def _as_bytes(value: Any) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    try:
        return bytes(value)
    except (TypeError, ValueError):
        return None


def _opcode_summary(value: Any) -> dict[str, Any]:
    payload = _as_bytes(value)
    if payload is None:
        return {"present": False} if value is None else {"present": True, "readable": False}
    summary: dict[str, Any] = {
        "present": True,
        "readable": True,
        "byte_count": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "items": [],
    }
    if len(payload) < 4:
        summary.update({"readable": False, "parse_warning": "payload_shorter_than_count_header"})
        return summary

    declared = struct.unpack_from(">I", payload, 0)[0]
    summary["declared_count"] = declared
    offset = 4
    items: list[dict[str, Any]] = []
    for index in range(declared):
        if offset + 16 > len(payload):
            summary["parse_warning"] = f"truncated_header_at_opcode_{index}"
            break
        opcode_id, version, flags, data_size = struct.unpack_from(">IIII", payload, offset)
        offset += 16
        if offset + data_size > len(payload):
            summary["parse_warning"] = f"truncated_payload_at_opcode_{index}"
            break
        items.append({
            "index": index,
            "opcode_id": opcode_id,
            "minimum_dng_version": ".".join(str((version >> shift) & 0xFF) for shift in (24, 16, 8, 0)),
            "flags": flags,
            "optional": bool(flags & 1),
            "preview_skippable": bool(flags & 2),
            "payload_bytes": data_size,
        })
        offset += data_size
    summary["items"] = items
    summary["parsed_count"] = len(items)
    summary["trailing_bytes"] = max(0, len(payload) - offset)
    return summary


def _dimensions(value: Any) -> tuple[int, ...] | None:
    if value is None:
        return None
    try:
        result = tuple(int(item) for item in value)
        return result if result else None
    except (TypeError, ValueError):
        return None


def _recommend_strength(unique_model: str, baseline_ev: float | None, diagnostic_warnings: list[str]) -> dict[str, Any]:
    model_key = unique_model.lower().split(" back", 1)[0].strip()
    recommended = MODEL_STRENGTH_RULES.get(model_key, "standard")
    calibrated = model_key in MODEL_STRENGTH_RULES
    reasons = []
    warnings = list(diagnostic_warnings)
    if calibrated:
        reasons.append(f"model_rule:{model_key}={recommended}")
    else:
        reasons.append("fallback_rule:standard")
        warnings.append("unverified_model: no calibrated strength override; visually review standard output")
    if baseline_ev is not None:
        reasons.append(f"baseline_exposure:{baseline_ev:.4f}_EV")
        if baseline_ev >= 1.5:
            warnings.append("high_baseline_exposure: inspect highlight roll-off; metadata alone does not force strong")
        elif baseline_ev <= 0.25:
            warnings.append("low_baseline_exposure: inspect shadow density; metadata alone does not force light")
    return {
        "recommended_strength": recommended,
        "model_key": model_key or None,
        "model_calibrated": calibrated,
        "model_adjustment_applied": recommended != "standard",
        "confidence": "calibrated" if calibrated else "fallback",
        "reasons": reasons,
        "warnings": list(dict.fromkeys(warnings)),
    }


def diagnose_proraw(path: Path, camera_model: str | None = None) -> dict[str, Any]:
    with tifffile.TiffFile(path) as tif:
        pages = list(_all_pages(tif))
        unique_model = _clean_text(_find_tag(pages, "UniqueCameraModel", 50708))
        baseline_raw = _find_tag(pages, "BaselineExposure", 50730)
        baseline_ev = _rational(baseline_raw)
        tone_curve = _tone_curve_summary(_find_tag(pages, "ProfileToneCurve", 50940))
        dims = _dimensions(_find_tag(pages, "ProfileHueSatMapDims", 50937))
        data1 = _map_data_summary(_find_tag(pages, "ProfileHueSatMapData1", 50938), dims)
        data2 = _map_data_summary(_find_tag(pages, "ProfileHueSatMapData2", 50939), dims)
        opcodes = {
            "OpcodeList1": _opcode_summary(_find_tag(pages, "OpcodeList1", 51008)),
            "OpcodeList2": _opcode_summary(_find_tag(pages, "OpcodeList2", 51009)),
            "OpcodeList3": _opcode_summary(_find_tag(pages, "OpcodeList3", 51022)),
        }

    diagnostic_warnings: list[str] = []
    if not tone_curve.get("present"):
        diagnostic_warnings.append("profile_tone_curve_absent")
    if dims is not None and not data1.get("present") and not data2.get("present"):
        diagnostic_warnings.append("hue_sat_dims_present_but_map_data_absent")
    for name, summary in opcodes.items():
        if summary.get("present") and not summary.get("readable"):
            diagnostic_warnings.append(f"{name.lower()}_unreadable")

    recommendation = _recommend_strength(unique_model, baseline_ev, diagnostic_warnings)
    return {
        "schema_version": 1,
        "camera": {
            "model": _clean_text(camera_model),
            "unique_camera_model": unique_model,
        },
        "baseline_exposure": {
            "present": baseline_raw is not None,
            "ev": round(baseline_ev, 7) if baseline_ev is not None else None,
        },
        "profile_tone_curve": tone_curve,
        "hue_sat_map": {
            "dims": list(dims) if dims is not None else None,
            "data1": data1,
            "data2": data2,
        },
        "opcodes": opcodes,
        "recommendation": recommendation,
    }
