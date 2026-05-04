# VideoAudioMixer — 使用手册

本项目包含多个命令行工具，用于视频音频的剪辑、合成与语音生成，以及一键流水线脚本。

---

## 依赖

- Python 3.8+
- FFmpeg（已安装并添加到 PATH，或与脚本放在同一目录）

---

## 工具一览

| 脚本 | 功能 |
|------|------|
| `srt_voice_gen.py` | 从 SRT 或 TXT 文件生成语音 MP3（ElevenLabs / Resemble.AI）|
| `mixer.py` | 将视频音轨替换为 MP3，可指定时间段保留原始音轨 |
| `clip_video.py` | 从视频文件截取指定时间段 |
| `clip_mp3.py` | 从 MP3 文件截取指定时间段 |
| `merge_mp3.py` | 将多个 MP3 文件串联合并为一个 |
| `speed_mp3.py` | 对 MP3 做变速处理（atempo，保持音调不变）|
| `assemble_segments.py` | 将 segments 目录的分块 MP3 合成为一个文件，块间加静音 |
| `srt_to_txt.py` | 从双语 SRT 中提取英文字幕，去除中文/时间轴/序号，输出 TXT |
| `mp3_to_srt.py` | 用 Whisper 转录 MP3，结合 TXT 文字生成时间对齐的 SRT |
| `srt_to_ass.py` | 将 SRT 转换为 ASS 格式，精确定义字幕框位置、字体、描边 |
| `add_subtitles.py` | 一键生成英文字幕并烧录到视频（MP3+TXT+SRT+MP4 → 带字幕 MP4）|
| **`pipeline.py`** | **一键流水线：输入 MP4 + SRT，自动完成全部步骤输出最终视频** |

---

## srt_voice_gen.py

从 SRT 字幕文件或纯文本 TXT 文件调用 TTS API 生成语音 MP3。

- **SRT 模式**：逐条字幕调用 API，自动对齐时间轴（atempo 拉伸/压缩）
- **TXT 模式**：按段落边界分块调用 API，顺序串联。每块自动携带前后块的上下文（`previous_text`/`next_text`），保证拼接处语调连贯

### 用法

```
python srt_voice_gen.py <input.srt|input.txt> [选项]
```

### 参数

#### 通用

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `input` | — | 输入文件，`.srt` 或 `.txt` |
| `-o`, `--output` | `voice_output.mp3` | 输出文件路径 |
| `--provider` | `elevenlabs` | TTS 服务商：`elevenlabs` / `resemble` |
| `--test` | 关 | 测试模式：只处理前 5 条/块 |
| `--segments-dir` | 自动 | 单独片段 MP3 输出目录（默认：`<输出文件名>_segments`），始终保留 |
| `--context-chars` | `200` | 传给 API 的上下文字符数（`previous_text`/`next_text`），`0`=关闭（仅 v2 模型有效） |
| `--log-requests` | 关 | 将每次 API 请求参数（不含文本）记录到 JSON 文件 |
| `--delay` | `0.3` | 每次 API 调用之间的间隔秒数 |

#### SRT 模式专用

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--duration` | 自动 | 输出总时长（秒），默认取最后一条字幕结束时间 |
| `--min-tempo` | `0.5` | 最小拉伸比，低于此值不做时间对齐 |
| `--max-tempo` | `1.5` | 最大压缩比，超出则截断 |

#### TXT 模式专用

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--max-chars` | `1000` | 合并短段落的上限字符数。段落本身超出此值但 ≤ 4500 字符时整段保留；超过 4500 才强制按句子切分（ElevenLabs 单次上限） |

#### ElevenLabs 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--el-model` | `eleven_v3` | 模型：`eleven_v3` / `eleven_multilingual_v2` / `eleven_turbo_v2_5` / `eleven_flash_v2_5` |
| `--el-api-key` | 读取 ElevenLabs.md | API Key |
| `--el-voice-id` | 读取 ElevenLabs.md | Voice ID |
| `--stability` | `0.75` | 声音稳定性 0~1，越低越有情感/越不稳定 |
| `--similarity-boost` | `0.8` | 与原声相似度 0~1，越低给模型越多发挥空间 |
| `--style` | `0.0` | 语气夸张度 0~1（v2 模型有效，建议 0.3~0.5） |
| `--speed` | `1.0` | 语速 0.7~1.2，1.0=正常（`eleven_v3` 不支持此参数） |
| `--post-speed` | `1.0` | 输出后处理加速倍率（FFmpeg atempo），1.0=不处理 |
| `--sentence-break` | `0.8` | 句尾停顿秒数，0=关闭。v2：插入 SSML `<break>`；v3：插入省略号（秒数越大点越多） |
| `--comma-break` | `0.2` | 逗号停顿秒数（仅 v2 模型 SSML） |
| `--sample-rate` | `44100` | 音频采样率 |

