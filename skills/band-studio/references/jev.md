# Jev 在工作流中的接入

Jev 是可选的文字判断服务。使用已核实的资料和媒体观察组织输入；调用不会替代实际看图、听音、浏览器操作、歌词创作或剪辑。

## 何时主动调用

| 节点 | 模式 | 输入与用途 |
|---|---|---|
| 查到参考作品、形成来源卡后 | `rank` | 按本首歌的 brief，对候选来源卡/听辨记录排序；优先深入最相关项 |
| 已有素材观察、设计或剪辑候选后 | `rank` | 按用途排序候选；条目仅有文件名时不推断人物、声音或画面 |
| Suno 草稿准备好、正式提交前 | `preflight` | 原要求对照草稿或实际回读字段；发现风格、人声、保留要求间的冲突 |
| 交付说明准备好 | `evidence` | 对照具体证据，标出结论有支持、矛盾还是不足；先复核疑点 |

按任务只调用需要的节点。已有明确工具选择、哈希去重、字幕越界、原词精确差异，用程序直接判断。不为一个清楚的操作额外调用模型；不重复审核刚获用户认可且未改变的部分。

当前会话已允许 Jev 处理相关文字时沿用授权。只有安装 Skill 不代表允许上传私有资料。先准备最少必要文本，沿用已配置的凭据；不要要求用户重复提供已有密钥。没有配置时继续主代理路径并如实记录。

## 配置与命令

需要 Python 3.10+，无需第三方 Python 包。优先使用 `TYPESAFE_API_KEY` 环境变量；也可指定现有私有 dotenv：

```sh
python3 scripts/jev.py rank --input references/examples/jev-rank.json --output /path/to/new-rank.json --env-file /path/to/private.env --execute
```

长期复用可在本机 `~/.config/band-studio/jev.json` 写入以下配置；若设置了 `XDG_CONFIG_HOME`，配置位于该目录的 `band-studio/jev.json`。配置仅保存已有密钥文件的路径和可选模型名，不放进仓库：

```json
{"env_file": "/path/to/private.env", "model": "jev-latest"}
```

dotenv 使用 `TYPESAFE_API_KEY` 和可选 `TYPESAFE_DEFAULT_MODEL`。不执行文件中的 shell 代码；不要在命令参数、日志或聊天中写入密钥。

```sh
# 默认只校验输入、准备问题，不联网。
python3 scripts/jev.py preflight --input references/examples/jev-preflight.json --output /path/to/new-dry-run.json

# 已授权的文字判断；复用本机配置。
python3 scripts/jev.py preflight --input /path/to/current-fields.json --output /path/to/new-review.json --execute
python3 scripts/jev.py evidence --input references/examples/jev-evidence.json --output /path/to/new-evidence.json --execute
```

输出路径必须未存在。退出码：`0` 表示取得完整判断或完成 dry run，`2` 为无效输入/配置，`3` 为服务判断未完成；任何退出码都不表示音视频已验收。

## 输入

只接受下列字段，不会自动读取字段里提到的文件或网址。每批最多 24 条，输入最多 64 KiB，单个文本最多 6000 字符；用简短事实和必要摘录，保留未知项。

- `rank`：[示例](examples/jev-rank.json)。`brief` 描述目标；`candidates` 每项有唯一 `id`、`summary`、可选 `evidence`。排序依据提供的文字；高匹配分但依据不足仍需复核。
- `preflight`：[示例](examples/jev-preflight.json)。`requirements` 每项有唯一 `id`、`text`；`proposal` 接受 `styles`、`excluded_styles`、`lyrics` 文本和 `instrumental`、`source_attached` 布尔值。可选 `observed` 为同结构，放实际网页回读值。没有观察到的字段直接省略，不猜测。只有草稿时报告仅适用于计划，不能声称页面已经正确填入。
- `evidence`：[示例](examples/jev-evidence.json)。`claims` 每项有唯一 `id`、`claim` 和对应 `evidence`；资料不足写清楚不足，不补造听辨。

问题模板用英文表达判断规则，以减少服务当前对非英文判断的局限。保留原始中文材料；中文文学性、双关和唱词韵律由主协调者复核。

## 结果与效率

适配器把同批独立问题放进一次请求，记录实际模型、问题数量、用量、耗时、网络调用数和缓存来源。`rank` 每条包含匹配评分及依据充分性判断；`preflight` 区分支持、冲突、未知；`evidence` 区分支持、矛盾、证据不足。阅读疑点后由主协调者决定后续，不让分数直接触发上传、生成、发布或删除。

缓存键包含输入、问题模板和请求模型；默认有效期 24 小时。缓存仅存规范化判断，不保存输入原文或密钥。内容、规则或模型改变会重新判断；`jev-latest` 是可变别名，需要锁定实验时显式 `--model`，强制新请求使用 `--no-cache`。更改本地排序偏好不应无故重做语义判断。

默认单次超时 25 秒，不自动重试。超时、限额、鉴权错误、异常返回用 `deferred` 记录，由主代理继续工作；查明服务状态后再决定是否重试。模型置信度不是准确率，默认复核阈值只用于分配检查顺序，不是经真实乐队样本校准的验收线。

## 能力来源

接口核对日期：2026-09-23。当前 Jev 只接受文字，返回选择、评分与真假概率；不直接接收图像、音频或视频。

- [官方输入格式与模态](https://docs.typesafe.ai/concepts/state)
- [HTTP API](https://docs.typesafe.ai/api)
- [批量独立问题](https://docs.typesafe.ai/patterns/fan-out)
- [置信度含义](https://docs.typesafe.ai/confidence)

发布包不附带账号或额度。真实连通测试与离线模拟测试分别记录；不从一次调用推导整套工作流提速比例。
