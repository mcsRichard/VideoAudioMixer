import argparse
import base64
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave


# ── Config loading ────────────────────────────────────────────────────────────

def _read_config(filename):
    # When frozen (PyInstaller exe), config files live next to the exe
    base = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) \
           else os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, filename)
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        text = f.read()
    result = {}
    for line in text.splitlines():
        m = re.match(r'^(.+?):\s*(\S+)', line.strip())
        if m:
            result[m.group(1).strip().lower()] = m.group(2).strip()
    return result


def load_resemble_config():
    cfg = _read_config('resembleAI.md')
    return cfg.get('api key'), cfg.get('voice uuid')


def load_elevenlabs_config():
    cfg = _read_config('ElevenLabs.md')
    return cfg.get('api key'), cfg.get('voice id')


# ── SRT parsing ───────────────────────────────────────────────────────────────

def parse_srt_time(s):
    m = re.match(r'(\d+):(\d+):(\d+)[,.](\d+)', s.strip())
    if not m:
        raise ValueError(f"Invalid SRT timestamp: '{s}'")
    h, mm, ss, ms = m.groups()
    return int(h) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000


def parse_srt(path):
    """Returns list of (start_sec, end_sec, text)."""
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        content = f.read()
    entries = []
    for block in re.split(r'\n\s*\n', content.strip()):
        lines = [ln for ln in block.strip().splitlines() if ln.strip()]
        if len(lines) < 3:
            continue
        tm = None
        text_lines = []
        for i, line in enumerate(lines):
            if '-->' in line and tm is None:
                tm = re.match(r'(.+?)\s*-->\s*(.+)', line)
                text_lines = lines[i + 1:]
                break
        if not tm:
            continue
        start = parse_srt_time(tm.group(1))
        end   = parse_srt_time(tm.group(2))
        text  = ' '.join(text_lines).strip()
        text  = re.sub(r'<[^>]+>', '', text).strip()
        if text and end > start:
            entries.append((start, end, text))
    return entries


# ── TXT parsing ───────────────────────────────────────────────────────────────

_EL_HARD_LIMIT = 4500 


def parse_txt(path, max_chars=1000):
    """
    Split text into chunks at paragraph boundaries only.
    Paragraphs ≤ max_chars are merged with neighbours when they fit.
    Paragraphs > max_chars but ≤ hard limit are kept whole (one chunk).
    Only paragraphs exceeding the hard limit are force-split at sentences.
    """
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        content = f.read()

    content = re.sub(r'\r\n', '\n', content)
    content = re.sub(r'\n{3,}', '\n\n', content).strip()

    paragraphs = re.split(r'\n\n+', content)
    chunks = []

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            # merge with previous chunk if it still fits within max_chars
            if chunks and len(chunks[-1]) + len(para) + 1 <= max_chars:
                chunks[-1] += ' ' + para
            else:
                chunks.append(para)
        elif len(para) <= _EL_HARD_LIMIT:
            # paragraph too long for max_chars but within API limit — keep whole
            chunks.append(para)
        else:
            # paragraph exceeds API limit — must split at sentence boundaries
            sentences = re.split(r'(?<=[.!?])\s+', para)
            current = ''
            for sent in sentences:
                if len(current) + len(sent) + 1 <= _EL_HARD_LIMIT:
                    current = (current + ' ' + sent).strip()
                else:
                    if current:
                        chunks.append(current)
                    current = sent[:_EL_HARD_LIMIT]
            if current:
                chunks.append(current)

    return [c for c in chunks if c.strip()]


# ── Resemble.AI TTS ───────────────────────────────────────────────────────────

def tts_resemble(api_key, voice_uuid, text, sample_rate=44100,
                 model='chatterbox', retries=3):
    url = 'https://f.cluster.resemble.ai/synthesize'
    payload = json.dumps({
        'voice_uuid':    voice_uuid,
        'data':          text,
        'output_format': 'mp3',
        'sample_rate':   sample_rate,
        'model':         model,
        'use_hd':        True,
    }).encode('utf-8')
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type':  'application/json',
    }
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            b64 = data.get('audio_content')
            if not b64:
                raise ValueError(f"Missing audio_content. Keys: {list(data.keys())}")
            return base64.b64decode(b64)
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"HTTP {e.code}: {body[:300]}")
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise


# ── ElevenLabs TTS ────────────────────────────────────────────────────────────

