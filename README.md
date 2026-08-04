# Natural iPhone ProRAW

**English** · [简体中文](README.zh-CN.md)

A Codex and Claude Code skill for deterministically developing Apple iPhone ProRAW DNG photos into natural, restrained images without generative editing.

The callable skill name is `render-iphone-proraw-naturally`.

## What It Does

The skill builds a restrained natural-camera rendering from the RAW image, then applies an optional sharing-ready finish. It is designed to reduce the visible Apple computational-photography character while preserving the photographed scene.

- decodes pixels from the ProRAW DNG rather than copying the embedded preview
- preserves the original composition, faces, objects, signs, and text
- avoids HDR-like lifted shadows, harsh microcontrast, neon color, and brittle highlights
- exports an 8-bit sRGB JPEG and a 16-bit Display P3 TIFF
- writes a structured diagnostic JSON with ProRAW metadata and exposure checks
- supports individual files, multiple files, and immediate-child batch folders
- strips GPS metadata by default
- never uses image generation, inpainting, sky replacement, or scene reconstruction

## Rendering Controls

### Strength

- `auto`: use a calibrated camera-model rule when available; otherwise fall back conservatively to `standard`
- `light`: airier middle tones and slightly fuller color
- `standard`: the default natural-camera S-curve
- `strong`: denser shadows and more restrained color

### Finish

- `social`: the default sharing-ready finish with restrained perceptual vibrance and hue-preserving sRGB gamut compression
- `neutral`: a conservative base for further editing

## Installation

### Codex

Clone the public repository into the Codex skills directory:

```bash
git clone https://github.com/Beluga0105/render-iphone-proraw-naturally.git \
  ~/.codex/skills/render-iphone-proraw-naturally
```

Restart Codex if the skill does not appear immediately.

### Claude Code

Clone the same repository into the Claude Code personal skills directory:

```bash
git clone https://github.com/Beluga0105/render-iphone-proraw-naturally.git \
  ~/.claude/skills/render-iphone-proraw-naturally
```

Claude Code reads the same `SKILL.md` directly. Invoke it with `/render-iphone-proraw-naturally`. Restart Claude Code only if a newly created top-level skills directory is not detected.

The first rendering run requires an internet connection. The bundled bootstrap creates an isolated `.runtime` environment and installs the exact dependency versions declared in `scripts/requirements.lock`.

## Usage in Codex and Claude Code

### Codex

Invoke the skill by name and attach an Apple iPhone ProRAW `.dng` file:

```text
Use $render-iphone-proraw-naturally to diagnose and naturally develop this iPhone ProRAW for direct sharing.
```

```text
使用 $render-iphone-proraw-naturally 去除这张 ProRAW 的苹果计算摄影感，并输出可直接分享的成片。
```

### Claude Code

Invoke the slash command with a DNG path or attach the file in the current session:

```text
/render-iphone-proraw-naturally /absolute/path/photo.dng
```

Both hosts should return paths for the JPEG, TIFF, and diagnostic JSON, together with the selected strength, finish, model-rule confidence, quality-check status, and any warnings.

## Command-Line Usage

Run from the skill directory:

```bash
python3 scripts/run.py "/absolute/path/photo.dng"
```

Choose a different rendering strength or finish:

```bash
python3 scripts/run.py "/absolute/path/photo.dng" \
  --strength light \
  --finish neutral
```

Render several files or all immediate `.dng` children of a directory:

```bash
python3 scripts/run.py "/path/photo-01.dng" "/path/photo-02.dng"
python3 scripts/run.py "/path/to/dng-folder"
```

Inspect ProRAW metadata without rendering:

```bash
python3 scripts/run.py "/absolute/path/photo.dng" --diagnose-only
```

Useful options:

```text
--strength auto|light|standard|strong
--finish neutral|social
--output-dir /absolute/output/path
--overwrite
--keep-gps
--diagnose-only
```

Without `--overwrite`, existing results are preserved and new files receive `-v2`, `-v3`, and later suffixes.

## Output

A default `standard` + `social` render creates:

```text
photo-natural-standard-social-sRGB.jpg
photo-natural-standard-social-16bit-P3.tif
photo-natural-standard-social-diagnostic.json
```

- **JPEG:** finished 8-bit sRGB, suitable for direct sharing
- **TIFF:** finished 16-bit Display P3 master
- **Diagnostic JSON:** camera metadata, ProRAW tag summaries, rendering decision, luminance statistics, saturation statistics, and `quality_check`

The original DNG remains unchanged. Output files are written through temporary files and published only after the render completes.

## Privacy and Content Integrity

- GPS is removed by default; use `--keep-gps` only when location metadata is intentionally required.
- The workflow does not upload the image to an image-generation service.
- Output pixels come from RAW decoding. The embedded DNG preview is used only for limited global tone guidance.
- The workflow never adds, removes, or reconstructs scene content.

## Requirements

- 64-bit CPython 3.9 or newer
- Apple iPhone ProRAW `.dng` input
- internet access on the first run to install pinned dependencies
- a platform supported by the official `rawpy` wheels: macOS arm64, Windows x86-64, or Linux x86-64/aarch64

The pinned runtime uses `rawpy`, `NumPy`, `Pillow`, and `tifffile`.

## Limitations

Apple ProRAW already contains multi-frame computational processing. This workflow reduces its visible tone, color, and microcontrast character, but it cannot reconstruct an untouched single sensor frame.

Unknown iPhone models conservatively use the `standard` preset and require visual review. Exposure warnings are review signals rather than automatic proof of a bad image, especially for night scenes, silhouettes, snow, the sun, and specular highlights.

JPEG and HEIC files are not accepted as substitutes for RAW input.

## Repository Structure

- `SKILL.md`: shared Codex and Claude Code workflow and acceptance rules
- `agents/openai.yaml`: Codex UI metadata; harmlessly ignored by Claude Code
- `scripts/`: bootstrap, diagnostics, RAW pipeline, and runner
- `references/rendering-model.md`: rendering model, thresholds, and technical decisions
- `assets/profiles/`: embedded sRGB and Display P3 ICC profiles
- `assets/wheels/`: bootstrap support for SOCKS proxy environments

## License

No open-source license has been added yet. Until a license is selected, the repository remains publicly viewable but does not grant general permission to copy, modify, or redistribute the code.
