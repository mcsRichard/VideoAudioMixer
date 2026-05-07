"""
pipeline_app.py — PyInstaller-compilable version of pipeline.py.

Calls sub-script main() functions directly (no subprocess) so that
all modules can be bundled into a single exe by PyInstaller.
"""
import argparse
import os
import sys
from contextlib import contextmanager


@contextmanager
def _argv(argv):
    """Temporarily replace sys.argv for a sub-script's argparse."""
    saved = sys.argv
    sys.argv = argv
    try:
        yield
    finally:
        sys.argv = saved


def _run(num, total, label, module_name, argv):
    print(f'\n{"─" * 60}')
    print(f'[{num}/{total}] {label}')
    print(f'{"─" * 60}')
    print()

    import srt_to_txt
    import srt_voice_gen
    import speed_mp3
    import mixer

    dispatch = {
        'srt_to_txt':    srt_to_txt.main,
        'srt_voice_gen': srt_voice_gen.main,
        'speed_mp3':     speed_mp3.main,
        'mixer':         mixer.main,
    }

    with _argv(argv):
        try:
            dispatch[module_name]()
            return True
        except SystemExit as e:
            if e.code in (0, None):
                return True
            print(f'\n错误: 步骤 {num} 失败（退出码 {e.code}）')
            return False
        except Exception as e:
            print(f'\n错误: 步骤 {num} 异常: {e}')
            return False


def main():
    parser = argparse.ArgumentParser(
        prog='VideoAudioMixer',
        description='一键生成：SRT + MP4 → TTS → 变速对齐 → 合入视频'
    )
    parser.add_argument('video',               help='输入视频文件 (.mp4)')
    parser.add_argument('srt',                 help='输入 SRT 字幕文件')
    parser.add_argument('--work-dir',          default=None,
                        help='中间文件保存目录（默认：<视频名>_pipeline）')

    parser.add_argument('--throat-interval',   type=int,   default=30)
    parser.add_argument('--el-model',          default='eleven_v3')
    parser.add_argument('--stability',         type=float, default=0.7)
    parser.add_argument('--similarity-boost',  type=float, default=0.5)
    parser.add_argument('--speed',             type=float, default=1.05)
    parser.add_argument('--sentence-break',    type=float, default=0.5)
    parser.add_argument('--max-chars',         type=int,   default=4500)
    parser.add_argument('--timeout',           type=int,   default=120)
    parser.add_argument('--from-step',         type=int,   default=1,
                        choices=[1, 2, 3, 4])
    parser.add_argument('-v', '--verbose',     action='store_true')
    args = parser.parse_args()

    for path in [args.video, args.srt]:
        if not os.path.exists(path):
            print(f'错误: 文件不存在: {path}')
            sys.exit(1)

    base     = os.path.splitext(os.path.basename(args.video))[0]
    work_dir = args.work_dir or f'{base}_pipeline'
    os.makedirs(work_dir, exist_ok=True)

    txt_path    = os.path.join(work_dir, 'transcript.txt')
    voice_path  = os.path.join(work_dir, 'voice_raw.mp3')
    fitted_path = os.path.join(work_dir, 'voice_fitted.mp3')
    result_path = os.path.join(work_dir, 'result.mp4')
    TOTAL = 4

    print(f'输入视频 : {args.video}')
    print(f'输入 SRT : {args.srt}')
    print(f'工作目录 : {work_dir}/')
    if args.from_step > 1:
        print(f'从步骤 {args.from_step} 开始')

    # ── Step 1 ────────────────────────────────────────────────────────────────
    if args.from_step <= 1:
        ok = _run(1, TOTAL, 'SRT → TXT  提取英文字幕', 'srt_to_txt', [
            'srt_to_txt.py', args.srt,
            '--throat-interval', str(args.throat_interval),
            '-o', txt_path,
        ])
        if not ok:
            sys.exit(1)
    else:
        print(f'\n[1/{TOTAL}] 跳过 → {txt_path}')

    # ── Step 2 ────────────────────────────────────────────────────────────────
    if args.from_step <= 2:
        ok = _run(2, TOTAL, 'TXT → 语音 MP3  ElevenLabs TTS', 'srt_voice_gen', [
            'srt_voice_gen.py', txt_path,
            '--el-model',         args.el_model,
            '--stability',        str(args.stability),
            '--similarity-boost', str(args.similarity_boost),
            '--speed',            str(args.speed),
            '--sentence-break',   str(args.sentence_break),
            '--max-chars',        str(args.max_chars),
            '--timeout',          str(args.timeout),
            '--log-requests',
            '-o', voice_path,
        ])
        if not ok:
            sys.exit(1)
    else:
        print(f'\n[2/{TOTAL}] 跳过 → {voice_path}')

    # ── Step 3 ────────────────────────────────────────────────────────────────
    if args.from_step <= 3:
        ok = _run(3, TOTAL, '语音变速对齐 SRT 时间轴', 'speed_mp3', [
            'speed_mp3.py', voice_path,
            '--srt', args.srt,
            '-o', fitted_path,
        ])
        if not ok:
            sys.exit(1)
    else:
        print(f'\n[3/{TOTAL}] 跳过 → {fitted_path}')

    # ── Step 4 ────────────────────────────────────────────────────────────────
    if args.from_step <= 4:
        ok = _run(4, TOTAL, '合入视频，保留片头片尾原音', 'mixer', [
            'mixer.py', args.video, fitted_path,
            '--srt', args.srt,
            '-o', result_path,
        ])
        if not ok:
            sys.exit(1)
    else:
        print(f'\n[4/{TOTAL}] 跳过 → {result_path}')

    print(f'\n{"═" * 60}')
    print(f'全部完成！')
    print(f'  最终视频 : {result_path}')
    print(f'  中间文件 : {work_dir}/')
    print(f'{"═" * 60}')


if __name__ == '__main__':
    main()
