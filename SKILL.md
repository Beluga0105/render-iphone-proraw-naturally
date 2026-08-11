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
3. Resolve the skill directory before running the bundled scripts.
   - In Claude Code, use `${CLAUDE_SKILL_DIR}`. Claude Code expands it to the directory containing this `SKILL.md`.
   - In Codex or another compatible host, locate the directory containing this `SKILL.md` and run from that directory.

In Claude Code, run:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/run.py" "/absolute/path/photo.dng"
```

In Codex or from a terminal already opened in the skill directory, run:

```bash
python3 scripts/run.py "/absolute/path/photo.dng"
```

Use `py -3 scripts/run.py ...` on Windows when `python3` is not an available command. In Claude Code on Windows, use `py -3 "${CLAUDE_SKILL_DIR}/scripts/run.py" ...`.

The default `--finish social` applies restrained perceptual vibrance and hue-preserving sRGB gamut compression after neutralization. Use `--finish neutral` only when the user explicitly wants a conservative base for further editing.

The default `--regional-shadows auto` detects a well-exposed upper region with a substantially darker lower/foreground region. It then applies a smooth, luminance-only recovery mask to the recoverable dark area while protecting bright sky, highlights, true black, and hue relationships. Use `--regional-shadows off` to compare against the legacy global adaptation path, or `--regional-shadows on` to force the same bounded safe mask when visual inspection justifies it. Scale the effect with `--regional-shadow-strength 0..1`; the maximum at `1` is `0.65 EV`.

Pass multiple files or directories for a batch. Directory inputs include only immediate `.dng` children.

4. Use `--output-dir "/absolute/path"` only when the user names a destination. Otherwise accept the sibling `natural-camera-output` folder.
5. Keep comparison renders as temporary candidates. Without `--finalize`, the runner creates `-v2`, `-v3`, and so on when an equivalent filename exists. Never deliver a candidate as final.
6. Add `--keep-gps` only when the user explicitly asks to retain location metadata. GPS is stripped by default.
7. Read `quality_check` from the runner output. Check both global exposure metrics and `metrics.local_highlight_check`; a small overbright or clipped lamp, sign, window, reflection, or cloud must not disappear inside a low full-image average. Treat `review_required` as a warning, not proof of a bad exposure; night scenes, silhouettes, snow, sun, and specular reflections can legitimately trigger it. A `pass` never replaces visual review.
8. Read the diagnostic report. Confirm `BaselineExposure`, `ProfileToneCurve`, Hue/Sat map, and all three OpcodeList entries are either summarized or explicitly marked absent. Treat an unreadable present tag as a failure requiring explanation. Report whether the selected strength came from a calibrated model rule or the conservative fallback.
9. Inspect `regional_shadow_recovery`, `midtone_adaptation`, `scene_contrast_preservation`, and the final JPEG visually. Verify orientation, unchanged scene geometry and text, grounded blacks in naturally high-contrast scenes, visible shadow and highlight texture, open middle tones, clean color separation, sufficient color fullness for direct sharing, and smooth highlight roll-off. Inspect the full-resolution region reported by `local_highlight_check.peak_tile`; reject visibly textureless clipping even when global white clipping is low. When regional recovery is applied, confirm that bright sky/highlights do not drift and that mountain ridges, trees, buildings, and other boundaries do not develop halos. The DNG preview may guide only global tone decisions; output pixels must still come entirely from RAW decoding. Reject a floating-gray, muddy, crushed, neon, haloed, locally blown, or uniformly HDR-bright rendering even when the histogram passes. Check the reported affected area, maximum lift, protected/upper-region luminance change, local and global exposure metrics, luminance percentiles, and saturation percentiles as supporting evidence, not as universal targets.
10. If the user did not request a specific strength and the selected output has an unintended exposure problem:
   - For crushed or excessively dense shadows, render a `light` candidate and compare both JPEGs.
   - For globally or locally overbright/clipped highlights, render one darker preset and compare the reported peak region at full resolution.
   - When shadow crush and local highlight clipping coexist, do not choose `light` solely to open the dark area. Also compare a one-step-darker preset with `--regional-shadows on`; this can open only safe dark regions while retaining the darker preset's highlight protection.
   - Deliver only the better candidate. If neither is acceptable, report the limitation instead of claiming success.
11. After visual acceptance, rerun the selected strength and finish with `--finalize`. This publishes one canonical JPEG + TIFF + diagnostic JSON group and deletes only recognized candidate/version/diagnose-only outputs for the same source stem. Cleanup occurs only after all three final files are complete and the source DNG hash is unchanged.
12. Confirm `publication.mode` is `final`, inspect `removed_candidates`, and verify that exactly one JPEG + TIFF + diagnostic JSON group remains for each source. Report clickable absolute paths for those three files; the selected strength and finish; whether the model rule was calibrated; the `quality_check` status; and any warnings.

For metadata inspection without rendering, run:

```bash
python3 scripts/run.py "/absolute/path/photo.dng" --diagnose-only
```

## Output contract

Candidate runs select a concrete preset, apply the requested finish, and may create versioned files for comparison. The accepted render must be rerun with `--finalize`, which leaves only:

- `<stem>-natural-standard-social-sRGB.jpg`: finished 8-bit sRGB, JPEG quality 96.
- `<stem>-natural-standard-social-16bit-P3.tif`: finished 16-bit Display P3 TIFF.
- `<stem>-natural-standard-social-diagnostic.json`: structured ProRAW diagnostic, strength decision, regional-shadow decision and protection metrics, preview-guided global tone decisions, finish method, global and local exposure checks, and saturation statistics.

The concrete strength and finish replace `standard-social` when another choice is selected. A successful finalization removes other recognized outputs sharing the same source stem, including versioned render groups and diagnose-only reports, but never deletes the source DNG or unrelated files. The original DNG must remain byte-for-byte unchanged. The runner writes all outputs through non-dot-prefixed temporary files and publishes them only after they are complete. Published files must be visible in Finder and other file managers; on macOS the runner clears and verifies the absence of `UF_HIDDEN`, failing the render instead of reporting success if a final output remains hidden.

The runner checks the final encoded JPEG with both a full-image luminance histogram and a portrait/landscape-aware local grid. It reports black clipping, deep-shadow coverage, bright-highlight coverage, white clipping, local peak-tile clipping, and 1st/50th/99th-percentile luma. See [references/rendering-model.md](references/rendering-model.md) for thresholds.

## Handle failures

- Stop and report the runner's error for a damaged file, non-DNG input, non-Apple camera, non-iPhone model, missing 64-bit Python 3.9+, dependency failure, or unsupported LibRaw file.
- Do not silently fall back to the embedded JPEG preview, Apple Photos, Capture One, or a generative image tool.
- If one item in a batch fails, report that item separately; successful items remain valid.
- Never clean candidates after a failed render, failed source-hash check, or incomplete final group.
- Explain that ProRAW already contains Apple multi-frame computation. This workflow reduces its visible tone, color, and microcontrast character but cannot reconstruct an untouched single sensor frame.

Read [references/rendering-model.md](references/rendering-model.md) only when changing presets or model rules, interpreting DNG diagnostics, diagnosing color differences, reviewing dependencies, or explaining technical limitations.
