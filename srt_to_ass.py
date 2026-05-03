import argparse
import os
import re
import sys


def parse_srt_time(s):
    m = re.match(r'(\d+):(\d+):(\d+)[,.](\d+)', s.strip())
    if not m:
        raise ValueError(f"Invalid SRT timestamp: '{s}'")
    h, mm, ss, frac = m.groups()
    return int(h) * 3600 + int(mm) * 60 + int(ss) + int(frac) / (10 ** len(frac))


def seconds_to_ass_time(sec):
    h  = int(sec // 3600)
    m  = int((sec % 3600) // 60)
    s  = int(sec % 60)
    cs = int(round((sec % 1) * 100))
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'


def srt_text_to_ass(text):
    """Convert inline SRT HTML tags to ASS override tags."""
    text = re.sub(r'<b>(.*?)</b>',   r'{\\b1}\1{\\b0}', text, flags=re.IGNORECASE)
    text = re.sub(r'<i>(.*?)</i>',   r'{\\i1}\1{\\i0}', text, flags=re.IGNORECASE)
    text = re.sub(r'<u>(.*?)</u>',   r'{\\u1}\1{\\u0}', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)   # strip remaining HTML tags
    return text


def read_srt(path):
    for enc in ('utf-8-sig', 'utf-8', 'gbk', 'utf-16', 'latin-1'):
        try:
            with open(path, encoding=enc) as f:
                content = f.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    entries = []
    for block in re.split(r'\n\s*\n', content.strip()):
        lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
        for i, line in enumerate(lines):
            m = re.match(r'(.+?)\s*-->\s*(.+)', line)
            if m:
                try:
                    start = parse_srt_time(m.group(1))
                    end   = parse_srt_time(m.group(2))
                    text  = r'\N'.join(srt_text_to_ass(l) for l in lines[i+1:] if l)
                    if text:
                        entries.append((start, end, text))
                except ValueError:
                    pass
                break
    return entries


def hex_to_ass_color(hex_color):
    """#RRGGBB or RRGGBB → ASS &H00BBGGRR"""
    h = hex_color.lstrip('#')
    if len(h) != 6:
        return '&H00404040'
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f'&H00{b:02X}{g:02X}{r:02X}'


def calc_margins(alignment, box_x, box_y, box_w, box_h,
                 play_res_x, play_res_y, padding):
    ml = box_x + padding
    mr = (play_res_x - box_x - box_w) + padding
    if alignment in (1, 2, 3):    # bottom row
        mv = (play_res_y - box_y - box_h) + padding
    elif alignment in (7, 8, 9):  # top row
        mv = box_y + padding
    else:                          # middle row
        mv = box_y + padding
    return ml, mr, mv


def build_ass(entries, play_res_x, play_res_y,
              box_x, box_y, box_w, box_h,
              font_name, font_size, color_hex,
              bold, outline_color_hex, outline_width,
              alignment, padding):

    ml, mr, mv = calc_margins(alignment, box_x, box_y, box_w, box_h,
                               play_res_x, play_res_y, padding)
    primary  = hex_to_ass_color(color_hex)
    outline  = hex_to_ass_color(outline_color_hex)
    bold_val = -1 if bold else 0

    header = (
        '[Script Info]\n'
        'ScriptType: v4.00+\n'
        f'PlayResX: {play_res_x}\n'
        f'PlayResY: {play_res_y}\n'
        'ScaledBorderAndShadow: yes\n'
        'YCbCr Matrix: None\n'
        '\n'
        '[V4+ Styles]\n'
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, '
        'OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, '
        'ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, '
        'Alignment, MarginL, MarginR, MarginV, Encoding\n'
        f'Style: Default,{font_name},{font_size},'
        f'{primary},&H000000FF,{outline},&H00000000,'
        f'{bold_val},0,0,0,100,100,0,0,1,{outline_width:.1f},0,'
        f'{alignment},{ml},{mr},{mv},1\n'
        '\n'
        '[Events]\n'
        'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text'
    )

    lines = [header]
    for start, end, text in entries:
        lines.append(
            f'Dialogue: 0,{seconds_to_ass_time(start)},'
            f'{seconds_to_ass_time(end)},Default,,0,0,0,,{text}'
        )
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        prog='srt_to_ass',
        description='将 SRT 转换为 ASS 格式，精确定位字幕框'
    )
    parser.add_argument('input',                help='输入 SRT 文件')
    parser.add_argument('--res',   default='1280x960',
                        help='视频分辨率 WxH（默认: 1280x960）')
    parser.add_argument('--box',   default=None,
                        help='字幕框 x,y,w,h（例: 0,700,1280,200）')
    parser.add_argument('--font-name',    default='Arial')
    parser.add_argument('--font-size',    type=int,   default=20)
    parser.add_argument('--color',        default='333333',
                        help='字体颜色 RRGGBB（默认: 333333 深灰）')
    parser.add_argument('--bold',         action='store_true')
    parser.add_argument('--outline-color',  default='FFFFFF',
                        help='描边颜色 RRGGBB（默认: FFFFFF 白色）')
    parser.add_argument('--outline-width',  type=float, default=1.5)
    parser.add_argument('--alignment',    type=int,   default=2,
                        choices=list(range(1, 10)),
                        help='对齐方式 1-9，ASS 标准（默认: 2 底部居中）')
    parser.add_argument('--padding',      type=int,   default=10,
                        help='框内边距 px（默认: 10）')
    parser.add_argument('-o', '--output', default=None)
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f'错误: 文件不存在: {args.input}')
        sys.exit(1)

    try:
        w_str, h_str = args.res.lower().split('x')
        play_res_x, play_res_y = int(w_str), int(h_str)
    except (ValueError, AttributeError):
        print(f'错误: 无效分辨率格式: {args.res}，应为 WxH')
        sys.exit(1)

    if args.box:
        try:
            box_x, box_y, box_w, box_h = map(int, args.box.split(','))
        except ValueError:
            print('错误: --box 格式应为 x,y,w,h（整数，逗号分隔）')
            sys.exit(1)
    else:
        box_x, box_w = 0, play_res_x
        box_y = int(play_res_y * 0.73)
        box_h = int(play_res_y * 0.21)

    output = args.output or os.path.splitext(args.input)[0] + '.ass'

    entries = read_srt(args.input)
    if not entries:
        print('错误: 未找到有效字幕')
        sys.exit(1)

    ml, mr, mv = calc_margins(args.alignment, box_x, box_y, box_w, box_h,
                               play_res_x, play_res_y, args.padding)

    ass = build_ass(entries, play_res_x, play_res_y,
                    box_x, box_y, box_w, box_h,
                    args.font_name, args.font_size, args.color,
                    args.bold, args.outline_color, args.outline_width,
                    args.alignment, args.padding)

    with open(output, 'w', encoding='utf-8-sig') as f:
        f.write(ass)

    print(f'转换完成：{len(entries)} 条字幕 → {output}')
    print(f'  视频: {play_res_x}x{play_res_y}  字幕框: x={box_x} y={box_y} w={box_w} h={box_h}')
    print(f'  边距: L={ml} R={mr} V={mv}  字体: {args.font_name} {args.font_size}px')
    print()
    print('烧录到视频:')
    print(f'  ffmpeg -i video.mp4 -vf "ass={output}" -c:a copy output.mp4')
    print()
    print('配合 drawbox 遮罩一起用:')
    print(f'  ffmpeg -i video.mp4 -vf "drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color=white@0.95:t=fill,ass={output}" -c:a copy output.mp4')


if __name__ == '__main__':
    main()
