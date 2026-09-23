# Band Studio · 乐队创作工作室

一个用于 Codex 的 **Agent Skill**，将音乐制作、视频处理和素材研究整理成可复用的协作流程。

**Rehearsal-to-demo, performance video and source-backed media workflows for bands.**

从一段排练动机、一份词稿或一个素材目录开始，按任务选择角色，完成可试听、可查看、可核验的交付物。

## 能做什么

- **音乐**：整理原动机的保留要求，发展歌词与段落，核查当前 Suno 输入与实际生成结果。
- **现场视频**：歌词对齐、字幕、调色与剪辑流程；对混录时码的不确定性如实处理。
- **素材库**：索引照片/音视频、可选哈希去重、技术探测、版本与来源记录。
- **视觉制作**：真实素材选片、照片墙和海报工作分工、导出后的视觉核验。
- **协作**：8 个专项角色加主协调者，按需要并行；没有子代理工具时顺序执行。

这是一套工作流和本地辅助脚本，**不是模型权重、已登录的 Suno 客户端或开箱即用的音乐转录模型**。它不包含乐队原始素材、研究数据库、完整歌词、账号或历史聊天。Suno、浏览器、Jev 和音频引擎是可选的运行环境能力，使用时检查实际可用性。

## 安装

在 Codex 中让技能安装器从这个仓库安装 `skills/band-studio`，或手动复制：

```sh
git clone https://github.com/z23711195-ctrl/band-studio-skill.git
python3 - <<'PYTHON'
from pathlib import Path
import shutil
source = Path("band-studio-skill/skills/band-studio")
target = Path.home() / ".codex" / "skills" / "band-studio"
target.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(source, target)  # Refuses an existing target.
PYTHON
```

复制前确认目标目录不存在；已有安装应先比较版本，避免覆盖本地改动。安装后在新的会话中调用 `$band-studio`；是否热加载以当前客户端实际状态为准。

## 使用例子

```text
用 $band-studio 把这段哼唱发展成完整中文 Ska 小样，保留旋律和停顿，Sax 做应答。

用 $band-studio 把这份原词加到现场视频里，调整紫色灯光偏色，保留现场声音。

用 $band-studio 整理我指定目录的照片和视频，做素材索引，再挑选照片制作照片墙。
```

## 内置脚本

需要 Python 3.10+。脚本本身仅依赖标准库，不包含媒体、模型或第三方库。

```sh
cd band-studio-skill/skills/band-studio
python3 scripts/doctor.py
python3 scripts/catalog.py /path/to/media --output /path/to/new-index --probe --hash
python3 scripts/verify_delivery.py /path/to/final.mp4 --srt /path/to/lyrics.srt --expect-duration 60
```

使用 `--help` 查看参数。显式二进制参数或环境变量 `BAND_STUDIO_FFMPEG`、`BAND_STUDIO_FFPROBE` 可选择独立运行时；不修改系统默认工具。

| 脚本 | 真实能力 | 不代表什么 |
|---|---|---|
| doctor.py | FFmpeg/FFprobe 与关键滤镜、编码器检测 | 不证明登录、模型已下载或音乐理解正确 |
| catalog.py | 文件清单，可选 SHA256 和 FFprobe 元数据 | 不证明看过图片、听过作品或可公开素材 |
| verify_delivery.py | 成片格式、指定尺寸/时长、SRT 时序检查 | 不证明字幕已烧录、逐字同步或听感达标 |

FFmpeg 的构建可能不包含 `ass/subtitles/drawtext`。先检测，再为当前任务选择可用构建。音频分析、字幕渲染和 Suno 操作由宿主现有工具完成，不会因安装 Skill 自动获得云端服务。

## 验证与开发

```sh
python3 -m unittest discover -s tests -v
```

发布前使用 Skill Creator 的 `quick_validate.py` 检查 Skill 元数据，同时执行本地合成素材测试。模拟测试与真实媒体核验分别报告；所有仓库测试使用临时或合成数据。

## 隐私与数据

索引和脚本默认只在本地运行。原件不改写，输出目录应新建。外部上传、发布、付费和播放遵循当前用户的具体授权。请勿向本仓库提交原始媒体、完整版权词稿、私有资料库、凭据、cookie 或个人路径记录。

本仓库的原创工作流与脚本采用 [MIT License](LICENSE)。可选第三方工具独立安装，遵守各自许可证与服务条款；本项目不附带它们的代码或权重，也不隶属于 Suno、OpenAI 或 TypeSafe。
