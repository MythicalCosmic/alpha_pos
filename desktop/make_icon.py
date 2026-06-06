"""Generate the Alpha POS app icon (desktop/AlphaPOS.ico) — a rounded blue
gradient tile with a white 'α'. Build-time only; run once:

    .venv/Scripts/python.exe desktop/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / 'AlphaPOS.ico'
SIZE = 256


def _font(px):
    for name in ('segoeuib.ttf', 'arialbd.ttf', 'arial.ttf'):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def render(size=SIZE):
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Vertical blue gradient background.
    top, bot = (59, 130, 246), (29, 78, 216)
    for y in range(size):
        t = y / size
        d.line([(0, y), (size, y)],
               fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,))
    # Rounded-rect mask so corners are soft.
    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=255)
    img.putalpha(mask)
    # Glyph.
    d = ImageDraw.Draw(img)
    txt = 'α'
    f = _font(int(size * 0.62))
    box = d.textbbox((0, 0), txt, font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1]), txt,
           font=f, fill=(255, 255, 255, 255))
    return img


def main():
    base = render(SIZE)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base.save(OUT, format='ICO', sizes=sizes)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
