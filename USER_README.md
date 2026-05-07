# VideoAudioMixer — User Guide

Generate an English-dubbed video from a Chinese lecture video in one command.

---

## What You Need

Place these files in the **same folder**:

```
VideoAudioMixer.exe   ← the program
ffmpeg.exe            ← required (download from ffmpeg.org)
ffprobe.exe           ← required (comes with ffmpeg)
ElevenLabs.md         ← your API key (see setup below)
```

---

## Setup: ElevenLabs API Key

Create a file named `ElevenLabs.md` in the same folder as the exe:

```
API Key: sk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Voice ID: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Get your API key and Voice ID from [elevenlabs.io](https://elevenlabs.io).

---

## Basic Usage

Open a Command Prompt in the folder containing the exe, then run:

```
VideoAudioMixer.exe  video.mp4  subtitles.srt
```

**Inputs:**
- `video.mp4` — the original Chinese lecture video
- `subtitles.srt` — the bilingual (Chinese/English) subtitle file

**Output:** a `video_pipeline/` folder containing all intermediate files and the final `result.mp4`.

---

## What It Does (4 steps)

```
Step 1  Extract English text from SRT              → transcript.txt
Step 2  Generate English speech via ElevenLabs TTS → voice_raw.mp3
Step 3  Speed-adjust audio to match subtitle timing → voice_fitted.mp3
Step 4  Replace video audio, keep original at start/end → result.mp4
```

All intermediate files are saved so you can re-run from any step if something goes wrong.

---

## Options

```
VideoAudioMixer.exe video.mp4 subtitles.srt [options]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--work-dir PATH` | `<video>_pipeline` | Folder for all output files |
| `--el-model MODEL` | `eleven_v3` | ElevenLabs model. Options: `eleven_v3`, `eleven_multilingual_v2`, `eleven_turbo_v2_5` |
| `--stability N` | `0.7` | Voice stability 0–1 (lower = more expressive) |
| `--similarity-boost N` | `0.5` | Voice similarity 0–1 |
| `--sentence-break N` | `0.5` | Pause length after sentences (seconds) |
| `--throat-interval N` | `30` | Insert `[clears throat]` every N lines (0 = off) |
| `--timeout N` | `120` | API request timeout in seconds |
| `--from-step N` | `1` | Resume from step N (1–4). Use if a step fails |
| `-v` | off | Verbose: print FFmpeg commands |

---

## Examples

```
# Basic — use all defaults
VideoAudioMixer.exe lecture.mp4 lecture.srt

# More expressive voice
VideoAudioMixer.exe lecture.mp4 lecture.srt --stability 0.5 --similarity-boost 0.4

# Longer sentence pauses
VideoAudioMixer.exe lecture.mp4 lecture.srt --sentence-break 1.0

# Step 2 timed out — resume from step 2 (skips step 1, retries failed API chunks)
VideoAudioMixer.exe lecture.mp4 lecture.srt --from-step 2

# Save output to a specific folder
VideoAudioMixer.exe lecture.mp4 lecture.srt --work-dir D:\Output\lecture_001
```

---

## Troubleshooting

**"ffmpeg not found"**
→ Make sure `ffmpeg.exe` and `ffprobe.exe` are in the same folder as `VideoAudioMixer.exe`.

**"API Key not found"**
→ Check that `ElevenLabs.md` is in the same folder and formatted correctly (see Setup above).

**Step 2 has failed chunks (timeout)**
→ Run again with `--from-step 2`. Already-generated audio chunks are cached and skipped; only failed ones are retried. Add `--timeout 180` if timeouts persist.

**Voice is too fast / too slow**
→ Step 3 automatically adjusts speed to match the subtitle timing. If the result sounds unnatural, try `--stability 0.65` for a slightly different delivery.

---

## Output Files

```
<video>_pipeline/
├── transcript.txt          Step 1: extracted English text
├── voice_raw.mp3           Step 2: raw TTS audio
├── voice_raw_segments/     Step 2: individual audio chunks (cached)
├── voice_raw_requests.json Step 2: API request log
├── voice_fitted.mp3        Step 3: speed-adjusted audio
└── result.mp4              Step 4: final dubbed video  ← this is your output
```

---

## ElevenLabs Voice Models

| Model | Quality | Speed | Notes |
|-------|---------|-------|-------|
| `eleven_v3` | Best | Slowest | Default. Supports emotion tags |
| `eleven_multilingual_v2` | Very good | Medium | Supports precise pause timing |
| `eleven_turbo_v2_5` | Good | Fast | Lower cost |

---

*Requires Windows 10/11 × 64-bit. FFmpeg and an ElevenLabs API key are required.*
