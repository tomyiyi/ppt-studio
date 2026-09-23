#!/usr/bin/env python3
"""
crop_panel.py — 按"主体包围盒"裁切配图，让主体填满面板

背景：Agnes 出的是 16:9 整幅构图，主体只占一小块。直接整幅塞进
      右半面板（1.51:1）时，主体在面板里只有 3% 的墨量，看着是空的。
      正确做法是先算出亮像素的包围盒，按面板比例裁一块"刚好包住主体"
      的图，SVG 再把这块图铺满面板——主体视觉占比立刻翻几倍。

用法：
  python3 crop_panel.py <src.png> --aspect 580:385 [--pad 1.12] [--out x.png] [--apply]
默认预演，加 --apply 写盘。
"""
import os
import sys

import numpy as np
from PIL import Image

INK_T = 80          # max 通道 > 80 视为"有笔画"
TRIM = 0.5          # 坐标取 0.5%~99.5% 分位，丢掉零星噪点


def bbox_of(a, t=INK_T):
    mx = a.max(axis=2)
    ys, xs = np.where(mx > t)
    if len(xs) < 50:
        return None
    y0, y1 = np.percentile(ys, [TRIM, 100 - TRIM])
    x0, x1 = np.percentile(xs, [TRIM, 100 - TRIM])
    return float(x0), float(y0), float(x1), float(y1)


def cover(a, box):
    x, y, w, h = [int(v) for v in box]
    c = a[y:y + h, x:x + w].max(axis=2)
    return 100 * float(np.mean(c > INK_T))


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    args = [a for a in args if a != "--apply"]

    src = next((a for a in args if not a.startswith("--")), None)
    if not src:
        print(__doc__)
        sys.exit(1)

    def opt(name, default):
        for a in args:
            if a.startswith(f"--{name}="):
                return a.split("=", 1)[1]
        return default

    aw, ah = [float(v) for v in opt("aspect", "580:385").split(":")]
    pad = float(opt("pad", "1.12"))
    out = opt("out", None) or os.path.splitext(src)[0] + "_panel.png"

    im = Image.open(src).convert("RGB")
    a = np.asarray(im, dtype=np.float64)
    H, W = a.shape[:2]

    bb = bbox_of(a)
    if bb is None:
        print(f"{src}: 没找到主体（亮像素太少）")
        sys.exit(1)
    x0, y0, x1, y1 = bb
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    bw, bh = (x1 - x0) * pad, (y1 - y0) * pad

    # 按面板比例扩张到"刚好包住主体"
    tgt = aw / ah
    if bw / bh > tgt:
        bh = bw / tgt
    else:
        bw = bh * tgt

    # 夹到画布内（越界则整体平移，不缩放）
    left = cx - bw / 2
    top = cy - bh / 2
    left = min(max(0.0, left), max(0.0, W - bw))
    top = min(max(0.0, top), max(0.0, H - bh))
    bw = min(bw, W)
    bh = min(bh, H)
    box = (left, top, bw, bh)

    before = cover(a, (0, 0, W, H))
    after = cover(a, box)
    print(f"{os.path.basename(src)}  {W}x{H}")
    print(f"  主体 bbox  x {x0:.0f}-{x1:.0f} ({x1-x0:.0f}px)  y {y0:.0f}-{y1:.0f} ({y1-y0:.0f}px)")
    print(f"  裁切框     x {left:.0f} y {top:.0f}  {bw:.0f}x{bh:.0f}  (比例 {bw/bh:.3f} vs 目标 {tgt:.3f})")
    print(f"  主体占画面  {before:.2f}%  →  {after:.2f}%   ({after/max(before,1e-6):.1f}×)")

    if apply:
        x, y, w, h = [int(round(v)) for v in (left, top, bw, bh)]
        Image.fromarray(a[y:y + h, x:x + w].astype(np.uint8)).save(out)
        print(f"  已保存 {out}")


if __name__ == "__main__":
    main()
