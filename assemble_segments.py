import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile


def get_ffmpeg():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
        ffmpeg = os.path.join(base, 'ffmpeg.exe')
        if os.path.exists(ffmpeg):
            return ffmpeg
    return 'ffmpeg'


def create_silence_wav(path, duration, sample_rate=44100):
    num_samples = int(sample_rate * duration)
    data_size   = num_samples * 2
    with open(path, 'wb') as f:
        f.write(b'RIFF')
        f.write(struct.pack('<I', 36 + data_size))
        f.write(b'WAVEfmt ')
        f.write(struct.pack('<IHHIIHH', 16, 1, 1, sample_rate,
                            sample_rate * 2, 2, 16))
        f.write(b'data')
        f.write(struct.pack('<I', data_size))
        f.write(b'\x00' * data_size)


def mp3_to_wav(mp3_path, wav_path, ffmpeg, sample_rate=44100):
    cmd = [ffmpeg, '-y', '-i', mp3_path,
           '-af', 'dynaudnorm',
           '-ar', str(sample_rate), '-ac', '1',
           '-sample_fmt', 's16', wav_path]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-300:])


def main():
    parser = argparse.ArgumentParser(
        prog='assemble_segments',
        description='将 segments 目录中的分块 MP3 合成为一个文件，块间加静音'
    )
    parser.add_argument('segments_dir',      help='分块 MP3 目录（含 segment_XXXX.mp3）')
    parser.add_argument('-o', '--output',    default=None,
                        help='输出 MP3 路径（默认：目录名.mp3）')
    parser.add_argument('--silence',         type=float, default=1.0,
                        help='块间静音秒数（默认: 1.0，0=不加）')
    parser.add_argument('--sample-rate',     type=int, default=44100)
    parser.add_argument('-v', '--verbose',   action='store_true')
    args = parser.parse_args()

    if not os.path.isdir(args.segments_dir):
        print(f'错误: 目录不存在: {args.segments_dir}')
        sys.exit(1)

    # find and sort segment files
    files = sorted(
        [f for f in os.listdir(args.segments_dir)
         if re.match(r'^segment_\d+\.mp3$', f)],
        key=lambda f: int(re.search(r'\d+', f).group())
    )
    if not files:
        print('错误: 目录中未找到 segment_XXXX.mp3 文件')
        sys.exit(1)

    output = args.output or os.path.basename(args.segments_dir.rstrip('/\\')) + '.mp3'
    ffmpeg = get_ffmpeg()

    print(f'找到 {len(files)} 个分块，静音间隔: {args.silence}s')

    tmp_dir = tempfile.mkdtemp(prefix='assemble_')
    try:
        concat_list = []
        for i, fname in enumerate(files):
            mp3_path = os.path.join(args.segments_dir, fname)
            wav_path = os.path.join(tmp_dir, f'{i:04d}.wav')
            print(f'  转换 {fname}...', end='\r')
            try:
                mp3_to_wav(mp3_path, wav_path, ffmpeg, args.sample_rate)
            except RuntimeError as e:
                print(f'\n  ⚠  {fname} 转换失败，跳过: {e}')
                continue
            if concat_list and args.silence > 0:
                sil_path = os.path.join(tmp_dir, f'sil_{i:04d}.wav')
                create_silence_wav(sil_path, args.silence, args.sample_rate)
                concat_list.append(sil_path)
            concat_list.append(wav_path)

        if not concat_list:
            print('错误: 没有可用的音频片段')
            sys.exit(1)

        print(f'  合并 {len(files)} 块 → {output} ...')
        concat_txt = os.path.join(tmp_dir, 'list.txt')
        with open(concat_txt, 'w', encoding='utf-8') as f:
            for p in concat_list:
                f.write(f"file '{p.replace(chr(92), '/')}'\n")

        cmd = [ffmpeg, '-y', '-f', 'concat', '-safe', '0',
               '-i', concat_txt,
               '-c:a', 'libmp3lame', '-b:a', '192k', output]
        if args.verbose:
            print(' '.join(f'"{c}"' if ' ' in c else c for c in cmd))

        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        if r.returncode != 0:
            print(f'错误: FFmpeg 失败:\n{r.stderr[-500:]}')
            sys.exit(1)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    size_mb = os.path.getsize(output) / 1024 / 1024
    print(f'\n完成！输出文件: {output}  ({size_mb:.1f} MB)')


if __name__ == '__main__':
    main()
