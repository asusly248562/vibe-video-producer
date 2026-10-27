# Vibe 知识大赏制作 Skill

当前版本：**0.2.0**。

把知识主题与背景音乐整理成中文科普短视频，并交付封面和发布文案。适用于支持本地 Agent Skills 的 Codex 工作环境。

默认制作偏好：横屏16:9、1920×1080、30fps，大字短字幕，无额外配音，依据音乐实际节拍剪辑。完整交付包括MP4、4:3横封面、3:4竖封面、标题、简介与话题，以及可继续编辑的源码。

## 安装与调用

下载本仓库，将整个文件夹放入你的 Codex skills 目录，并将文件夹命名为 `vibe-video-producer`。常见目录为 `~/.codex/skills/vibe-video-producer/`，其中应直接包含 `SKILL.md`。

也可以向支持 GitHub 技能安装的 Codex 说明：

> 使用 skill-installer 安装 https://github.com/asusly248562/vibe-video-producer

调用示例：

> 使用 $vibe-video-producer，主题是“机会成本”，音乐用我提供的MP3，其余按默认风格，交付视频、两张封面和发布文案。

支持继续修改已有工程，例如“放大周围标签”“切镜更快”“按鼓点重排”“只生成封面和标题”。用户要求、既有项目设置和已经明确的授权优先于默认值。

## 制作流程

知识核对 → 短文案与分镜 → 音乐测拍与帧级事件表 → 视频工程和预览 → 本地渲染与验证 → 双尺寸封面 → 发布文案与归档。

这是由代理执行的工作流程与辅助脚本，不是独立视频生成服务。文案、事实核查、视觉制作和工具选择由代理结合实际工具完成；节拍测量需要试听或波形复核，不能把帧舍入误差当成测拍准确度。

## 依赖与可选技能

- Python 3.10+；音频分析与同步检查需要 NumPy，可执行 `python -m pip install -r requirements.txt`。
- 本地 FFmpeg / FFprobe，在PATH中或通过脚本参数指定。
- 视频制作需要可用的渲染器、浏览器及其运行环境。默认优先 HyperFrames；用户已有 OpenFilm 或剪映项目时可延续原工程。
- 配套技能按需使用：`hyperframes-vibe-169`、`lemo-opuscar`、`painted-animation`（Joker-chichi/claude-mv-skill）、`imagegen`、`openfilm`、`jianying-editor`。本仓库不附带它们，也不要求每期全部运行。
- 栅格封面生成需要可用的图片生成工具；本仓库不附带模型、账号或API密钥。

## 辅助工具

在本仓库目录运行，路径有空格时请加引号：

```text
python scripts/create_project.py --workspace <工作区> --slug <主题短名> --topic <主题> --music <MP3路径>
python scripts/beat_plan.py analyze --music <音乐路径> --out <beat-grid.json> --seconds 50 --ffmpeg <ffmpeg路径>
python scripts/beat_plan.py plan --grid <beat-grid.json> --story <storyboard.json> --out <beat-map.json>
python scripts/audit_render.py --video <MP4路径> --plan <beat-map.json> --score <最终配乐路径> --out <audit.json> --ffmpeg <ffmpeg路径>
```

- `create_project.py`：建立独立项目、复制输入音乐并保存偏好，避免覆盖同名项目。
- `beat_plan.py`：估计拍点，将分镜拍数、公式出现和数值变化等事件统一映射到视频帧。支持手动指定BPM与首拍。
- `audit_render.py`：检查最终MP4的规格、帧数、完整解码和可选音轨同步，不能替代人工画面检查。
- `project_state.py`：登记交付物的文件指纹，检查缺项、文件修改与旧报告失效；支持完整制作、仅视频、双封面、单封面与仅文案的验收范围。
- `assets/hyperframes-clock.js`：可复用的GSAP时间线时钟，处理六位小数边界误差和屏蔽回调时的绘制。

详细说明见 [SKILL.md](SKILL.md)、[时序与渲染](references/timing-and-render.md)、[视觉与交付](references/visual-and-delivery.md) 和 [断点续做与验收](references/project-state.md)。

## 断点续做

```text
python scripts/project_state.py record --project <项目目录> --kind video --path final/video.mp4
python scripts/project_state.py status --project <项目目录> --scope full --require-ready
```

替换成片、时序或配乐后，旧检查报告无法继续通过验收。实际逐帧、知识和手机可读性检查仍须完成后记录；状态文件不产生用户授权，也不代替视觉判断。对CSS/JS或插图的修改仍需重新导出并检查受影响部分。

## 运行测试

```text
python -m unittest discover -s tests -v
```

测试仅在临时项目里创建合成音视频，不使用个人素材。FFmpeg、Node在PATH中时会自动启用相应检查，也可通过VIBE_FFMPEG、VIBE_NODE指定可执行文件；可选VIBE_GSAP指向真实GSAP的CommonJS模块执行时间线回归。没有FFmpeg/Node时，相应测试明确显示为跳过，不能据此宣称完整媒体验证已经通过。

脚本已使用隔离的合成音频、测试视频和真实GSAP时间线验证，包括错误帧数与80ms音轨偏移的检出。仍需对实际成片逐镜检查、核对知识事实与封面文字。

仓库仅包含流程、原始辅助代码和默认配置，不包含用户音乐、视频、聊天记录、私人文件或第三方二进制；使用者自行提供项目素材。
