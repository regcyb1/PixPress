"""Draw the PixPress app icon with Pillow and save PNG / ICO / ICNS versions.

Usage: python assets/make_icon.py [output_dir]
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024


def draw_icon(size: int = SIZE) -> Image.Image:
    s = size / 1024
    # diagonal indigo → purple gradient
    grad = Image.new("RGB", (size, size))
    top, bottom = (102, 126, 234), (118, 75, 162)
    px = grad.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(top, bottom))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40 * s, 40 * s, 984 * s, 984 * s], radius=220 * s, fill=255)
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    icon.paste(grad, mask=mask)

    d = ImageDraw.Draw(icon)
    # back sheet (a page / PDF)
    d.rounded_rectangle([330 * s, 200 * s, 790 * s, 760 * s], radius=48 * s, fill=(206, 212, 246, 255))
    # front photo card
    d.rounded_rectangle([230 * s, 300 * s, 690 * s, 840 * s], radius=48 * s, fill=(255, 255, 255, 255))
    d.rounded_rectangle([280 * s, 350 * s, 640 * s, 700 * s], radius=26 * s, fill=(232, 236, 252, 255))
    # sun + mountains inside the photo
    d.ellipse([530 * s, 390 * s, 600 * s, 460 * s], fill=(255, 196, 77, 255))
    d.polygon([(280 * s, 700 * s), (400 * s, 520 * s), (500 * s, 700 * s)], fill=(102, 126, 234, 255))
    d.polygon([(420 * s, 700 * s), (540 * s, 560 * s), (640 * s, 700 * s)], fill=(118, 75, 162, 255))
    # caption lines under the photo
    d.rounded_rectangle([280 * s, 740 * s, 560 * s, 770 * s], radius=15 * s, fill=(200, 205, 230, 255))
    return icon


def main(out_dir="build/icon"):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    icon = draw_icon()
    icon.save(out / "icon.png")
    icon.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.save(out / "icon.icns")
    return out


if __name__ == "__main__":
    print(main(*sys.argv[1:]))