def add_sentence_breaks(text, break_sec=0.8, comma_break_sec=0.2):
    """Insert SSML <break> after punctuation for v2 models."""
    brk       = f'<break time="{break_sec}s"/>'
    comma_brk = f'<break time="{comma_break_sec}s"/>'
    text = re.sub(r'([.!?])\s+', rf'\1{brk} ',       text)
    text = re.sub(r'([.!?])$',   rf'\1{brk}',         text)
    text = re.sub(r'([,])\s+',   rf'\1{comma_brk} ',  text)
    return text


def add_v3_breaks(text, break_sec=0.8):
    """Insert ellipsis dots after sentence-ending punctuation for v3 models.
    Dot count scales with break_sec: 0.5s→2dots, 1.0s→3dots, 1.5s→5dots."""
    dots = '.' * max(2, min(8, int(break_sec * 3 + 0.5)))
    text = re.sub(r'([.!?])\s+', rf'\1{dots} ', text)
    text = re.sub(r'([.!?])$',   rf'\1{dots}',  text)
    return text


def tts_elevenlabs(api_key, voice_id, text, sample_rate=44100,
                   model='eleven_multilingual_v2', sentence_break=0.8,
                   stability=0.75, style=0.0, speed=1.0, comma_break=0.2,
                   similarity_boost=0.8, retries=3, request_log=None,
                   chunk_index=None, previous_text=None, next_text=None,
                   timeout=120):
    is_v3 = 'v3' in model
    if sentence_break > 0:
        if is_v3:
            text = add_v3_breaks(text, sentence_break)
        else:
            text = add_sentence_breaks(text, sentence_break, comma_break)
    fmt_param = f'mp3_{sample_rate}_128' if sample_rate in (44100, 22050) else 'mp3_44100_128'
    url = (f'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}'
           f'?output_format={fmt_param}')
    voice_settings = {
        'stability':        stability,
        'similarity_boost': similarity_boost,
        'style':            style,
        'use_speaker_boost': True,
        'speed':            speed,
    }
    body = {
        'text':           text,
        'model_id':       model,
        'voice_settings': voice_settings,
    }
    if not is_v3:
        if previous_text:
            body['previous_text'] = previous_text
        if next_text:
            body['next_text'] = next_text
    payload = json.dumps(body).encode('utf-8')
    headers = {
        'xi-api-key':   api_key,
        'Content-Type': 'application/json',
        'Accept':       'audio/mpeg',
    }
    if request_log is not None:
        request_log.append({
            'chunk_index':    chunk_index,
            'timestamp':      datetime.datetime.now().isoformat(timespec='seconds'),
            'provider':       'elevenlabs',
            'model':          model,
            'voice_id':       voice_id,
            'output_format':  fmt_param,
            'sentence_break': sentence_break if sentence_break > 0 else None,
            'comma_break':    comma_break    if (not is_v3 and comma_break > 0) else None,
            'v3_dots':        '.' * max(2, min(8, int(sentence_break * 3 + 0.5))) if (is_v3 and sentence_break > 0) else None,
            'voice_settings': voice_settings,
            'previous_text':  bool(previous_text) if not is_v3 else None,
            'next_text':      bool(next_text)      if not is_v3 else None,
        })
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"HTTP {e.code}: {body[:300]}")
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise


# ── Audio assembly helpers ────────────────────────────────────────────────────

def get_ffmpeg():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
        p = os.path.join(base, 'ffmpeg.exe')
        if os.path.exists(p):
            return p
    return 'ffmpeg'


def create_silence_wav(path, duration_sec, sample_rate=44100, channels=2):
    n_frames = max(1, int(duration_sec * sample_rate))
    with wave.open(path, 'w') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        chunk  = sample_rate
        zeros  = bytes(chunk * channels * 2)
        remaining = n_frames
        while remaining > 0:
            n = min(chunk, remaining)
            wf.writeframes(zeros[:n * channels * 2])
            remaining -= n


def mp3_to_wav(mp3_path, wav_path, ffmpeg, sample_rate=44100):
    # dynaudnorm normalises each clip to a consistent loudness level
    cmd = [ffmpeg, '-y', '-i', mp3_path,
           '-af', 'dynaudnorm',
           '-ar', str(sample_rate), '-ac', '2', '-sample_fmt', 's16',
           '-f', 'wav', wav_path]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode('utf-8', errors='replace')[-400:])


def wav_duration(wav_path):
    with wave.open(wav_path, 'r') as wf:
        return wf.getnframes() / wf.getframerate()