#### Resemble.AI 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--re-model` | `chatterbox` | 模型：`chatterbox` / `chatterbox-turbo` |
| `--re-api-key` | 读取 resembleAI.md | API Key |
| `--re-voice-uuid` | 读取 resembleAI.md | Voice UUID |

### v3 模型情感标签

`eleven_v3` 支持在文本中直接插入标签控制情感，逗号、句号等普通标点无需额外处理：

```
[excited]  [happy]  [sad]  [angry]  [fearful]  [surprised]
[calm]  [serious]  [nervous]  [playful]  [sarcastic]
[laughs]  [sighs]  [gasps]  [whispers]  [clears throat]  [crying]
```

示例（在 SRT 或 TXT 文件中直接写入）：
```
[excited] 今天有个重大消息要宣布！[laughs] 真的太棒了。
[calm] 接下来，[serious] 请大家注意以下几点。
```

### 示例

```bash
# SRT 模式，基础用法
python srt_voice_gen.py subtitle.srt -o voice.mp3

# SRT 模式，自定义参数
python srt_voice_gen.py subtitle.srt --stability 0.7 --similarity-boost 0.5 --speed 1.05 --sentence-break 1.0 -o voice.mp3

# TXT 模式，测试前 5 块
python srt_voice_gen.py script.txt --test -o test.mp3

# TXT 模式，记录请求日志
python srt_voice_gen.py script.txt --log-requests -o voice.mp3

# 使用 Resemble.AI
python srt_voice_gen.py subtitle.srt --provider resemble -o voice.mp3

# 使用 v2 模型（支持 SSML 停顿）
python srt_voice_gen.py subtitle.srt --el-model eleven_multilingual_v2 --sentence-break 0.8 --comma-break 0.2 -o voice.mp3
```

### 配置文件

API Key 和 Voice ID 存放在同目录下的 Markdown 文件中，程序自动读取：

**ElevenLabs.md**
```
API Key: sk_xxxxxxxxxxxxxxxx
Voice ID: xxxxxxxxxxxxxxxx
```

**resembleAI.md**
```
API Key: xxxxxxxxxxxxxxxx
Voice UUID: xxxxxxxx
```

### 请求日志格式

启用 `--log-requests` 后，输出 `<output名>_requests.json`：

```json
[
  {
    "chunk_index": 0,
    "timestamp": "2026-04-26T10:30:00",
    "provider": "elevenlabs",
    "model": "eleven_v3",
    "voice_id": "xxxxxxxx",
    "output_format": "mp3_44100_128",
    "sentence_break": 1.0,
    "comma_break": null,
    "v3_dots": "...",
    "voice_settings": {
      "stability": 0.7,
      "similarity_boost": 0.5,
      "style": 0.0,
      "use_speaker_boost": true,
      "speed": 1.05
    }
  }
]
```

---

## mixer.py

将视频音轨全程替换为指定 MP3，同时可指定若干时间段保留原始音轨。

### 用法

```
python mixer.py <video.mp4> <audio.mp3> [选项]
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `video` | — | 输入视频文件（.mp4） |
| `audio` | — | 输入音频文件（.mp3） |
| `--srt` | — | SRT 字幕文件，自动计算保留原音的头尾时间段（第一条字幕之前 + 最后一条字幕之后），读取视频时长无需手动输入 |
| `-k`, `--keep-original` | — | 手动指定保留原音的时间段，可多个，格式 `HH:MM:SS-HH:MM:SS`。可与 `--srt` 同时使用 |
| `-o`, `--output` | `output.mp4` | 输出文件路径 |
| `-v`, `--verbose` | 关 | 打印 FFmpeg 命令 |

### 示例

```bash
# 全程替换音轨
python mixer.py video.mp4 voice.mp3 -o result.mp4

# 用 SRT 自动保留片头/片尾原音（最常用）
python mixer.py video.mp4 voice.mp3 --srt subtitles.srt -o result.mp4

# 手动指定保留 5:00~7:30 的原始音轨
python mixer.py video.mp4 voice.mp3 -k 00:05:00-00:07:30 -o result.mp4

