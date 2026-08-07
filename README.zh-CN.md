# Natural iPhone ProRAW

[English](README.md) · **简体中文**

一个同时适用于 Codex 与 Claude Code 的确定性 iPhone ProRAW 显影 skill：不使用生成式编辑，将 Apple iPhone ProRAW DNG 处理为自然、克制的成片。

可调用的 skill 名称是 `render-iphone-proraw-naturally`。

## 它能做什么

这个 skill 先从 RAW 数据构建克制的自然相机底片，再按需加入适合直接分享的完成度。目标是降低苹果计算摄影的可见痕迹，同时完整保留真实拍摄内容。

- 从 ProRAW DNG 解码输出像素，不复制内嵌预览图
- 保留原始构图、人物、物体、标识和文字
- 避免阴影被统一抬亮、微反差过硬、颜色发荧光和高光断裂
- 输出 8-bit sRGB JPEG 和 16-bit Display P3 TIFF
- 生成包含 ProRAW 元数据与曝光检查的结构化诊断 JSON
- 支持单文件、多文件和文件夹直属 `.dng` 批处理
- 默认移除 GPS 元数据
- 不使用图像生成、局部重绘、换天空或场景重建

## 显影控制

### 强度

- `auto`：优先使用已校准的相机型号规则；没有对应规则时保守回退到 `standard`
- `light`：中间调更通透，颜色略充实
- `standard`：默认的自然相机 S 曲线
- `strong`：阴影更扎实，颜色更克制

### 完成方式

- `social`：默认的直接分享成片；使用克制的感知鲜艳度与保色相的 sRGB 色域压缩
- `neutral`：适合继续后期处理的保守底片

## 安装

### Codex

把公开仓库克隆到 Codex skills 目录：

```bash
git clone https://github.com/Beluga0105/render-iphone-proraw-naturally.git \
  ~/.codex/skills/render-iphone-proraw-naturally
```

如果 skill 没有立即出现，请重启 Codex。

### Claude Code

把同一个仓库克隆到 Claude Code 的个人 skills 目录：

```bash
git clone https://github.com/Beluga0105/render-iphone-proraw-naturally.git \
  ~/.claude/skills/render-iphone-proraw-naturally
```

Claude Code 会直接读取同一份 `SKILL.md`，调用方式是 `/render-iphone-proraw-naturally`。只有在新建的顶层 skills 目录没有被识别时才需要重启 Claude Code。

首次显影需要联网。内置启动脚本会创建隔离的 `.runtime` 环境，并安装 `scripts/requirements.lock` 中锁定的依赖版本。

## 在 Codex 和 Claude Code 中使用

### Codex

调用 skill 名称，并附上 Apple iPhone ProRAW `.dng` 文件：

```text
使用 $render-iphone-proraw-naturally 去除这张 ProRAW 的苹果计算摄影感，并输出可直接分享的成片。
```

```text
使用 $render-iphone-proraw-naturally 诊断并自然显影这张 DNG，给我 JPEG、16-bit TIFF 和诊断报告。
```

### Claude Code

使用斜杠命令传入 DNG 路径，或在当前会话中附上文件：

```text
/render-iphone-proraw-naturally /绝对路径/photo.dng
```

两个平台都应返回 JPEG、TIFF 和诊断 JSON 的路径，并说明最终强度、完成方式、相机型号规则置信度、质量检查状态和警告。

## 命令行使用

在 skill 目录中运行：

```bash
python3 scripts/run.py "/绝对路径/photo.dng"
```

选择不同的显影强度或完成方式：

```bash
python3 scripts/run.py "/绝对路径/photo.dng" \
  --strength light \
  --finish neutral
```

处理多个文件，或处理一个目录下直属的全部 `.dng`：

```bash
python3 scripts/run.py "/路径/photo-01.dng" "/路径/photo-02.dng"
python3 scripts/run.py "/DNG文件夹路径"
```

只检查 ProRAW 元数据而不显影：

```bash
python3 scripts/run.py "/绝对路径/photo.dng" --diagnose-only
```

常用选项：

```text
--strength auto|light|standard|strong
--finish neutral|social
--output-dir /绝对输出路径
--overwrite
--keep-gps
--diagnose-only
--finalize
```

不使用 `--finalize` 时，显影结果属于对比候选；已有结果不会被覆盖，新文件会自动增加 `-v2`、`-v3` 等后缀。目视确认后，用选定的强度和完成方式重新运行并加入 `--finalize`，发布唯一一组规范命名的 JPEG + TIFF + JSON，同时只清理同一源文件的已识别输出。

## 输出

默认的 `standard` + `social` 显影会生成：

```text
photo-natural-standard-social-sRGB.jpg
photo-natural-standard-social-16bit-P3.tif
photo-natural-standard-social-diagnostic.json
```

- **JPEG：** 完成版 8-bit sRGB，可直接分享
- **TIFF：** 完成版 16-bit Display P3 母版
- **诊断 JSON：** 相机元数据、ProRAW 标签摘要、显影决策、亮度统计、饱和度统计和 `quality_check`

原始 DNG 保持不变。输出先写入非点号开头的临时文件，只有完整处理成功后才正式发布到目标目录。在 macOS 上，发布过程会清除并验证 `UF_HIDDEN`；如果最终文件仍在 Finder 中隐藏，显影会直接报错，不再误报成功。

## 隐私与内容完整性

- 默认移除 GPS；只有明确需要保留位置信息时才使用 `--keep-gps`。
- 工作流不会把照片上传到图像生成服务。
- 输出像素来自 RAW 解码；DNG 内嵌预览图只用于有限的全局影调参考。
- 不添加、删除或重建画面内容。

## 运行要求

- 64-bit CPython 3.9 或更高版本
- Apple iPhone ProRAW `.dng` 输入
- 首次运行时需要联网安装锁定依赖
- 官方 `rawpy` wheel 支持的平台：macOS arm64、Windows x86-64、Linux x86-64/aarch64

锁定的运行环境使用 `rawpy`、`NumPy`、`Pillow` 和 `tifffile`。

## 能力边界

Apple ProRAW 本身已经包含多帧计算处理。这个工作流能够降低其可见的影调、色彩和微反差特征，但无法重建未经计算处理的单帧传感器数据。

尚未校准的 iPhone 型号会保守使用 `standard`，并要求人工目视检查。曝光警告只是复核信号，不等于照片一定曝光错误；夜景、剪影、雪景、太阳和镜面高光都可能合理触发警告。

JPEG 和 HEIC 不能代替 RAW 输入。

## 仓库结构

- `SKILL.md`：Codex 与 Claude Code 共用的工作流和验收规则
- `agents/openai.yaml`：Codex 界面元数据；Claude Code 会安全忽略
- `scripts/`：运行环境启动、诊断、RAW 显影管线和入口脚本
- `references/rendering-model.md`：显影模型、阈值和技术决策
- `assets/profiles/`：内嵌 sRGB 与 Display P3 ICC 配置文件
- `assets/wheels/`：支持 SOCKS 代理环境的启动资源

## 许可

本项目采用 [MIT License](LICENSE)。

第三方组件继续适用其原始许可证，详见 [THIRD_PARTY_NOTICES.txt](assets/THIRD_PARTY_NOTICES.txt)。
