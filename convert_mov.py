import argparse
import os
import re
import subprocess
import sys
import time


def get_ffmpeg_paths():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
        ffmpeg = os.path.join(base, 'ffmpeg.exe')
        ffprobe = os.path.join(base, 'ffprobe.exe')
        if os.path.exists(ffmpeg):
            return ffmpeg, ffprobe
    return 'ffmpeg', 'ffprobe'


def get_duration(ffprobe, path):
    cmd = [ffprobe, '-v', 'quiet', '-print_format', 'json', '-show_format', path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")
    import json
    data = json.loads(result.stdout)
    return float(data['format']['duration'])


def parse_time(s):
    parts = s.strip().split(':')
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    except ValueError:
        pass
    raise ValueError(f"Invalid time: '{s}'")


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
        eta_str = f"ETA {eta}s"
    else:
        eta_str = "calculating..."
    line = f"\r  {cur_str} / {tot_str}  [{bar}]  {pct*100:5.1f}%  {eta_str}   "
    sys.stdout.write(line)
    sys.stdout.flush()


def convert_mov_to_mp4(
    input_path: str,
    output_path: str,
    *,
    video_codec: str = 'libx264',
    audio_codec: str = 'aac',
    crf: int = 23,
    preset: str = 'medium',
    audio_bitrate: str = '192k',
    pix_fmt: str = 'yuv420p',
    verbose: bool = False,
) -> str:
    """Convert a MOV file to a standard MP4 with H.264/AAC encoding.

    Args:
        input_path:    Path to the source .mov file.
        output_path:   Destination .mp4 path.
        video_codec:   FFmpeg video encoder (default: libx264).
        audio_codec:   FFmpeg audio encoder (default: aac).
        crf:           Constant Rate Factor for libx264; lower = higher quality (0-51, default 23).
        preset:        libx264 encoding speed preset (default: medium).
        audio_bitrate: Audio bitrate (default: 192k).
        pix_fmt:       Output pixel format (default: yuv420p — required for broad compatibility;
                       ProRes source is 10-bit 4:2:2 which most decoders cannot handle).
        verbose:       Print the FFmpeg command before running.

    Returns:
        Absolute path to the output file.
    """
    ffmpeg, ffprobe = get_ffmpeg_paths()

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    duration = get_duration(ffprobe, input_path)

    cmd = [
        ffmpeg, '-y',
        '-i', input_path,
        '-c:v', video_codec,
        '-crf', str(crf),
        '-preset', preset,
        '-pix_fmt', pix_fmt,   # convert 10-bit 4:2:2 (ProRes) → 8-bit 4:2:0 (universal)
        '-c:a', audio_codec,
        '-b:a', audio_bitrate,
        '-movflags', '+faststart',  # relocate moov atom for web streaming
        output_path,
    ]

    if verbose:
        print('FFmpeg command:')
        print(' '.join(f'"{c}"' if ' ' in c else c for c in cmd))
        print()

    t0 = time.time()
    try:
        proc = subprocess.Popen(
            cmd, stderr=subprocess.PIPE,
            universal_newlines=True, encoding='utf-8', errors='replace',
        )
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found — install it and add it to PATH")

    time_re = re.compile(r'time=(\d+:\d+:\d+\.\d+)')
    for line in proc.stderr:
        m = time_re.search(line)
        if m:
            current = parse_time(m.group(1))
            print_progress(current, duration, time.time() - t0)

    proc.wait()
    print()

    if proc.returncode != 0:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise RuntimeError("FFmpeg conversion failed — run with verbose=True for details")

    elapsed = time.time() - t0
    size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"Done!  {output_path}  ({size_mb:.1f} MB, {elapsed:.1f}s)")
    return os.path.abspath(output_path)


def main():
    parser = argparse.ArgumentParser(
        prog='convert_mov',
        description='Convert a MOV file to a standard H.264/AAC MP4',
    )
    parser.add_argument('input', help='Input .mov file')
    parser.add_argument('output', nargs='?', help='Output .mp4 file (default: <input>.mp4)')
    parser.add_argument('--crf', type=int, default=23,
                        help='Video quality (0-51, lower=better, default 23)')
    parser.add_argument('--preset', default='medium',
                        choices=['ultrafast','superfast','veryfast','faster','fast',
                                 'medium','slow','slower','veryslow'],
                        help='Encoding speed/compression tradeoff (default: medium)')
    parser.add_argument('--audio-bitrate', default='192k',
                        help='Audio bitrate (default: 192k)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Print FFmpeg command')
    args = parser.parse_args()

    output = args.output or os.path.splitext(args.input)[0] + '.mp4'

    print(f'[1/2] Input:  {args.input}')
    print(f'[2/2] Output: {output}')
    print()

    convert_mov_to_mp4(
        args.input, output,
        crf=args.crf,
        preset=args.preset,
        audio_bitrate=args.audio_bitrate,
        verbose=args.verbose,
    )


if __name__ == '__main__':
    main()