# --srt 与手动 -k 同时使用
python mixer.py video.mp4 voice.mp3 --srt subtitles.srt -k 00:10:00-00:12:00 -o result.mp4
```

---

## clip_video.py

从视频文件中截取指定时间段，默认直接复制流（极快），可选重新编码（帧精确）。

### 用法

```
python clip_video.py <input.mp4> <start> <end> [选项]
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `input` | — | 输入视频文件 |
| `start` | — | 开始时间，格式 `HH:MM:SS` 或 `MM:SS` |
| `end` | — | 结束时间，格式 `HH:MM:SS` 或 `MM:SS` |
| `-o`, `--output` | 自动 | 输出文件路径（默认：`原文件名_开始_结束.mp4`） |
| `--reencode` | 关 | 重新编码，帧精确裁切（较慢） |
| `-v`, `--verbose` | 关 | 打印 FFmpeg 命令 |

> **注意**：默认快速模式（`-c copy`）裁切点对齐到关键帧，误差约 0~2 秒。需要精确到帧时使用 `--reencode`。

### 示例

```bash
# 截取 5:00 ~ 7:30，快速模式
python clip_video.py video.mp4 00:05:00 00:07:30

# 指定输出文件名
python clip_video.py video.mp4 00:05:00 00:07:30 -o clip.mp4

# 帧精确裁切
python clip_video.py video.mp4 00:05:00 00:07:30 --reencode -o clip.mp4
```

---

## speed_mp3.py

对已有 MP3 文件做变速处理，保持音调不变（FFmpeg atempo）。可手动指定倍率，或提供 SRT 文件自动计算所需倍率。

### 用法

```
python speed_mp3.py <input.mp3> [speed] [--srt file.srt] [选项]
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `input` | — | 输入 MP3 文件 |
| `speed` | — | 加速倍率（可选），例如 `1.15`=加速15%，`0.9`=减速10% |
| `--srt` | — | SRT 文件路径，自动计算倍率：MP3时长 ÷ SRT语音时长（首条开始→末条结束）|
| `-o`, `--output` | 自动 | 输出文件路径（默认：`原文件名_Nx.mp3`） |
| `-v`, `--verbose` | 关 | 打印 FFmpeg 命令 |

### 示例

```bash
# 手动指定倍率
python speed_mp3.py voice.mp3 1.15

# 自动从 SRT 计算倍率
python speed_mp3.py voice.mp3 --srt 001_subtitles.srt

# 指定输出文件名
python speed_mp3.py voice.mp3 --srt 001_subtitles.srt -o voice_fitted.mp3
```

---

## clip_mp3.py

从 MP3 文件中截取指定时间段，直接复制流不重编码。

### 用法

```
python clip_mp3.py <input.mp3> <start> <end> [选项]
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `input` | — | 输入 MP3 文件 |
| `start` | — | 开始时间，格式 `HH:MM:SS` 或 `MM:SS` |
| `end` | — | 结束时间，格式 `HH:MM:SS` 或 `MM:SS` |
| `-o`, `--output` | 自动 | 输出文件路径（默认：`原文件名_开始_结束.mp3`） |
| `-v`, `--verbose` | 关 | 打印 FFmpeg 命令 |

### 示例

```bash
# 截取 5:00 ~ 7:30
python clip_mp3.py audio.mp3 00:05:00 00:07:30

# 指定输出文件名
python clip_mp3.py audio.mp3 00:05:00 00:07:30 -o clip.mp3
```

---

## merge_mp3.py

将多个 MP3 文件按顺序串联合并为一个，直接复制流不重编码，速度极快。

### 用法

```
python merge_mp3.py <file1.mp3> <file2.mp3> [file3.mp3 ...] [选项]
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `inputs` | — | 输入 MP3 文件列表（按顺序排列） |
| `-o`, `--output` | `merged.mp3` | 输出文件路径 |
| `-v`, `--verbose` | 关 | 打印 FFmpeg 命令 |

### 示例

```bash
# 合并两个文件
python merge_mp3.py part1.mp3 part2.mp3 -o merged.mp3

# 合并多个文件
python merge_mp3.py part1.mp3 part2.mp3 part3.mp3 -o full.mp3
```

---

## srt_to_txt.py

从双语 SRT 文件中提取英文字幕，去除中文行、时间轴、序号和空白行，输出纯文本 TXT。

### 用法

```
python srt_to_txt.py <input.srt> [选项]
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `input` | — | 输入 SRT 文件 |
| `--throat-interval` | `30` | 每隔 N 行在句前插入 `[clears throat]`，`0`=关闭 |
| `-o`, `--output` | 自动 | 输出 TXT 路径（默认：同名 `.txt`）|

