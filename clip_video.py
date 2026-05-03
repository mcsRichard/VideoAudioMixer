import argparse
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


def parse_time(s):
    parts = s.strip().split(':')
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except ValueError:
        pass
    raise ValueError(f"无效时间格式: '{s}'，应为 HH:MM:SS、MM:SS 或秒数")


def clip_video(input_path, start, end, output_path, reencode=False, verbose=False):
    """
    Trim input_path from start to end seconds, write to output_path.
    Fast by default (-c copy); set reencode=True for frame-accurate cuts.
    """
    duration = end - start
    ffmpeg = get_ffmpeg()

    if reencode:
        cmd = [
            ffmpeg, '-y',
            '-ss', str(start),
            '-i', input_path,
            '-t', str(duration),
            '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
            '-c:a', 'aac', '-b:a', '192k',
            output_path,
        ]
    else:
        cmd = [
            ffmpeg, '-y',
            '-ss', str(start),
            '-i', input_path,
            '-t', str(duration),
            '-c', 'copy',
            output_path,
        ]

    if verbose:
        print('FFmpeg 命令:')
        print(' '.join(f'"{c}"' if ' ' in c else c for c in cmd))
        print()

    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-500:])


def main():
    parser = argparse.ArgumentParser(
        prog='clip_video',
        description='从视频文件中截取指定时间段'
    )
    parser.add_argument('input',  help='输入视频文件 (.mp4)')
    parser.add_argument('start',  help='开始时间，格式 HH:MM:SS 或 MM:SS')
    parser.add_argument('end',    help='结束时间，格式 HH:MM:SS 或 MM:SS')
    parser.add_argument('-o', '--output', default=None,
                        help='输出文件路径（默认: 原文件名_clip.mp4）')
    parser.add_argument('--reencode', action='store_true',
                        help='重新编码（帧精确裁切，较慢；默认: 直接复制流，极快）')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='打印 FFmpeg 命令')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f'错误: 文件不存在: {args.input}')
        sys.exit(1)

    try:
        start = parse_time(args.start)
        end   = parse_time(args.end)
    except ValueError as e:
        print(f'错误: {e}')
        sys.exit(1)

    if start >= end:
        print('错误: 开始时间必须早于结束时间')
        sys.exit(1)

    if args.output:
        output = args.output
    else:
        base, ext = os.path.splitext(args.input)
        s = args.start.replace(':', '-')
        e = args.end.replace(':', '-')
        output = f'{base}_{s}_{e}{ext}'

    mode = '重新编码' if args.reencode else '直接复制流（快速）'
    print(f'截取: {args.start} → {args.end}  [{mode}]', end='', flush=True)

    try:
        clip_video(args.input, start, end, output, args.reencode, args.verbose)
    except RuntimeError as e:
        print(f'\n错误: FFmpeg 失败:\n{e}')
        if os.path.exists(output):
            os.remove(output)
        sys.exit(1)

    size_mb = os.path.getsize(output) / 1024 / 1024
    print(f' ✓')
    print(f'  输出文件: {output}  ({size_mb:.1f} MB)')


if __name__ == '__main__':
    main()