def fit_to_slot(wav_in, wav_out, clip_dur, slot_dur, ffmpeg,
                min_tempo=0.5, max_tempo=1.5):
    """Stretch/compress to slot_dur via atempo. Returns actual output duration."""
    tempo = clip_dur / slot_dur
    if tempo < min_tempo:
        shutil.copy2(wav_in, wav_out)
        return clip_dur
    tempo = min(tempo, max_tempo)
    filters = []
    t = tempo
    while t < 0.5:
        filters.append('atempo=0.5')
        t /= 0.5
    while t > 2.0:
        filters.append('atempo=2.0')
        t /= 2.0
    filters.append(f'atempo={t:.6f}')
    cmd = [ffmpeg, '-y', '-i', wav_in, '-af', ','.join(filters), wav_out]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode('utf-8', errors='replace')[-400:])
    return clip_dur / tempo


def assemble_audio(concat_list, output_path, ffmpeg, total_duration=None):
    """Concatenate WAV files via concat demuxer and encode to MP3."""
    concat_txt = output_path + '.concat_list.txt'
    try:
        with open(concat_txt, 'w', encoding='utf-8') as f:
            for p in concat_list:
                # Absolute path prevents FFmpeg from mis-resolving relative paths
                # when the concat list itself is inside a subdirectory
                escaped = os.path.abspath(p).replace('\\', '/').replace("'", "\\'")
                f.write(f"file '{escaped}'\n")
        cmd = [ffmpeg, '-y',
               '-f', 'concat', '-safe', '0', '-i', concat_txt,
               '-c:a', 'libmp3lame', '-b:a', '192k']
        if total_duration:
            cmd += ['-t', str(total_duration)]
        cmd += [output_path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-500:])
    finally:
        if os.path.exists(concat_txt):
            os.remove(concat_txt)


# ── Progress + formatting ─────────────────────────────────────────────────────

def print_progress(current, total, bar_width=36):
    pct = min(current / total, 1.0) if total > 0 else 0
    filled = int(bar_width * pct)
    bar = '█' * filled + '░' * (bar_width - filled)
    sys.stdout.write(f'\r  [{bar}] {current}/{total}  ({pct*100:.0f}%)')
    sys.stdout.flush()


def fmt(sec):
    h, r = divmod(int(sec), 3600)
    m, s = divmod(r, 60)
    return f'{h:02d}:{m:02d}:{s:02d}'


# ── TTS call loop (shared) ────────────────────────────────────────────────────


def run_tts_loop(texts, call_tts, segments_dir, delay, test_count=None, context_chars=200):
    """
    Call TTS for each text chunk, save as segment_XXXX.mp3 in segments_dir.
    Passes previous_text/next_text context to each call for prosody continuity.
    Skips chunks whose file already exists (allows partial re-runs).
    Returns list of (index, mp3_path) for successful clips.
    """
    if test_count:
        texts = texts[:test_count]

    os.makedirs(segments_dir, exist_ok=True)
    clips   = []
    failed  = 0
    skipped = 0
    t0      = time.time()

    for i, text in enumerate(texts):
        mp3_path = os.path.join(segments_dir, f'segment_{i:04d}.mp3')
        if os.path.exists(mp3_path):
            skipped += 1
        else:
            prev_ctx = texts[i - 1][-context_chars:] if (i > 0 and context_chars > 0) else None
            next_ctx = texts[i + 1][:context_chars]  if (i < len(texts) - 1 and context_chars > 0) else None
            try:
                audio = call_tts(text, previous_text=prev_ctx, next_text=next_ctx)
                with open(mp3_path, 'wb') as f:
                    f.write(audio)
            except Exception as e:
                sys.stdout.write(f'\n  ⚠  第 {i+1} 块失败: {e}\n')
                failed += 1
                print_progress(i + 1, len(texts))
                continue
            if delay > 0 and i < len(texts) - 1:
                time.sleep(delay)
        clips.append((i, mp3_path))
        print_progress(i + 1, len(texts))

    skipped_str = f'，跳过 {skipped} 块（已缓存）' if skipped else ''
    print(f'\n      成功 {len(clips)} 块，失败 {failed} 块{skipped_str}，耗时 {time.time()-t0:.0f}s')
    return clips


# ── Main ──────────────────────────────────────────────────────────────────────