### 示例

```bash
python srt_to_txt.py 003_chinese-english_subtitles.srt
# 输出 003_chinese-english_subtitles.txt

python srt_to_txt.py 003_chinese-english_subtitles.srt -o 003_english.txt

# 每 50 行插一个 [clears throat]
python srt_to_txt.py 003_chinese-english_subtitles.srt --throat-interval 50
```

---

## mp3_to_srt.py

用 OpenAI Whisper 本地转录 MP3，结合提供的 TXT 文字生成时间对齐的 SRT 字幕。

- **TXT 模式**（推荐）：Whisper 只用于提取时间轴，正文文字来自 TXT 文件，避免 Whisper 识别错误
- **纯 Whisper 模式**：不提供 TXT，直接用 Whisper 的识别文字分段输出 SRT

### 依赖

```bash
pip install openai-whisper
```

### 用法

```
python mp3_to_srt.py <input.mp3> [选项]
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `input` | — | 输入 MP3 文件 |
| `--txt` | — | TXT 文件（含完整正确文字）；不提供则直接使用 Whisper 识别文字 |
| `--model` | `base` | Whisper 模型大小：`tiny` / `base` / `small` / `medium` / `large` |
| `--language` | `en` | 音频语言（例如 `zh` 表示中文）|
| `--max-words` | `12` | 每条字幕最多单词数 |
| `--start-time` | `0` | SRT 时间轴起始偏移，格式 `HH:MM:SS`、`MM:SS` 或秒数。MP3 是视频某片段时使用，让 SRT 对齐视频时间轴 |
| `-o`, `--output` | 自动 | 输出 SRT 路径（默认：同名 `.srt`）|
| `-v`, `--verbose` | 关 | 打印 Whisper 识别详情 |

### 模型说明

| 模型 | 速度 | 精度 | 显存 |
|------|------|------|------|
| `tiny` | 最快 | 最低 | ~1 GB |
| `base` | 快 | 一般 | ~1 GB |
| `small` | 中 | 较好 | ~2 GB |
| `medium` | 慢 | 好 | ~5 GB |
| `large` | 最慢 | 最好 | ~10 GB |

### 示例

```bash
# TXT 对齐模式（推荐）：时间轴来自 Whisper，正文来自 script.txt
python mp3_to_srt.py voice.mp3 --txt script.txt

# 使用更高精度模型
python mp3_to_srt.py voice.mp3 --txt script.txt --model medium

# 纯 Whisper 模式，每条字幕最多 8 个单词
python mp3_to_srt.py voice.mp3 --max-words 8

# 指定语言为中文，指定输出文件名
python mp3_to_srt.py voice.mp3 --language zh -o output.srt

# MP3 是视频 5:30 开始的片段，SRT 时间轴从 5:30 计算
python mp3_to_srt.py voice.mp3 --txt script.txt --start-time 00:05:30
```

---

## pipeline.py（一键流水线）

输入原始视频 MP4 和 SRT 字幕，自动依次执行全部四个步骤，所有中间文件保存在同一目录下，方便排查问题或从任意步骤重新运行。

### 流水线步骤

```
步骤 1  srt_to_txt.py     SRT → TXT（提取英文，插入 [clears throat]）
步骤 2  srt_voice_gen.py  TXT → voice_raw.mp3（ElevenLabs TTS）
步骤 3  speed_mp3.py      voice_raw.mp3 → voice_fitted.mp3（按 SRT 时长变速对齐）
步骤 4  mixer.py          video.mp4 + voice_fitted.mp3 → result.mp4（保留片头片尾原音）
```

### 用法

```
python pipeline.py <input.mp4> <input.srt> [选项]
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `video` | — | 输入视频文件 (.mp4) |
| `srt` | — | 输入 SRT 字幕文件 |
| `--work-dir` | `<视频名>_pipeline` | 中间文件保存目录 |
| `--throat-interval` | `30` | 每隔 N 行插入 `[clears throat]`（步骤 1）|
| `--el-model` | `eleven_v3` | ElevenLabs 模型（步骤 2）|
| `--stability` | `0.7` | 声音稳定性（步骤 2）|
| `--similarity-boost` | `0.5` | 与原声相似度（步骤 2）|
| `--speed` | `1.05` | TTS 语速（步骤 2）|
| `--sentence-break` | `0.5` | 句尾停顿秒数（步骤 2）|
| `--max-chars` | `4500` | TTS 每块最大字符数（步骤 2）|
| `--from-step` | `1` | 从第 N 步开始，跳过前面步骤（用于断点续跑）|
| `-v`, `--verbose` | 关 | 打印每步的完整命令 |

