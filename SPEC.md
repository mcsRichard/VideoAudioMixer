# VideoAudioMixer — 需求与实现方案

## 一、程序概述

命令行工具，将视频文件的音轨替换为指定 MP3 音频，但在用户指定的时间段内保留视频原始音轨。

---

## 二、输入规格

| 参数 | 规格 |
|------|------|
| 视频文件 | MP4，1280×960，码率 1200kbps，时长 30分钟 ~ 2小时 |
| 音频文件 | MP3，时长与视频相同 |
| 保留原音时间段 | 一个或多个，格式 `HH:MM:SS-HH:MM:SS` |
| 输出文件 | MP4，视频流不变，音轨为混合结果 |

---

## 三、命令行接口

```
mixer.exe <video.mp4> <audio.mp3> [选项]

位置参数:
  video               输入视频文件路径
  audio               输入音频文件路径（MP3）

选项:
  -k, --keep-original <T1-T2> [<T3-T4> ...]
                      保留原视频音轨的时间段，可指定多个
                      格式: HH:MM:SS-HH:MM:SS 或 MM:SS-MM:SS
  -o, --output        输出文件路径（默认: output.mp4）
  -v, --verbose       打印详细的 FFmpeg 命令
  -h, --help          显示帮助信息

示例:
  mixer.exe video.mp4 audio.mp3 -k 00:05:00-00:07:30 -o result.mp4
  mixer.exe video.mp4 audio.mp3 -k 00:10:00-00:12:00 00:45:00-00:47:00 -o result.mp4
```

---

## 四、核心逻辑

### 音轨拼接策略

```
原始音轨:  |----A----|----A----|----A----|----A----|
输入 MP3:  |====B====|====B====|====B====|====B====|
保留段:              [  keep1 ]          [ keep2  ]

输出音轨:  |====B====|----A----|====B====|----A----|
```

在保留段以外的所有区间，使用 MP3 对应位置的片段；在保留段内，使用原视频音轨。

### 时间轴切割示例

假设视频 60 分钟，保留段 `05:00-07:00` 和 `30:00-32:00`：

```
切割为 5 段:
  [00:00 ~ 05:00]  → 使用 MP3
  [05:00 ~ 07:00]  → 使用原音
  [07:00 ~ 30:00]  → 使用 MP3
  [30:00 ~ 32:00]  → 使用原音
  [32:00 ~ 60:00]  → 使用 MP3
```

---

## 五、技术方案

### 依赖

| 组件 | 说明 |
|------|------|
| Python 3.8+ | 程序语言 |
| FFmpeg | 音视频处理核心，调用方式：`subprocess` |
| PyInstaller | 打包为 exe（可选） |

Python 侧无需 `pip install` 第三方包（仅用标准库）。

### FFmpeg 调用策略

- **视频流**：`-c:v copy`，直接复制不重编码，速度快
- **音频流**：通过 `filter_complex` 切割拼接，最终输出单一音轨
- **采样率统一**：所有音频段统一 resample 至 44100Hz，避免因采样率不一致导致拼接错位

### filter_complex 构建逻辑（伪代码）

```
segments = build_segments(video_duration, keep_original_ranges)

for each segment:
    if segment.use_mp3:
        从 [1:a]（MP3输入流）atrim start~end，asetpts 归零
    else:
        从 [0:a]（视频原音）atrim start~end，asetpts 归零

所有段 → concat=n=N:v=0:a=1 → 输出音轨
```

---

## 六、进度反馈设计

程序运行期间向用户实时显示进度，分以下阶段：

```
[1/4] 验证输入文件...          ✓
[2/4] 读取视频信息...          ✓ 时长: 01:00:00，分辨率: 1280x960
[3/4] 构建音频处理指令...      ✓ 共 5 段（2 段保留原音）
[4/4] 合并处理中...
      00:00:10 / 01:00:00  [████░░░░░░░░░░░░░░░░]  17%  预计剩余: 45s
```

- 阶段 1~3：即时显示，带 ✓ 确认
- 阶段 4：解析 FFmpeg stderr 的 `time=` 字段，实时刷新进度条（同行覆盖）

---

## 七、实现步骤

### Step 1 — 参数解析与验证
- `argparse` 解析命令行参数
- 检查视频/音频文件存在
- 解析并验证时间段格式，检查不重叠、不超出视频时长

### Step 2 — 读取视频信息
- 调用 `ffprobe` 获取视频时长、分辨率、码率
- 确认音频文件可读

### Step 3 — 构建时间段列表
- 将保留段与 MP3 段交替排列，覆盖完整时间轴
- 生成 FFmpeg filter_complex 字符串

### Step 4 — 执行 FFmpeg
- `subprocess.Popen` 启动 FFmpeg，捕获 stderr
- 逐行解析 `time=HH:MM:SS.xx`，更新进度条
- 完成后打印输出文件路径和耗时

### Step 5 — 错误处理
- FFmpeg 非零退出码：打印错误信息，删除不完整的输出文件
- 时间段超出视频时长：提前报错退出
- 输入文件不存在/格式错误：清晰提示

---

## 八、打包与分发

```bash
# 安装打包工具
pip install pyinstaller

# 打包（将 ffmpeg.exe 一并打入）
pyinstaller --onefile --add-binary "ffmpeg.exe;." mixer.py

# 输出
dist/mixer.exe   ← 约 100MB，目标机器无需任何环境
```

目标机器要求：Windows 7+（64位），无需安装 Python 或 FFmpeg。

---

## 九、预计运行时间

| 视频时长 | 硬盘类型 | 预计耗时 |
|----------|---------|---------|
| 60 分钟 | SSD | 30秒 ~ 1分钟 |
| 60 分钟 | HDD | 2 ~ 4分钟 |
| 120 分钟 | SSD | 1 ~ 2分钟 |

视频流直接复制（不重编码），瓶颈为磁盘 I/O。

---

## 十、文件结构

```
VideoAudioMixer/
├── mixer.py          # 主程序
├── SPEC.md           # 本文档
├── ffmpeg.exe        # FFmpeg 可执行文件（打包时使用）
└── dist/
    └── mixer.exe     # 打包输出
```