ELEVENLABS_MODELS = ['eleven_multilingual_v2', 'eleven_turbo_v2_5', 'eleven_flash_v2_5',
                     'eleven_v3', 'eleven_multilingual_v3']
RESEMBLE_MODELS   = ['chatterbox', 'chatterbox-turbo']


def main():
    el_api_key,  el_voice_id   = load_elevenlabs_config()
    re_api_key,  re_voice_uuid = load_resemble_config()

    parser = argparse.ArgumentParser(
        prog='srt_voice_gen',
        description='从 SRT 或 TXT 文件生成语音 MP3（ElevenLabs / Resemble.AI）'
    )
    parser.add_argument('input',            help='输入文件：.srt（时间对齐）或 .txt（连续朗读）')
    parser.add_argument('--provider',       default='elevenlabs',
                        choices=['elevenlabs', 'resemble'],
                        help='TTS 服务商（默认: elevenlabs）')

    el = parser.add_argument_group('ElevenLabs')
    el.add_argument('--el-api-key',  default=el_api_key,
                    help='API Key（默认读取 ElevenLabs.md）')
    el.add_argument('--el-voice-id', default=el_voice_id,
                    help='Voice ID（默认读取 ElevenLabs.md）')
    el.add_argument('--el-model',    default='eleven_v3',
                    choices=ELEVENLABS_MODELS)

    rg = parser.add_argument_group('Resemble.AI')
    rg.add_argument('--re-api-key',    default=re_api_key,
                    help='API Key（默认读取 resembleAI.md）')
    rg.add_argument('--re-voice-uuid', default=re_voice_uuid,
                    help='Voice UUID（默认读取 resembleAI.md）')
    rg.add_argument('--re-model',      default='chatterbox',
                    choices=RESEMBLE_MODELS)

    parser.add_argument('-o', '--output',   default='voice_output.mp3')
    parser.add_argument('--duration',       type=float, default=None,
                        help='[SRT] 输出总时长（秒），默认取最后一条结束时间')
    parser.add_argument('--max-chars',      type=int, default=1000,
                        help='[TXT] 每块最大字符数（默认: 1000，约60秒/块）')
    parser.add_argument('--sample-rate',    type=int, default=44100)
    parser.add_argument('--min-tempo',      type=float, default=0.5,
                        help='[SRT] 最小拉伸比（默认: 0.5）')
    parser.add_argument('--max-tempo',      type=float, default=1.5,
                        help='[SRT] 最大压缩比（默认: 1.5）')
    parser.add_argument('--sentence-break',  type=float, default=0.8,
                        help='句尾停顿秒数，0=关闭（默认: 0.8，仅限v2模型）')
    parser.add_argument('--comma-break',     type=float, default=0.2,
                        help='逗号停顿秒数（默认: 0.2）')
    parser.add_argument('--stability',        type=float, default=0.75,
                        help='声音稳定性 0~1，越低越有感情/越不稳定（默认: 0.75）')
    parser.add_argument('--style',            type=float, default=0.0,
                        help='语气夸张度 0~1，v2模型有效（默认: 0，建议0.3~0.5）')
    parser.add_argument('--similarity-boost', type=float, default=0.8,
                        help='与原声相似度 0~1，越低越有创作发挥空间（默认: 0.8）')
    parser.add_argument('--speed',           type=float, default=1.0,
                        help='语速 0.7~1.2，1.0=正常，0.8=慢20%%（默认: 1.0）')
    parser.add_argument('--post-speed',      type=float, default=1.0,
                        help='输出后处理加速倍率（atempo），1.0=不处理（默认: 1.0）')
    parser.add_argument('--delay',          type=float, default=0.3)
    parser.add_argument('--timeout',        type=int,   default=120,
                        help='每次 API 请求超时秒数（默认: 120）')
    parser.add_argument('--test',           action='store_true',
                        help='测试模式：只处理前 5 条/块')
    parser.add_argument('--segments-dir',   default=None,
                        help='单独片段 MP3 输出目录（默认：<输出文件名>_segments）')
    parser.add_argument('--context-chars',   type=int, default=200,
                        help='传给 API 的上下文字符数（previous/next_text），0=关闭（默认: 200，仅 v2 模型）')
    parser.add_argument('--log-requests',   action='store_true',
                        help='将每次 API 请求参数（不含文本）记录到 JSON 文件')
    args = parser.parse_args()

    # ── validate credentials ──────────────────────────────────────────────────
    request_log = [] if args.log_requests else None

    if args.provider == 'elevenlabs':
        if not args.el_api_key:
            print('错误: 未找到 ElevenLabs API Key，请在 ElevenLabs.md 中添加')
            sys.exit(1)
        if not args.el_voice_id:
            print('错误: 未找到 ElevenLabs Voice ID，请在 ElevenLabs.md 中添加')
            sys.exit(1)
        _chunk_counter = [0]
        def call_tts(text, previous_text=None, next_text=None):
            idx = _chunk_counter[0]
            _chunk_counter[0] += 1
            return tts_elevenlabs(args.el_api_key, args.el_voice_id, text,
                                  args.sample_rate, args.el_model, args.sentence_break,
                                  args.stability, args.style, args.speed, args.comma_break,
                                  args.similarity_boost, request_log=request_log,
                                  chunk_index=idx, previous_text=previous_text,
                                  next_text=next_text, timeout=args.timeout)
        provider_label = f'ElevenLabs ({args.el_model})'
    else:
        if not args.re_api_key:
            print('错误: 未找到 Resemble.AI API Key，请在 resembleAI.md 中添加')
            sys.exit(1)
        if not args.re_voice_uuid:
            print('错误: 未找到 Resemble.AI Voice UUID，请在 resembleAI.md 中添加')
            sys.exit(1)
        def call_tts(text, **_):
            return tts_resemble(args.re_api_key, args.re_voice_uuid, text,
                                args.sample_rate, args.re_model)
        provider_label = f'Resemble.AI ({args.re_model})'

    if not os.path.exists(args.input):
        print(f'错误: 文件不存在: {args.input}')
        sys.exit(1)

    ffmpeg       = get_ffmpeg()
    t_start      = time.time()
    segments_dir = args.segments_dir or (os.path.splitext(args.output)[0] + '_segments')
    wav_dir      = os.path.join(segments_dir, '_wav')
    ext          = os.path.splitext(args.input)[1].lower()
    is_srt    = ext == '.srt'
    mode      = 'SRT' if is_srt else 'TXT'

    # ── 1. parse input ────────────────────────────────────────────────────────
    print(f'[1/4] 解析 {mode} 文件...', end='', flush=True)

    if is_srt:
        entries = parse_srt(args.input)
        if not entries:
            print('\n错误: 未找到有效字幕条目')
            sys.exit(1)
        texts          = [e[2] for e in entries]
        total_duration = args.duration or entries[-1][1]
        test_n         = 5 if args.test else None
        print(f' ✓  {len(entries)} 条字幕')
        print(f'      首条: {fmt(entries[0][0])}  末条: {fmt(entries[-1][1])}'
              f'  输出时长: {fmt(total_duration)}')
    else:
        chunks = parse_txt(args.input, args.max_chars)
        if not chunks:
            print('\n错误: 文件内容为空')
            sys.exit(1)
        texts          = chunks
        total_duration = None
        test_n         = 5 if args.test else None
        total_chars    = sum(len(c) for c in chunks)
        print(f' ✓  {len(chunks)} 块  共 {total_chars:,} 字符')

    label = '  [测试模式]' if args.test else ''
    print(f'      Provider: {provider_label}{label}')

    # ── 2. TTS API calls ──────────────────────────────────────────────────────
    print(f'[2/4] 调用 TTS API（共 {min(len(texts), test_n or len(texts))} 次）...')
    clips = run_tts_loop(texts, call_tts, segments_dir, args.delay, test_n, args.context_chars)

    if not clips:
        print('错误: 所有 API 调用均失败')
        sys.exit(1)

    # write segment index
    index_path = os.path.join(segments_dir, 'segments_index.txt')
    active_texts = texts[:test_n] if test_n else texts
    with open(index_path, 'w', encoding='utf-8') as f:
        for i, text in enumerate(active_texts):
            preview = text[:80].replace('\n', ' ')
            f.write(f'segment_{i:04d}.mp3  {preview}\n')

    # ── 3. build concat list ──────────────────────────────────────────────────
    print('[3/4] 准备音频片段...')
    os.makedirs(wav_dir, exist_ok=True)

    concat_list = []

    if is_srt:
        # SRT mode: insert silence gaps + atempo fit to slot
        cursor = 0.0
        active_entries = entries[:test_n] if args.test else entries

        for idx, mp3_path in clips:
            start, end, _ = active_entries[idx]
            gap = start - cursor
            if gap > 0.001:
                sil_path = os.path.join(wav_dir, f'sil_{idx:04d}.wav')
                create_silence_wav(sil_path, gap, args.sample_rate)
                concat_list.append(sil_path)

            wav_raw  = os.path.join(wav_dir, f'clip_{idx:04d}_raw.wav')
            wav_path = os.path.join(wav_dir, f'clip_{idx:04d}.wav')
            try:
                mp3_to_wav(mp3_path, wav_raw, ffmpeg, args.sample_rate)
                clip_dur = wav_duration(wav_raw)
                slot_dur = end - start
                clip_dur = fit_to_slot(wav_raw, wav_path, clip_dur, slot_dur,
                                       ffmpeg, args.min_tempo, args.max_tempo)
            except Exception as e:
                sys.stdout.write(f'\n  ⚠  第 {idx+1} 条处理失败，跳过: {e}\n')
                continue

            concat_list.append(wav_path)
            cursor = max(start, cursor) + clip_dur
            print_progress(idx + 1, len(clips))

        print()
        tail = total_duration - cursor
        if tail > 0.001:
            sil_tail = os.path.join(wav_dir, 'sil_tail.wav')
            create_silence_wav(sil_tail, tail, args.sample_rate)
            concat_list.append(sil_tail)

    else:
        # TXT mode: simple sequential concat, no timing
        for i, (idx, mp3_path) in enumerate(clips):
            wav_path = os.path.join(wav_dir, f'clip_{idx:04d}.wav')
            try:
                mp3_to_wav(mp3_path, wav_path, ffmpeg, args.sample_rate)
            except Exception as e:
                sys.stdout.write(f'\n  ⚠  第 {idx+1} 块转换失败，跳过: {e}\n')
                continue
            if concat_list:  # insert 1s silence between segments
                sil_path = os.path.join(wav_dir, f'sil_{idx:04d}.wav')
                create_silence_wav(sil_path, 1.0, args.sample_rate)
                concat_list.append(sil_path)
            concat_list.append(wav_path)
            print_progress(i + 1, len(clips))
        print()

    if not concat_list:
        print('错误: 没有可组装的音频片段')
        sys.exit(1)

    # ── 4. encode final MP3 ───────────────────────────────────────────────────
    print('[4/4] FFmpeg 编码输出 MP3...', end='', flush=True)
    try:
        assemble_audio(concat_list, args.output, ffmpeg, total_duration)
    except Exception as e:
        print(f'\n错误: FFmpeg 失败: {e}')
        sys.exit(1)

    print(' ✓')

    # ── 5. post-speed (atempo) ────────────────────────────────────────────────
    if abs(args.post_speed - 1.0) > 0.001:
        print(f'[5/5] 后处理加速 {args.post_speed}x (atempo)...', end='', flush=True)
        tmp = args.output + '.tmp.mp3'
        # chain atempo filters for values outside 0.5~2.0
        ratio = args.post_speed
        filters = []
        while ratio > 2.0:
            filters.append('atempo=2.0')
            ratio /= 2.0
        while ratio < 0.5:
            filters.append('atempo=0.5')
            ratio /= 0.5
        filters.append(f'atempo={ratio:.6f}')
        af = ','.join(filters)
        cmd = [ffmpeg, '-y', '-i', args.output, '-af', af,
               '-c:a', 'libmp3lame', '-b:a', '192k', tmp]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        if r.returncode != 0:
            print(f'\n警告: atempo 失败，保留原速文件\n{r.stderr[-300:]}')
            if os.path.exists(tmp):
                os.remove(tmp)
        else:
            os.replace(tmp, args.output)
            print(' ✓')

    size_mb = os.path.getsize(args.output) / 1024 / 1024
    elapsed = time.time() - t_start
    print(f'\n完成！')
    print(f'  模式:     {mode}')
    print(f'  输出文件: {args.output}  ({size_mb:.1f} MB)')
    if total_duration:
        print(f'  音频时长: {fmt(total_duration)}')
    print(f'  总耗时:   {elapsed:.0f}s')

    if request_log is not None:
        log_path = os.path.splitext(args.output)[0] + '_requests.json'
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(request_log, f, ensure_ascii=False, indent=2)
        print(f'  请求日志: {log_path}  ({len(request_log)} 条)')

    shutil.rmtree(wav_dir, ignore_errors=True)
    print(f'  片段目录: {segments_dir}  ({len(clips)} 个文件)')


if __name__ == '__main__':
    main()
