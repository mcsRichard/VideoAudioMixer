import argparse
import os
import re
import sys


def fmt_srt_time(seconds):
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    ms = int(round((seconds % 1) * 1000))
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def load_txt_words(path):
    for enc in ('utf-8-sig', 'gbk', 'utf-16', 'latin-1'):
        try:
            with open(path, encoding=enc) as f:
                text = f.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    # collapse whitespace, return list of words
    return re.sub(r'\s+', ' ', text).strip().split()


def align_txt_to_words(whisper_words, txt_words):
    """
    Map each Whisper word to its positional counterpart in txt_words.
    Returns list of (start, end, txt_word) tuples.
    Whisper may have slightly different word count due to filler/noise;
    we interpolate timing linearly for any mismatch.
    """
    n_w = len(whisper_words)
    n_t = len(txt_words)
    result = []
    for i, tw in enumerate(txt_words):
        # map txt index → whisper index proportionally
        wi = min(int(i * n_w / n_t), n_w - 1)
        ww = whisper_words[wi]
        result.append((ww['start'], ww['end'], tw))
    return result


def group_into_segments(aligned_words, max_words=12):
    """Group aligned words into SRT segments of max_words each."""
    segments = []
    i = 0
    while i < len(aligned_words):
        chunk = aligned_words[i:i + max_words]
        start = chunk[0][0]
        end   = chunk[-1][1]
        text  = ' '.join(w[2] for w in chunk)
        segments.append((start, end, text))
        i += max_words
    return segments


def parse_time_arg(s):
    """Parse HH:MM:SS, MM:SS, or plain seconds into float seconds."""
    s = s.strip()
    parts = s.split(':')
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(s)


def write_srt(segments, output_path, offset=0.0):
    with open(output_path, 'w', encoding='utf-8') as f:
        for idx, (start, end, text) in enumerate(segments, 1):
            f.write(f'{idx}\n')
            f.write(f'{fmt_srt_time(start + offset)} --> {fmt_srt_time(end + offset)}\n')
            f.write(f'{text}\n\n')


def main():
    parser = argparse.ArgumentParser(
        prog='mp3_to_srt',
        description='用 Whisper 转录 MP3，结合 TXT 文字生成时间对齐的 SRT'
    )
    parser.add_argument('input',             help='输入 MP3 文件')
    parser.add_argument('--txt',             default=None,
                        help='TXT 文件（含完整正确文字）；不提供则直接使用 Whisper 识别文字')
    parser.add_argument('--model',           default='small',
                        choices=['tiny', 'base', 'small', 'medium', 'large'],
                        help='Whisper 模型大小（默认: small；质量更高用 medium/large）')
    parser.add_argument('--language',        default='en',
                        help='音频语言（默认: en）')
    parser.add_argument('--max-words',       type=int, default=12,
                        help='每条字幕最多单词数（默认: 12）')
    parser.add_argument('--start-time',      default=None,
                        help='SRT 时间轴起始偏移（格式：HH:MM:SS、MM:SS 或秒数）。'
                             '用于 MP3 是视频某片段时，使生成的 SRT 时间轴对齐视频')
    parser.add_argument('-o', '--output',    default=None,
                        help='输出 SRT 路径（默认：同名 .srt）')
    parser.add_argument('-v', '--verbose',   action='store_true')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f'错误: 文件不存在: {args.input}')
        sys.exit(1)

    try:
        import whisper
    except ImportError:
        print('错误: 请先安装 Whisper：pip install openai-whisper')
        sys.exit(1)

    offset = 0.0
    if args.start_time:
        try:
            offset = parse_time_arg(args.start_time)
        except ValueError:
            print(f'错误: 无效的起始时间格式: {args.start_time}')
            sys.exit(1)
        print(f'  时间轴偏移: +{fmt_srt_time(offset)} ({offset:.3f}s)')

    output = args.output or os.path.splitext(args.input)[0] + '.srt'

    # ── 1. load Whisper model ─────────────────────────────────────────────────
    print(f'[1/3] 加载 Whisper 模型 ({args.model})...', end='', flush=True)
    model = whisper.load_model(args.model)
    print(' ✓')

    # ── 2. transcribe ─────────────────────────────────────────────────────────
    print(f'[2/3] 转录音频...', end='', flush=True)
    result = model.transcribe(
        args.input,
        language=args.language,
        word_timestamps=True,
        verbose=args.verbose or None,
    )
    print(' ✓')

    # extract flat word list with timestamps
    whisper_words = []
    for seg in result['segments']:
        for w in seg.get('words', []):
            word = re.sub(r'[^\w\'\-]', '', w['word']).strip()
            if word:
                whisper_words.append({'word': word, 'start': w['start'], 'end': w['end']})

    if args.verbose:
        print(f'  Whisper 识别: {len(whisper_words)} 个单词')

    # ── 3. build SRT ──────────────────────────────────────────────────────────
    print(f'[3/3] 生成 SRT...', end='', flush=True)

    if args.txt:
        txt_words = load_txt_words(args.txt)
        if args.verbose:
            print(f'\n  TXT 单词数: {len(txt_words)}  Whisper 单词数: {len(whisper_words)}')
        aligned   = align_txt_to_words(whisper_words, txt_words)
        segments  = group_into_segments(aligned, args.max_words)
    else:
        # use Whisper text directly, grouped by max_words
        aligned  = [(w['start'], w['end'], w['word']) for w in whisper_words]
        segments = group_into_segments(aligned, args.max_words)

    write_srt(segments, output, offset)
    print(f' ✓  {len(segments)} 条字幕')
    print(f'\n完成！输出文件: {output}')
    if args.txt:
        print(f'  模式: TXT 对齐（文字来自 {os.path.basename(args.txt)}，时间轴来自 Whisper）')
    else:
        print(f'  模式: 纯 Whisper 转录')


if __name__ == '__main__':
    main()
