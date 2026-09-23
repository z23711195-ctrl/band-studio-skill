---
name: band-studio
description: >-
  Coordinate a band's rehearsal-to-demo and media workflow: develop a supplied motif into a Suno demo, research reference recordings, maintain a source-backed media library, and produce captioned or graded performance videos and band visuals. Use for 乐队动机、Suno 小样、现场字幕调色、照片墙和乐队素材库 tasks; follow the requested deliverable rather than starting every workflow.
---

# Band Studio · 乐队创作工作室

把用户提供的乐队录音、词稿、照片或现场视频，推进到本次要求的可检查交付物。
这是可复用的角色分工与工作流；不会复制旧会话、模型能力、登录状态或私有资料库。

## 先明确本次交付

从当前对话和项目说明提取：输入素材、必须保留的旋律/节奏/原词/版本、允许修改的范围、目标风格、交付形式、播放与上传偏好。旧项目的单曲偏好不自动适用于新曲。

能从素材和已有说明确定的事直接执行。只追问会改变结果的缺口。若只要提示词、字幕或文件整理，不扩展成整首生成或全面建库。

- **排练动机 → 歌曲**：读 [music.md](references/music.md)，实际操作 Suno 时再读 [suno.md](references/suno.md)。
- **视频字幕、调色、花絮**：读 [video.md](references/video.md)。
- **作品研究、媒体入库、照片墙、海报**：读 [library-and-visual.md](references/library-and-visual.md)。
- **需要协作**：按 [roles.md](references/roles.md) 分配独立子任务。简单任务由一个代理完成，不为展示团队而启动所有角色。
- **Jev 辅助判断**：参考资料或已审阅素材有多个候选、Suno 提交前存在语义约束、交付结论需要对证据时，按 [jev.md](references/jev.md) 调用内置适配器。已配置且本次文字处理获授权时，主动调用，不等用户再提醒；简单操作直接执行。

## 可执行工具

以下路径相对本 Skill 目录。脚本仅使用 Python 3.10+ 标准库；媒体探测需要 FFprobe，渲染需要本机 FFmpeg 或所选编辑工具。

```sh
python3 scripts/doctor.py
python3 scripts/catalog.py /path/to/authorized-media --output /path/to/new-index --probe --hash
python3 scripts/verify_delivery.py /path/to/final.mp4 --srt /path/to/lyrics.srt --expect-duration 60
python3 scripts/jev.py preflight --input /path/to/brief.json --output /path/to/new-review.json --execute
```

具体参数以各脚本 `--help` 为准。FFmpeg 不在 PATH 时可显式指定 `--ffmpeg` / `--ffprobe`，或设置 `BAND_STUDIO_FFMPEG` / `BAND_STUDIO_FFPROBE`。脚本不会自动安装依赖、登录或播放；只有 `jev.py --execute` 会将明确准备的文字发送到 TypeSafe，默认仅本地检查。

检测只决定后续哪条路径可用：某个字幕滤镜缺失不妨碍整理素材；找到 Whisper 命令不证明其模型可用；没有音频理解工具时不能将数值测量写成听感。

## 协作与执行

1. 保持原件不变，先做文件格式与身份核对。大型库优先引用路径，避免无目的复制。
2. 按本次交付选最少角色。并行任务各写独立输出目录；主协调者负责合并、调用外部生成服务和交付。
3. 优先复用安装好的、适合当前媒介的技能或工具；首次使用先查看其说明。没有某个可选技能时，用已验证的等价工具继续，不伪装成已安装。
4. 将确认事实、测量候选、真实音视频观察、创作提案和用户认可分别记录，规则见 [evidence.md](references/evidence.md)。
5. 持续保存可接续的任务状态。连接故障时复用当前授权与素材状态，先定位问题层，避免要求用户反复登录或重复上传。
6. 完成可观察核验，再报告结果。描述词不是歌曲，索引不是听辨，FFprobe 成功不是视觉或审美验收。

Jev 负责候选排序、语义冲突和证据匹配，不承担写歌、媒体感知或实际执行。优先批量一次询问、复用缓存；低信心、证据不足或接口不可用时由主协调者接手。不要把 Jev 失联升级为整个任务阻塞，也不要把其评分当作媒体已通过验收。

## 交付边界

- 歌曲：核实服务端完成状态、对应来源和可访问结果链接；文件交付仅在本次需要时下载。未经实际音频核验，不评价旋律、歌词或音色已保留到什么程度。
- 视频：核实成片时长、画幅、声轨、字幕时间轴，并实际看导出帧。SRT 有效不证明字幕已烧录。不能仅因格式检查通过就称完全同步。
- 素材库：报告索引、去重、技术探测、实际查看/听辨各自的覆盖数；缺失或失败保留在报告中。
- 视觉：核对真实照片、Logo、字形、人物和乐器；交付可直接查看的成品及必要源文件。筛图结果不能代替照片墙或海报。

用户提供的素材只在当前授权范围处理。入库不等于同意云端上传；发布流程代码不等于同意公开原始素材、歌词或个人资料。新建输出，避免覆盖未知文件。对结果如实报告已验证项和仍需核听/审阅的部分。
