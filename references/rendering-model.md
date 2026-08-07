# Rendering model

## Intent

Render Apple ProRAW as a restrained natural-camera starting point. Keep true blacks, open the middle tones with a smooth camera-style S curve, preserve clean color separation, and avoid the flattened shadows and uniformly bright microcontrast associated with phone HDR processing. Do not imitate film stock, add grain, sharpen, denoise aggressively, or claim an exact Capture One profile match.

Apple ProRAW is already a computational RAW format. The pipeline can reshape its tone and color but cannot undo multi-frame fusion or recover an untouched Bayer exposure.

## Decode contract

- Decoder: rawpy 0.27.0 / LibRaw.
- White balance: camera/as-shot.
- Automatic white balance: off.
- Exposure normalization: deterministic LibRaw global auto-bright at a 1% highlight threshold, followed by a fixed preset-level linear exposure bias, an optional preview-guided global midtone lift, and an optional global shadow anchor; no local or content-aware HDR adjustment.
- Highlight handling: blend.
- Working data: 16-bit linear P3 D65.
- Output encoding: standard sRGB transfer function.
- Rendering: deterministic global color and tone operations only.

## Presets

All tone curves use x control points `[0.00, 0.08, 0.20, 0.45, 0.73, 0.90, 1.00]` and monotone cubic interpolation. Preserve the toe while lifting middle tones; do not equate a natural rendering with globally darker or desaturated output.

| Preset | Exposure EV | Chroma compression | Saturation | Brightness | Contrast | Tone y points |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| light | 0.000 | 0.020 | 1.030 | 0.002 | 1.010 | `[0.000, 0.035, 0.170, 0.525, 0.840, 0.955, 0.995]` |
| standard | -0.180 | 0.055 | 1.020 | 0.000 | 1.025 | `[0.000, 0.022, 0.125, 0.430, 0.770, 0.925, 0.990]` |
| strong | -0.450 | 0.110 | 1.000 | 0.000 | 1.045 | `[0.000, 0.012, 0.075, 0.335, 0.690, 0.890, 0.982]` |

Apply the preset exposure bias in linear P3. After display encoding, compress high chroma around P3 luminance and apply brightness, contrast, and the tone curve to luminance rather than independently to RGB channels. Rescale RGB by the luminance ratio to preserve hue relationships. The `strong` curve deliberately restores lower-middle-tone density and highlight separation for scenes where the standard rendering still looks HDR-flat. Do not apply local operators.

## Scene midtone adaptation

Bright sky, cloud, or backlight can dominate LibRaw's global auto-bright decision and leave the photographed ground or foreground too dense even when highlights are intact. After the preset tone curve, compare the rendered global median luminance with the embedded preview's global median. Activate a deterministic luminance-only lift only when the preview median is at least `0.25`, the preview-to-render gap is at least `0.06`, the rendered P01-to-P99 span is at least `0.75`, and rendered P99 is at least `0.80`.

Set the candidate target from 70% of the preview median gap and a bounded positive `BaselineExposure` contribution. Clamp positive metadata input to `0.75 EV`, use it only as an additional target signal, never let a negative value force darkening, keep the target at least `0.035` below the preview median, and cap absolute median lift at `0.17`. Solve a single global gain against sampled luminance. Preserve the toe with a smooth gate from `0.015` to `0.12`, fade the lift out from `0.60` to `0.97`, and cap gain at `4.0`. This opens dense midtones without copying preview pixels, applying local masks, or sacrificing the bright-sky shoulder.

Record the preview and rendered percentiles, BaselineExposure contribution, selected target, gain, curve limit, activation reason, and before/after statistics in `midtone_adaptation`. Failure to read a preview is non-fatal and must result in no midtone adaptation.

## Scene contrast preservation

LibRaw auto-bright can place the darkest significant tone too high in a naturally high-contrast scene even when highlights remain intact. This produces a floating black point and a gray, compressed impression despite a numerically wide histogram.

Read the DNG embedded preview only to measure global 1st/50th/99th-percentile luminance. Never copy its pixels, color, local tone mapping, sharpening, or scene content into the output. After the base tone curve, activate the global shadow anchor only when the rendered P01-to-P99 span is at least `0.58` and its P01 black point exceeds the preview-guided target by at least `0.035`. Apply a smooth luminance-only toe below a `0.55` pivot, cap its gamma at `1.70`, fade it out from `0.35` to `0.65`, and preserve hue by rescaling RGB together. Do not apply the anchor to low-contrast scenes or images whose black point is already grounded.

Record the preview statistics, decision thresholds, before/after percentiles, activation reason, and applied gamma in `scene_contrast_preservation`. Failure to read a preview is non-fatal and must result in no shadow anchoring, not a pixel fallback.

## ProRAW diagnostic and model decision

Before decoding pixels, traverse the root IFDs and nested SubIFDs and summarize these DNG tags without changing the source:

