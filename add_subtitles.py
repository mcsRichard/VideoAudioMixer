import argparse
import os
import re
import subprocess
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def parse_srt_time(s):
    m = re.match(r'(\d+):(\d+):(\d+)[,.](\d+)', s.strip())
    if not m:
        raise ValueError(f"Invalid SRT timestamp: '{s}'")
    h, mm, ss, frac = m.groups()
    return int(h) * 3600 + int(mm) * 60 + int(ss) + int(frac) / (10 ** len(frac))


def srt_boundaries(srt_path):
    """Return (first_start_sec, last_end_sec) from SRT file."""
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
    return parse_srt_time(timestamps[0][0]), parse_srt_time(timestamps[-1][1])


def fmt_hhmmss(sec):
    return f'{int(sec//3600):02d}:{int((sec%3600)//60):02d}:{int(sec%60):02d}'


def run_step(num, total, label, cmd, verbose=False, cwd=None):
    print(f'\n{"─" * 60}')
    print(f'[{num}/{total}] {label}')
    print(f'{"─" * 60}')
    if verbose:
        print('  ' + ' '.join(f'"{c}"' if ' ' in c else c for c in cmd))
        print()
    r = subprocess.run(cmd, text=True, encoding='utf-8', errors='replace', cwd=cwd)
    if r.returncode != 0:
        print(f'\n错误: 步骤 {num} 退出码 {r.returncode}，流程中止')
        return False
    return True


def check_exists(path, step_name):
    if not os.path.exists(path):
        print(f'错误: {step_name} 输出文件不存在，请先运行该步骤: {path}')
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog='add_subtitles',
        description='MP3 + TXT + 原始SRT + MP4 → 生成英文字幕并烧录到视频'
    )
    parser.add_argument('mp3',              help='英文音频 MP3（TTS 输出）')
    parser.add_argument('txt',              help='英文文稿 TXT')
    parser.add_argument('srt',              help='原始双语 SRT（自动提取时间轴范围）')
    parser.add_argument('video',            help='视频 MP4')

    parser.add_argument('--res',            default='1280x960',
                        help='视频分辨率 WxH（默认: 1280x960）')
    parser.add_argument('--box',            default='0,700,1280,200',
                        help='字幕框 x,y,w,h（默认: 0,700,1280,200）')
    parser.add_argument('--box-color',      default='white@0.95',
                        help='遮罩颜色（默认: white@0.95）')
    parser.add_argument('--font-size',      type=int, default=44)
    parser.add_argument('--color',          default='333333',
                        help='字幕字体颜色 RRGGBB（默认: 333333 深灰）')
    parser.add_argument('--whisper-model',  default='small',
                        choices=['tiny', 'base', 'small', 'medium', 'large'],
                        help='Whisper 模型（默认: small）')
    parser.add_argument('--from-step',      type=int, default=1, choices=[1, 2, 3],
                        help='从第 N 步开始，跳过前面步骤（默认: 1）')
    parser.add_argument('-o', '--output',   default=None,
                        help='输出 MP4（默认: 与输入文件同目录，<视频名>_subtitled.mp4）')
    parser.add_argument('-v', '--verbose',  action='store_true')
    args = parser.parse_args()

    for path in [args.mp3, args.txt, args.srt, args.video]:
        if not os.path.exists(path):
            print(f'错误: 文件不存在: {path}')
            sys.exit(1)

    # All outputs go in the same directory as the MP3
    out_dir  = os.path.dirname(os.path.abspath(args.mp3))
    mp3_base = os.path.splitext(os.path.basename(args.mp3))[0]
    srt_out  = os.path.join(out_dir, mp3_base + '.srt')
    ass_out  = os.path.join(out_dir, mp3_base + '.ass')

    if args.output:
        video_out = os.path.abspath(args.output)
    else:
        vid_base  = os.path.splitext(os.path.basename(args.video))[0]
        video_out = os.path.join(out_dir, vid_base + '_subtitled.mp4')

    # ── Read timing from original SRT ─────────────────────────────────────────
    print(f'读取原始 SRT 时间轴: {os.path.basename(args.srt)}')
    try:
        first_start, last_end = srt_boundaries(args.srt)
    except Exception as e:
        print(f'错误: {e}')
        sys.exit(1)
    start_str = fmt_hhmmss(first_start)
    print(f'  配音起点: {start_str}  配音终点: {fmt_hhmmss(last_end)} ({last_end:.1f}s)')
    print(f'输出目录 : {out_dir}')

    python = sys.executable
    TOTAL  = 3
    bx, by, bw, bh = args.box.split(',')

    # ── Step 1: MP3 + TXT → SRT ───────────────────────────────────────────────
    if args.from_step <= 1:
        ok = run_step(1, TOTAL, 'MP3 + TXT → SRT  (mp3_to_srt)', [
            python, os.path.join(SCRIPT_DIR, 'mp3_to_srt.py'),
            os.path.abspath(args.mp3),
            '--txt',        os.path.abspath(args.txt),
            '--model',      args.whisper_model,
            '--start-time', start_str,
            '-o',           srt_out,
        ], args.verbose)
        if not ok:
            sys.exit(1)
    else:
        check_exists(srt_out, '步骤1')
        print(f'\n[1/{TOTAL}] 跳过 → {srt_out}')

    # ── Step 2: SRT → ASS ─────────────────────────────────────────────────────
    if args.from_step <= 2:
        ok = run_step(2, TOTAL, 'SRT → ASS  (srt_to_ass)', [
            python, os.path.join(SCRIPT_DIR, 'srt_to_ass.py'),
            srt_out,
            '--res',       args.res,
            '--box',       args.box,
            '--font-size', str(args.font_size),
            '--color',     args.color,
            '-o',          ass_out,
        ], args.verbose)
        if not ok:
            sys.exit(1)
    else:
        check_exists(ass_out, '步骤2')
        print(f'\n[2/{TOTAL}] 跳过 → {ass_out}')

    # ── Step 3: FFmpeg drawbox + ASS burn-in ──────────────────────────────────
    if args.from_step <= 3:
        check_exists(ass_out, '步骤2')
        # Use only the filename for ass= and set cwd to its directory.
        # This avoids Windows drive-letter colon conflicts in FFmpeg filter strings.
        ass_name = os.path.basename(ass_out)
        enable   = f"between(t,{first_start:.3f},{last_end:.3f})"
        vf = (
            f"drawbox=x={bx}:y={by}:w={bw}:h={bh}"
            f":color={args.box_color}:t=fill:enable='{enable}',"
            f"ass={ass_name}"
        )
        ok = run_step(3, TOTAL, '烧录字幕到视频  (FFmpeg)', [
            'ffmpeg', '-y',
            '-i', os.path.abspath(args.video),
            '-vf', vf,
            '-c:a', 'copy',
            video_out,
        ], args.verbose, cwd=out_dir)
        if not ok:
            sys.exit(1)
    else:
        print(f'\n[3/{TOTAL}] 跳过 → {video_out}')

    print(f'\n{"═" * 60}')
    print(f'完成！')
    print(f'  英文字幕 SRT : {srt_out}')
    print(f'  ASS 字幕文件 : {ass_out}')
    print(f'  最终视频     : {video_out}')
    print(f'{"═" * 60}')


if __name__ == '__main__':
    main()
