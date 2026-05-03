import argparse
import os
import re
import sys


def has_chinese(text):
    return bool(re.search(r'[一-鿿㐀-䶿豈-﫿　-〿]', text))


def detect_and_read(path):
    for enc in ('utf-8-sig', 'gbk', 'gb2312', 'utf-16', 'latin-1'):
        try:
            with open(path, encoding=enc) as f:
                content = f.read()
            return content, enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    with open(path, encoding='latin-1') as f:
        return f.read(), 'latin-1'


def srt_to_txt(srt_path, output_path, throat_interval=30):
    content, enc = detect_and_read(srt_path)
    print(f'  检测编码: {enc}')

    content = re.sub(r'\r\n', '\n', content)

    lines_out = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r'^\d+$', line):
            continue
        if '-->' in line:
            continue
        if has_chinese(line):
            continue
        line = re.sub(r'<[^>]+>', '', line).strip()
        if not line:
            continue
        # insert [clears throat] before every Nth line (1-indexed)
        if throat_interval > 0 and len(lines_out) % throat_interval == 0 and len(lines_out) > 0:
            lines_out.append('[clears throat]')
        lines_out.append(line)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines_out) + '\n')

    throat_count = sum(1 for l in lines_out if l == '[clears throat]')
    return len(lines_out) - throat_count, throat_count


def main():
    parser = argparse.ArgumentParser(
        prog='srt_to_txt',
        description='从 SRT 文件中提取英文字幕，去除中文、时间轴、序号，输出 TXT'
    )
    parser.add_argument('input',                    help='输入 SRT 文件')
    parser.add_argument('-o', '--output',           default=None,
                        help='输出 TXT 文件路径（默认：同名 .txt）')
    parser.add_argument('--throat-interval',        type=int, default=30,
                        help='每隔几行插入 [clears throat]，0=关闭（默认: 30）')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f'错误: 文件不存在: {args.input}')
        sys.exit(1)

    output = args.output or os.path.splitext(args.input)[0] + '.txt'
    count, throats = srt_to_txt(args.input, output, args.throat_interval)
    print(f'完成！提取 {count} 行英文字幕，插入 {throats} 个 [clears throat] → {output}')


if __name__ == '__main__':
    main()
