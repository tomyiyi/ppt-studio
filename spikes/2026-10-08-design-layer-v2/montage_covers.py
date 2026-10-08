#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拼对照图：montage_covers.py <out.png> "标签=图片路径" ..."""
import sys
from PIL import Image, ImageDraw, ImageFont

OUT = sys.argv[1]
CELLS = [a.split("=", 1) for a in sys.argv[2:]]
W, H, LAB = 768, 432, 34
COLS = 3
ROWS = (len(CELLS) + COLS - 1) // COLS
sheet = Image.new("RGB", (COLS * W, ROWS * (H + LAB)), "#FFFFFF")
d = ImageDraw.Draw(sheet)
try:
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
except Exception:
    font = ImageFont.load_default()
for i, (label, path) in enumerate(CELLS):
    im = Image.open(path).convert("RGB")
    im.thumbnail((W, H))
    x, y = (i % COLS) * W, (i // COLS) * (H + LAB)
    sheet.paste(im, (x + (W - im.width) // 2, y + (H - im.height) // 2))
    d.rectangle([x, y + H, x + W, y + H + LAB], fill="#111111")
    d.text((x + 10, y + H + 6), label, fill="#FFFFFF", font=font)
sheet.save(OUT)
print("wrote", OUT, sheet.size, "cells=", len(CELLS))