### 输出文件结构

```
<视频名>_pipeline/
├── transcript.txt          ← 步骤 1：提取的英文文稿
├── voice_raw.mp3           ← 步骤 2：TTS 生成的原始语音
├── voice_raw_segments/     ← 步骤 2：分块 MP3（可用 assemble_segments.py 重新合并）
├── voice_raw_requests.json ← 步骤 2：API 请求日志
├── voice_fitted.mp3        ← 步骤 3：变速对齐后的语音
└── result.mp4              ← 步骤 4：最终输出视频
```

### 示例

```bash
# 最简用法（使用所有默认参数）
python pipeline.py 001.mp4 001_subtitles.srt

# 自定义模型和声音参数
python pipeline.py 001.mp4 001_subtitles.srt --stability 0.65 --similarity-boost 0.4

# 步骤 2 失败后，从步骤 2 重新开始（步骤 1 已完成，不重跑）
python pipeline.py 001.mp4 001_subtitles.srt --from-step 2

# 只重新跑步骤 4（mixer），例如调整了 SRT 边界
python pipeline.py 001.mp4 001_subtitles.srt --from-step 4
```

---

## add_subtitles.py（一键烧录英文字幕）

在视频上遮盖原有中文字幕（白色遮罩），并将英文字幕烧录到遮罩区域内。三步自动完成：

```
步骤 1  mp3_to_srt.py   MP3 + TXT → 英文 SRT（Whisper 对齐时间轴）
步骤 2  srt_to_ass.py   SRT → ASS（精确定位字幕框）
步骤 3  FFmpeg          视频 + 白色遮罩 + ASS 字幕 → 最终 MP4
```

起始时间和 drawbox 时间范围自动从原始 SRT 第一条/最后一条时间戳提取，无需手动计算。

所有中间文件（`.srt`、`.ass`）保存在 MP3 所在目录，方便单步重跑。

### 用法

```
python add_subtitles.py <input.mp3> <transcript.txt> <original.srt> <video.mp4> [选项]
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `mp3` | — | 英文音频 MP3（TTS 生成的，与 transcript.txt 对应）|
| `txt` | — | 英文文稿 TXT |
| `srt` | — | 原始双语 SRT（用于提取配音起止时间）|
| `video` | — | 视频 MP4 |
| `--res` | `1280x960` | 视频分辨率 WxH |
| `--box` | `0,700,1280,200` | 字幕框 x,y,w,h |
| `--box-color` | `white@0.95` | 遮罩颜色 |
| `--font-size` | `44` | 字幕字体大小 |
| `--color` | `333333` | 字幕颜色 RRGGBB |
| `--whisper-model` | `small` | Whisper 模型 |
| `--from-step` | `1` | 从第 N 步开始（断点续跑）|
| `-o`, `--output` | 自动 | 输出 MP4（默认：与输入同目录，`<视频名>_subtitled.mp4`）|
| `-v`, `--verbose` | 关 | 打印 FFmpeg 命令 |

### 示例

```bash
# pipeline.py 输出目录下直接运行
python add_subtitles.py 002_pipeline/voice_fitted.mp3 002_pipeline/transcript.txt 002_chinese-english_subtitles_HRF.srt 002.mp4

# 自定义字幕框和字体
python add_subtitles.py voice.mp3 transcript.txt original.srt video.mp4 --box 0,650,1280,250 --font-size 40

# 步骤 1 已完成，从步骤 2 重新开始
python add_subtitles.py voice.mp3 transcript.txt original.srt video.mp4 --from-step 2
```

---

## 典型工作流

```
一键模式（推荐）:
  python pipeline.py input.mp4 input.srt

手动分步:
  1. srt_to_txt.py      SRT → TXT
  2. srt_voice_gen.py   TXT → MP3
  3. speed_mp3.py       MP3 变速对齐
  4. mixer.py           合入视频
  （可选）clip_video.py / clip_mp3.py / merge_mp3.py 做后期剪辑
```
