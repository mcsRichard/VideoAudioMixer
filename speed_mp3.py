import argparse
import json
import os
import re
import subprocess
import sys


def get_ffmpeg():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
        ffmpeg = os.path.join(base, 'ffmpeg.exe')
        if os.path.exists(ffmpeg):
            return ffmpeg
    return 'ffmpeg'


def build_atempo_chain(ratio):
    filters = []
    while ratio > 2.0:
        filters.append('atempo=2.0')
        ratio /= 2.0
    while ratio < 0.5:
        filters.append('atempo=0.5')
        ratio /= 0.5
    filters.append(f'atempo={ratio:.6f}')
    return ','.join(filters)


def parse_srt_time(s):
    m = re.match(r'(\d+):(\d+):(\d+)[,.](\d+)', s.strip())
    if not m:
        raise ValueError(f"无效时间戳: '{s}'")
    h, mm, ss, ms = m.groups()
    return int(h) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000


def srt_speech_duration(srt_path):
    """Return (first_start, last_end, speech_duration) from SRT file."""
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
        raise ValueError('SRT 文件中未找到时间戳')

    first_start = parse_srt_time(timestamps[0][0])
    last_end    = parse_srt_time(timestamps[-1][1])
    return first_start, last_end, last_end - first_start


def get_mp3_duration(mp3_path):
    ffmpeg = get_ffmpeg()
    ffprobe = ffmpeg.replace('ffmpeg', 'ffprobe')
    cmd = [ffprobe, '-v', 'quiet', '-print_format', 'json',
           '-show_format', mp3_path]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    if r.returncode != 0:
        raise RuntimeError(f'ffprobe 失败: {r.stderr.strip()}')
    return float(json.loads(r.stdout)['format']['duration'])


def fmt(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f'{h:02d}:{m:02d}:{s:06.3f}'


def main():
    parser = argparse.ArgumentParser(
        prog='speed_mp3',
        description='对 MP3 做变速处理。可手动指定倍率，或输入 SRT 自动计算'
    )
    parser.add_argument('input',           help='输入 MP3 文件')
    parser.add_argument('speed',           nargs='?', type=float, default=None,
                        help='加速倍率（可选）。不填时须提供 --srt 自动计算')
    parser.add_argument('--srt',           default=None,
                        help='SRT 文件路径，自动计算所需倍率')
    parser.add_argument('-o', '--output',  default=None,
                        help='输出文件路径（默认：原文件名_Nx.mp3）')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='打印 FFmpeg 命令')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f'错误: 文件不存在: {args.input}')
        sys.exit(1)

    if args.speed is None and args.srt is None:
        print('错误: 请提供倍率参数，或用 --srt 指定 SRT 文件自动计算')
        sys.exit(1)

    if args.srt:
        if not os.path.exists(args.srt):
            print(f'错误: SRT 文件不存在: {args.srt}')
            sys.exit(1)
        try:
            first_start, last_end, speech_dur = srt_speech_duration(args.srt)
            mp3_dur = get_mp3_duration(args.input)
        except Exception as e:
            print(f'错误: {e}')
            sys.exit(1)

        speed = mp3_dur / speech_dur
        print(f'  SRT 语音范围: {fmt(first_start)} → {fmt(last_end)}')
        print(f'  SRT 语音时长: {speech_dur:.1f}s  ({fmt(speech_dur)})')
        print(f'  MP3 时长:     {mp3_dur:.1f}s  ({fmt(mp3_dur)})')
        print(f'  计算倍率:     {mp3_dur:.1f} / {speech_dur:.1f} = {speed:.4f}x')
    else:
        speed = args.speed

    if speed <= 0:
        print('错误: 倍率必须大于 0')
        sys.exit(1)

    if args.output:
        output = args.output
    else:
        base, ext = os.path.splitext(args.input)
        output = f'{base}_{speed:.4f}x{ext}'

    af = build_atempo_chain(speed)
    ffmpeg = get_ffmpeg()
    cmd = [ffmpeg, '-y', '-i', args.input,
           '-af', af,
           '-c:a', 'libmp3lame', '-b:a', '192k', output]

    if args.verbose:
        print('FFmpeg 命令:')
        print(' '.join(f'"{c}"' if ' ' in c else c for c in cmd))
        print()

    print(f'变速处理: {speed:.4f}x ...', end='', flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if result.returncode != 0:
        print(f'\n错误: FFmpeg 失败:\n{result.stderr[-500:]}')
        if os.path.exists(output):
            os.remove(output)
        sys.exit(1)

    size_mb = os.path.getsize(output) / 1024 / 1024
    print(f' ✓')
    print(f'  输出文件: {output}  ({size_mb:.1f} MB)')


if __name__ == '__main__':
    main()
