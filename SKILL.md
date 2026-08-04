---
name: render-iphone-proraw-naturally
description: Deterministically diagnose, develop, finish, and exposure-check Apple iPhone ProRAW DNG photos into a natural, social-media-ready rendering without Capture One or generative editing. Use when the user asks to inspect DNG diagnostics; reduce the Apple computational-photography look; restore natural color after neutralization; produce a finished photo ready to share; compare against a Capture One reference; or export sRGB JPEG and 16-bit Display P3 TIFF. Trigger on Chinese requests such as 去除苹果计算摄影感、自然显影 ProRAW、恢复颜色、直接出片、社交媒体成片、相机质感、胶片标准曲线, and related English requests.
---

# Natural iPhone ProRAW

Develop Apple ProRAW with a deterministic two-stage pipeline: create a restrained natural-camera base, then apply a controlled social-media finish that restores color without restoring phone HDR tonality. Preserve every photographed pixel, object, sign, face, and composition. Do not launch Capture One and do not use image generation, inpainting, sky replacement, or other generative editing.

## Run the workflow

1. Confirm that each requested input is an Apple iPhone `.dng`. Do not convert a JPEG or HEIC and present it as RAW.
   - If the user supplies a paired reference JPEG, verify matching dimensions and composition. Use it only to compare global tone, color separation, and visual acceptance; never substitute it for RAW decoding or copy scene content from it.
2. Use model-aware `auto` unless the user explicitly requests a lighter or stronger reduction. `auto` reads the DNG diagnostics and currently falls back conservatively to `standard` for an uncalibrated model:
   - `light`: use airier middle tones and slightly fuller color.
   - `standard`: use the calibrated natural-camera S-curve default.
   - `strong`: use denser shadows and more restrained color without crushing midtones.
3. Run from the skill directory:

```bash
python3 scripts/run.py "/absolute/path/photo.dng"
```

Use `py -3 scripts/run.py ...` on Windows when `python3` is not an available command.

The default `--finish social` applies restrained perceptual vibrance and hue-preserving sRGB gamut compression after neutralization. Use `--finish neutral` only when the user explicitly wants a conservative base for further editing.

Pass multiple files or directories for a batch. Directory inputs include only immediate `.dng` children.

4. Use `--output-dir "/absolute/path"` only when the user names a destination. Otherwise accept the sibling `natural-camera-output` folder.
5. Add `--overwrite` only when the user explicitly authorizes replacement. Otherwise the runner creates `-v2`, `-v3`, and so on.
6. Add `--keep-gps` only when the user explicitly asks to retain location metadata. GPS is stripped by default.
7. Read `quality_check` from the runner output. Treat `review_required` as a warning, not proof of a bad exposure; night scenes, silhouettes, snow, sun, and specular reflections can legitimately trigger it. A `pass` never replaces visual review.
8. Read the diagnostic report. Confirm `BaselineExposure`, `ProfileToneCurve`, Hue/Sat map, and all three OpcodeList entries are either summarized or explicitly marked absent. Treat an unreadable present tag as a failure requiring explanation. Report whether the selected strength came from a calibrated model rule or the conservative fallback.
9. Inspect `scene_contrast_preservation` and the final JPEG visually. Verify orientation, unchanged scene geometry and text, grounded blacks in naturally high-contrast scenes, visible shadow and highlight texture, open middle tones, clean color separation, sufficient color fullness for direct sharing, and smooth highlight roll-off. The DNG preview may guide only global black-point detection; output pixels must still come entirely from RAW decoding. Reject a floating-gray, muddy, crushed, neon, or uniformly HDR-bright rendering even when the histogram passes. Check the reported luminance and saturation percentiles as supporting evidence, not as universal targets.
10. If the user did not request a specific strength and the selected output has an unintended exposure problem:
   - For crushed or excessively dense shadows, render a `light` candidate and compare both JPEGs.
   - For clipped or excessively bright highlights, or when the standard rendering still has flattened light and shadow separation, render a `strong` candidate and compare both JPEGs.
   - Deliver only the better candidate. If neither is acceptable, report the limitation instead of claiming success.
11. Report clickable absolute paths for the JPEG, TIFF, and diagnostic JSON; the selected strength and finish; whether the model rule was calibrated; the `quality_check` status; and any warnings.

For metadata inspection without rendering, run:

```bash
python3 scripts/run.py "/absolute/path/photo.dng" --diagnose-only
```

## Output contract

The default `auto` run selects a concrete preset, applies the `social` finish, and creates:

- `<stem>-natural-standard-social-sRGB.jpg`: finished 8-bit sRGB, JPEG quality 96.
- `<stem>-natural-standard-social-16bit-P3.tif`: finished 16-bit Display P3 TIFF.
- `<stem>-natural-standard-social-diagnostic.json`: structured ProRAW diagnostic, strength decision, finish method, exposure check, and saturation statistics.

The concrete strength and finish replace `standard-social` when another choice is selected. The original DNG must remain byte-for-byte unchanged. The runner writes all outputs through temporary files and publishes them only after they are complete.

The runner checks the final encoded JPEG with a full-image luminance histogram and reports black clipping, deep-shadow coverage, bright-highlight coverage, white clipping, and 1st/50th/99th-percentile luma. See [references/rendering-model.md](references/rendering-model.md) for thresholds.

## Handle failures

- Stop and report the runner's error for a damaged file, non-DNG input, non-Apple camera, non-iPhone model, missing 64-bit Python 3.9+, dependency failure, or unsupported LibRaw file.
- Do not silently fall back to the embedded JPEG preview, Apple Photos, Capture One, or a generative image tool.
- If one item in a batch fails, report that item separately; successful items remain valid.
- Explain that ProRAW already contains Apple multi-frame computation. This workflow reduces its visible tone, color, and microcontrast character but cannot reconstruct an untouched single sensor frame.

Read [references/rendering-model.md](references/rendering-model.md) only when changing presets or model rules, interpreting DNG diagnostics, diagnosing color differences, reviewing dependencies, or explaining technical limitations.
