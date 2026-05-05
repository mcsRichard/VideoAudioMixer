import argparse
import os
import subprocess
import sys


def script_path(name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


def run_step(num, total, label, cmd, verbose=False):
    print(f'\n{"─" * 60}')
    print(f'[{num}/{total}] {label}')
    print(f'{"─" * 60}')
    if verbose:
        print('  ' + ' '.join(f'"{c}"' if ' ' in c else c for c in cmd))
        print()
    result = subprocess.run(cmd, text=True, encoding='utf-8', errors='replace')
    if result.returncode != 0:
        print(f'\n错误: 步骤 {num} 退出码 {result.returncode}，流程中止')
        return False
    return True


def main():
    parser = argparse.ArgumentParser(
        prog='pipeline',
        description='一键生成：SRT + MP4 → TTS → 变速对齐 → 合入视频'
    )
    parser.add_argument('video',               help='输入视频文件 (.mp4)')
    parser.add_argument('srt',                 help='输入 SRT 字幕文件')
    parser.add_argument('--work-dir',          default=None,
                        help='中间文件保存目录（默认：<视频名>_pipeline）')

    # Step 1 options
    parser.add_argument('--throat-interval',   type=int,   default=30,
                        help='srt_to_txt: 每隔 N 行插入 [clears throat]（默认: 30）')

    # Step 2 options
    parser.add_argument('--el-model',          default='eleven_v3',
                        help='ElevenLabs 模型（默认: eleven_v3）')
    parser.add_argument('--stability',         type=float, default=0.7,
                        help='声音稳定性（默认: 0.7）')
    parser.add_argument('--similarity-boost',  type=float, default=0.5,
                        help='与原声相似度（默认: 0.5）')
    parser.add_argument('--speed',             type=float, default=1.05,
                        help='语速（默认: 1.05，eleven_v3 不支持时仅影响 v2 模型）')
    parser.add_argument('--sentence-break',    type=float, default=0.5,
                        help='句尾停顿秒数（默认: 0.5）')
    parser.add_argument('--max-chars',         type=int,   default=4500,
                        help='TTS 每块最大字符数（默认: 4500）')
    parser.add_argument('--timeout',           type=int,   default=120,
                        help='每次 API 请求超时秒数（默认: 120）')

    # Pipeline control
    parser.add_argument('--from-step',         type=int,   default=1,
                        choices=[1, 2, 3, 4],
                        help='从第 N 步开始执行，跳过前面步骤（默认: 1）')
    parser.add_argument('-v', '--verbose',     action='store_true',
                        help='打印每步的完整命令')
    args = parser.parse_args()

    for path in [args.video, args.srt]:
        if not os.path.exists(path):
            print(f'错误: 文件不存在: {path}')
            sys.exit(1)

    base     = os.path.splitext(os.path.basename(args.video))[0]
    work_dir = args.work_dir or f'{base}_pipeline'
    os.makedirs(work_dir, exist_ok=True)

    python       = sys.executable
    txt_path     = os.path.join(work_dir, 'transcript.txt')
    voice_path   = os.path.join(work_dir, 'voice_raw.mp3')
    fitted_path  = os.path.join(work_dir, 'voice_fitted.mp3')
    result_path  = os.path.join(work_dir, 'result.mp4')
    TOTAL        = 4

    print(f'输入视频 : {args.video}')
    print(f'输入 SRT : {args.srt}')
    print(f'工作目录 : {work_dir}/')
    if args.from_step > 1:
        print(f'从步骤 {args.from_step} 开始（跳过前 {args.from_step - 1} 步）')

    # ── Step 1: SRT → TXT ────────────────────────────────────────────────────
    if args.from_step <= 1:
        ok = run_step(1, TOTAL, 'SRT → TXT  提取英文字幕 (srt_to_txt)', [
            python, script_path('srt_to_txt.py'), args.srt,
            '--throat-interval', str(args.throat_interval),
            '-o', txt_path,
        ], args.verbose)
        if not ok:
            sys.exit(1)
    else:
        print(f'\n[1/{TOTAL}] 跳过 → {txt_path}')

    # ── Step 2: TXT → Voice MP3 ───────────────────────────────────────────────
    if args.from_step <= 2:
        ok = run_step(2, TOTAL, 'TXT → 语音 MP3  ElevenLabs TTS (srt_voice_gen)', [
            python, script_path('srt_voice_gen.py'), txt_path,
            '--el-model',         args.el_model,
            '--stability',        str(args.stability),
            '--similarity-boost', str(args.similarity_boost),
            '--speed',            str(args.speed),
            '--sentence-break',   str(args.sentence_break),
            '--max-chars',        str(args.max_chars),
            '--log-requests',
            '--timeout',          str(args.timeout),
            '-o', voice_path,
        ], args.verbose)
        if not ok:
            sys.exit(1)
    else:
        print(f'\n[2/{TOTAL}] 跳过 → {voice_path}')

    # ── Step 3: Speed-fit to SRT timing ──────────────────────────────────────
    if args.from_step <= 3:
        ok = run_step(3, TOTAL, '语音变速对齐 SRT 时间轴 (speed_mp3)', [
            python, script_path('speed_mp3.py'), voice_path,
            '--srt', args.srt,
            '-o', fitted_path,
        ], args.verbose)
        if not ok:
            sys.exit(1)
    else:
        print(f'\n[3/{TOTAL}] 跳过 → {fitted_path}')

    # ── Step 4: Mix into video ────────────────────────────────────────────────
    if args.from_step <= 4:
        ok = run_step(4, TOTAL, '合入视频，保留片头片尾原音 (mixer)', [
            python, script_path('mixer.py'), args.video, fitted_path,
            '--srt', args.srt,
            '-o', result_path,
        ], args.verbose)
        if not ok:
            sys.exit(1)
    else:
        print(f'\n[4/{TOTAL}] 跳过 → {result_path}')

    print(f'\n{"═" * 60}')
    print(f'全部完成！')
    print(f'  最终视频 : {result_path}')
    print(f'  中间文件 : {work_dir}/')
    print(f'    transcript.txt       ← 步骤 1 输出')
    print(f'    voice_raw.mp3        ← 步骤 2 输出')
    print(f'    voice_raw_segments/  ← 步骤 2 分块 MP3')
    print(f'    voice_raw_requests.json ← 步骤 2 API 日志')
    print(f'    voice_fitted.mp3     ← 步骤 3 输出')
    print(f'    result.mp4           ← 步骤 4 最终输出')
    print(f'{"═" * 60}')


if __name__ == '__main__':
    main()
