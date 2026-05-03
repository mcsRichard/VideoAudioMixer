import argparse
import os
import re
import subprocess
import sys
import tempfile
import time


def get_ffmpeg_paths():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
        ffmpeg  = os.path.join(base, 'ffmpeg.exe')
        ffprobe = os.path.join(base, 'ffprobe.exe')
        if os.path.exists(ffmpeg):
            return ffmpeg, ffprobe
    return 'ffmpeg', 'ffprobe'


def get_duration(ffprobe, path):
    cmd = [ffprobe, '-v', 'quiet', '-print_format', 'json', '-show_format', path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {result.stderr.strip()}")
    import json
    return float(__import__('json').loads(result.stdout)['format']['duration'])


def format_duration(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


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
        prog='merge_mp3',
        description='将多个 MP3 文件串联合并为一个'
    )
    parser.add_argument('inputs', nargs='+', metavar='file.mp3',
                        help='输入 MP3 文件（按顺序排列）')
    parser.add_argument('-o', '--output', default='merged.mp3',
                        help='输出文件路径（默认: merged.mp3）')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='打印 FFmpeg 命令')
    args = parser.parse_args()

    ffmpeg, ffprobe = get_ffmpeg_paths()

    # Step 1 — validate
    print(f'[1/3] 验证输入文件...', end='', flush=True)
    for path in args.inputs:
        if not os.path.exists(path):
            print(f'\n错误: 文件不存在: {path}')
            sys.exit(1)
    print(f' ✓  共 {len(args.inputs)} 个文件')

    # Step 2 — read durations
    print('[2/3] 读取文件信息...', end='', flush=True)
    durations = []
    try:
        for path in args.inputs:
            durations.append(get_duration(ffprobe, path))
    except Exception as e:
        print(f'\n错误: {e}')
        sys.exit(1)
    total_dur = sum(durations)
    print(f' ✓  总时长: {format_duration(total_dur)}')
    for i, (path, dur) in enumerate(zip(args.inputs, durations), 1):
        print(f'        {i}. {os.path.basename(path)}  ({format_duration(dur)})')

    # Step 3 — concat
    print('[3/3] 合并处理中...')

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt',
                                     delete=False, encoding='utf-8') as f:
        list_path = f.name
        for path in args.inputs:
            abs_path = os.path.abspath(path).replace('\\', '/')
            f.write(f"file '{abs_path}'\n")

    try:
        cmd = [ffmpeg, '-y', '-f', 'concat', '-safe', '0',
               '-i', list_path, '-c', 'copy', args.output]

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
                h, mi, s = m.group(1).split(':')
                current = int(h) * 3600 + int(mi) * 60 + float(s)
                print_progress(current, total_dur, time.time() - t0)

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

    finally:
        os.unlink(list_path)


if __name__ == '__main__':
    main()