- `BaselineExposure` (50730): decode the signed rational as EV.
- `ProfileToneCurve` (50940): report point count, monotonicity, endpoints, selected interpolated samples, and a SHA-256 fingerprint rather than dumping the full curve.
- `ProfileHueSatMapDims`/`Data1`/`Data2` (50937–50939): report presence, dimensions, expected/actual value counts, per-channel ranges and means, and fingerprints.
- `OpcodeList1`/`2`/`3` (51008, 51009, 51022): parse the big-endian list header and summarize each opcode ID, minimum DNG version, flags, and payload size without copying payload data.

Absence is a valid result and must be represented as `present: false`. A present but malformed tag must be represented as unreadable and must not silently influence the strength decision.

`--strength auto` is the default. Apply a model-specific override only when `MODEL_STRENGTH_RULES` contains a rule calibrated from real source/output pairs for the exact `UniqueCameraModel` hardware key. The currently calibrated `iPhone16,1` rule remains `standard`; therefore no additional preset adjustment is needed for the supplied iPhone 15 Pro samples. Unknown models use `standard`, set confidence to `fallback`, and require visual review. Treat unusually high or low `BaselineExposure` as a review warning only: it is scene-dependent metadata and must not independently force `strong` or `light`. A bounded positive value may contribute to the global midtone target only when the preview and rendered global statistics independently identify a bright high-contrast scene.

An explicit `--strength light|standard|strong` overrides the recommendation but the diagnostic still reports both values. Add new model rules only after visual calibration on multiple representative ProRAW files; never infer a permanent model rule from one scene.

## Color and metadata

After the natural base, default to the `social` finish. Boost low- and medium-chroma colors more than already saturated colors, fade the boost near deep black and near-white to avoid colored noise and clipped highlights, and cap chroma scaling at 1.32. Convert P3 to sRGB with hue-preserving gamut compression toward Rec.709 luminance rather than independent channel clipping. Use `neutral` to skip this finishing stage.

- Embed `assets/profiles/DisplayP3-v4.icc` in TIFF output.
- Convert Display P3 to sRGB with D65 matrices and embed `assets/profiles/sRGB-v4.icc` in JPEG output.
- Preserve camera, model, lens, capture time, ISO, shutter, aperture, and focal length when readable.
- Normalize orientation to 1 because pixels are physically oriented during decode.
- Remove GPS by default. `--keep-gps` preserves it in JPEG metadata when readable.

## Final JPEG exposure and color check

Analyze the final encoded JPEG, not only the pre-compression array. Build a full-image 8-bit Rec.709 luma histogram and report:

- black clipping: luma 0–1;
- deep shadows: luma 0–20;
- bright highlights: luma 250–255;
- white clipping: luma 254–255;
- luma percentiles: 1st, 50th, and 99th.

Also build an 8-bit HSV-style saturation histogram for pixels above near-black and report its mean, 50th, 75th, and 90th percentiles. Use these values to detect unintended color loss or excessive color, but do not impose a universal pass threshold because naturally gray, misty, snowy, and night scenes can be correctly low in saturation.

Set `quality_check.status` to `review_required` when black clipping is at least 1%, or when deep shadows cover at least 20% while median luma is at most 40, or when white clipping is at least 1%, or when bright highlights cover at least 5%. Also require review when the final JPEG median remains at least `0.08` below the preview median and is no more than 75% of that reference in a scene whose preview median is at least `0.25`. Record the final-to-preview median gap and ratio in `scene_midtone_reference`. These thresholds are conservative review triggers, not automatic exposure verdicts. Always inspect whether important scene texture is lost; legitimate night scenes, silhouettes, snow, the sun, and specular reflections may cross the thresholds.

## Runtime dependencies

Install the exact versions in `scripts/requirements.lock` into a per-platform virtual environment inside `.runtime`. Require 64-bit CPython 3.9 or newer. Install the bundled PySocks wheel before network resolution so pip can work with SOCKS proxy configurations.

Official rawpy wheels used by this runtime cover macOS arm64, Windows x86-64, and Linux x86-64/aarch64. LibRaw lists DNG and Apple iPhone 15 Pro support. Reject unsupported platforms or newer formats rather than using a preview fallback.

Write each output to a same-directory temporary path and atomically replace the final path only after encoding succeeds. On macOS, clear `UF_HIDDEN` before and after the rename because Finder can preserve that flag from a dot-prefixed temporary file. This visibility repair is a no-op on platforms without `chflags` and must not alter image bytes or metadata.

Treat non-finalized renders as disposable candidates. After visual acceptance, rerun the selected preset with `--finalize`. Publish the canonical JPEG, TIFF, and diagnostic JSON first; verify the source hash; then remove only filenames that strictly match another recognized render or diagnose-only artifact for the same source stem in the same output directory. Never remove unrelated files, and never clean candidates after an incomplete or failed final render.

## Third-party assets

The compact Display P3 and sRGB ICC profiles come from `saucecontrol/Compact-ICC-Profiles` and are released under CC0-1.0. The bundled PySocks wheel is version 1.7.1 and is distributed under the BSD license. Neither asset contains Capture One data.
