import argparse
import json
import os
import re
import subprocess
import sys
import time


def parse_time(s):
    parts = s.strip().split(':')
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    except ValueError:
        pass
    raise ValueError(f"无效时间格式: '{s}'，应为 HH:MM:SS 或 MM:SS")


def format_duration(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def parse_srt_time(s):
    m = re.match(r'(\d+):(\d+):(\d+)[,.](\d+)', s.strip())
    if not m:
        raise ValueError(f"无效 SRT 时间戳: '{s}'")
    h, mm, ss, frac = m.groups()
    return int(h) * 3600 + int(mm) * 60 + int(ss) + int(frac) / (10 ** len(frac))


def srt_boundaries(srt_path):
    """Return (first_start, last_end) seconds from SRT file."""
    for enc in ('utf-8-sig', 'gbk', 'utf-16', 'latin-1'):
        try:
            with open(srt_path, encoding=enc) as f:
                content = f.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    timestamps = re.findall(
        r'(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)',
        content
    )
    if not timestamps:
        raise ValueError(f'SRT 文件中未找到时间戳')
    return parse_srt_time(timestamps[0][0]), parse_srt_time(timestamps[-1][1])


def parse_keep_range(s):
    match = re.match(r'^([\d:]+)-([\d:]+)$', s.strip())
    if not match:
        raise ValueError(f"无效时间段格式: '{s}'，应为 HH:MM:SS-HH:MM:SS")
    start = parse_time(match.group(1))
    end = parse_time(match.group(2))
    if start >= end:
        raise ValueError(f"时间段起始必须早于结束: '{s}'")
    return start, end


def get_ffmpeg_paths():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
        ffmpeg = os.path.join(base, 'ffmpeg.exe')
        ffprobe = os.path.join(base, 'ffprobe.exe')
        if os.path.exists(ffmpeg):
            return ffmpeg, ffprobe
    return 'ffmpeg', 'ffprobe'


def get_video_info(ffprobe, video_path):
    cmd = [ffprobe, '-v', 'quiet', '-print_format', 'json',
           '-show_format', '-show_streams', video_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    duration = float(data['format']['duration'])
    width = height = None
    for stream in data['streams']:
        if stream['codec_type'] == 'video':
            width = stream.get('width')
            height = stream.get('height')
            break
    return duration, width, height


def build_segments(duration, keep_ranges):
    keep_ranges = sorted(keep_ranges)
    segments = []
    cursor = 0.0
    for start, end in keep_ranges:
        if cursor < start:
            segments.append((cursor, start, False))
        segments.append((start, end, True))
        cursor = end
    if cursor < duration:
        segments.append((cursor, duration, False))
    return segments


def build_filter_complex(segments, mp3_duration=None):
    parts = []
    labels = []
    mp3_cursor = 0.0  # tracks position within MP3 independently of video timeline
    for i, (start, end, use_original) in enumerate(segments):
        src = '[0:a]' if use_original else '[1:a]'
        label = f'seg{i}'
        if use_original:
            trim_start = start
            trim_end = end
        else:
            trim_start = mp3_cursor
            trim_end = mp3_cursor + (end - start)
            if mp3_duration is not None:
                trim_end = min(trim_end, mp3_duration)
            mp3_cursor = trim_end
        parts.append(
            f'{src}atrim=start={trim_start:.3f}:end={trim_end:.3f},'
            f'asetpts=PTS-STARTPTS,'
            f'aresample=44100[{label}]'
        )
        labels.append(f'[{label}]')
    concat = ''.join(labels) + f'concat=n={len(segments)}:v=0:a=1[aout]'
    parts.append(concat)
    return ';'.join(parts)


def print_progress(current, total, elapsed, bar_width=38):
    if total <= 0:
        return
    pct = min(current / total, 1.0)
    filled = int(bar_width * pct)
    bar = '█' * filled + '░' * (bar_width - filled)
    cur_str = format_duration(current)
    tot_str = format_duration(total)
    if pct > 0.001 and elapsed > 0:
        eta = int(elapsed / pct - elapsed)
        eta_str = f"剩余约 {eta}s"
    else:
        eta_str = "计算中..."
    line = f"\r      {cur_str} / {tot_str}  [{bar}]  {pct*100:5.1f}%  {eta_str}   "
    sys.stdout.write(line)
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(
        prog='mixer',
        description='将视频音轨替换为MP3，可指定时间段保留原始音轨'
    )
    parser.add_argument('video', help='输入视频文件 (.mp4)')
    parser.add_argument('audio', help='输入音频文件 (.mp3)')
    parser.add_argument('--srt', default=None,
                        help='SRT 字幕文件，自动计算保留原音的头尾时间段'
                             '（第一条字幕之前 + 最后一条字幕之后）')
    parser.add_argument('-k', '--keep-original', nargs='+', metavar='T1-T2',
                        default=[],
                        help='保留原音的时间段，可多个，格式: HH:MM:SS-HH:MM:SS')
    parser.add_argument('-o', '--output', default='output.mp4',
                        help='输出文件路径 (默认: output.mp4)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='打印 FFmpeg 命令')
    args = parser.parse_args()

    ffmpeg, ffprobe = get_ffmpeg_paths()

    # Step 1 — validate files
    print('[1/4] 验证输入文件...', end='', flush=True)
    for path in [args.video, args.audio]:
        if not os.path.exists(path):
            print(f'\n错误: 文件不存在: {path}')
            sys.exit(1)
    print(' ✓')

    # Step 2 — read video info
    print('[2/4] 读取视频信息...', end='', flush=True)
    try:
        duration, width, height = get_video_info(ffprobe, args.video)
        mp3_duration, _, _ = get_video_info(ffprobe, args.audio)
    except Exception as e:
        print(f'\n错误: {e}')
        sys.exit(1)
    print(f' ✓  时长: {format_duration(duration)}，分辨率: {width}x{height}')
    if mp3_duration < duration - 0.5:
        print(f'      ⚠  MP3 时长 {format_duration(mp3_duration)} 短于视频 {format_duration(duration)}，'
              f'超出部分将静音')

    # Step 3 — parse time ranges and build segments
    print('[3/4] 构建音频处理指令...', end='', flush=True)

    # --srt: derive keep ranges from SRT boundaries
    srt_extra = []
    if args.srt:
        if not os.path.exists(args.srt):
            print(f'\n错误: SRT 文件不存在: {args.srt}')
            sys.exit(1)
        try:
            srt_first, srt_last = srt_boundaries(args.srt)
        except Exception as e:
            print(f'\n错误: 读取 SRT 失败: {e}')
            sys.exit(1)
        print(f'\n  SRT 配音范围: {format_duration(srt_first)} → {format_duration(srt_last)}')
        if srt_first > 0.05:
            srt_extra.append((0.0, srt_first))
            print(f'  自动保留片头原音: 00:00:00 ~ {format_duration(srt_first)}')
        if srt_last < duration - 0.05:
            srt_extra.append((srt_last, duration))
            print(f'  自动保留片尾原音: {format_duration(srt_last)} ~ {format_duration(duration)}')
        if not srt_extra:
            print('  SRT 覆盖全程，无需保留原音片段')

    keep_ranges = list(srt_extra)
    for s in args.keep_original:
        try:
            start, end = parse_keep_range(s)
        except ValueError as e:
            print(f'\n错误: {e}')
            sys.exit(1)
        if end > duration + 0.5:
            print(f'\n错误: 时间段 {s} 超出视频时长 {format_duration(duration)}')
            sys.exit(1)
        keep_ranges.append((start, end))

    sorted_ranges = sorted(keep_ranges)
    for i in range(len(sorted_ranges) - 1):
        if sorted_ranges[i][1] > sorted_ranges[i + 1][0]:
            print('\n错误: 保留时间段存在重叠')
            sys.exit(1)

    if keep_ranges:
        segments = build_segments(duration, sorted_ranges)
        orig_count = sum(1 for s in segments if s[2])
        mp3_count = len(segments) - orig_count
        filter_complex = build_filter_complex(segments, mp3_duration)
        audio_map = '[aout]'
        print(f' ✓  共 {len(segments)} 段（{orig_count} 段保留原音，{mp3_count} 段使用MP3）')
    else:
        filter_complex = None
        audio_map = None
        print(' ✓  全程替换为 MP3')

    # Step 4 — run ffmpeg
    print('[4/4] 合并处理中...')

    cmd = [ffmpeg, '-y', '-i', args.video, '-i', args.audio]
    if filter_complex:
        cmd += ['-filter_complex', filter_complex, '-map', '0:v', '-map', audio_map]
    else:
        cmd += ['-map', '0:v', '-map', '1:a']
    cmd += ['-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', args.output]

    if args.verbose:
        print('FFmpeg 命令:')
        print(' '.join(f'"{c}"' if ' ' in c else c for c in cmd))
        print()

    t0 = time.time()
    try:
        proc = subprocess.Popen(
            cmd, stderr=subprocess.PIPE,
            universal_newlines=True, encoding='utf-8', errors='replace'
        )
    except FileNotFoundError:
        print('\n错误: 找不到 ffmpeg，请确认已安装并添加到 PATH')
        sys.exit(1)

    time_re = re.compile(r'time=(\d+:\d+:\d+\.\d+)')
    for line in proc.stderr:
        m = time_re.search(line)
        if m:
            current = parse_time(m.group(1))
            print_progress(current, duration, time.time() - t0)

    proc.wait()
    print()

    if proc.returncode != 0:
        print('错误: FFmpeg 处理失败，请加 -v 参数查看详细信息')
        if os.path.exists(args.output):
            os.remove(args.output)
        sys.exit(1)

    elapsed = time.time() - t0
    size_mb = os.path.getsize(args.output) / 1024 / 1024
    print(f'\n完成！')
    print(f'  输出文件: {args.output}  ({size_mb:.1f} MB)')
    print(f'  处理耗时: {elapsed:.1f}s')


if __name__ == '__main__':
    main()
