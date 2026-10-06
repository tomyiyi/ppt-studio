#!/usr/bin/env python3
"""
boost_ink.py — 暗底线性图专用提亮：黑点保持 + 高光增益

为什么不用普通 brightness（乘法）：
  普通乘法把 #08090C 的底色一起提亮，黑底变灰底，图会"发雾"。
  正确做法是先减掉黑点、再增益、再把黑点加回去：
      out = black + (in - black) * gain
  这样 in == black 的像素（背景）完全不动，笔画被单独拉亮。

用法：
  python3 boost_ink.py <images_dir> [--target 230] [--black-pct 5] [--apply]

默认只预演（dry-run），加 --apply 才写盘（写盘前自动备份 _pre_<name>.png）。
"""
import argparse
import glob
import os
import shutil
import sys

import numpy as np
from PIL import Image

TARGET = 230          # 目标：p99.9 提亮到这个亮度
BLACK_PCT = 5.0       # 黑点 = 全图第 N 百分位（暗底图里这就是背景色）
TOP_PCT = 99.9        # 用于自适应求 gain 的高光参考点


def metrics(a):
    return dict(
        max=float(a.max()),
        p999=float(np.percentile(a, TOP_PCT)),
        p99=float(np.percentile(a, 99)),
        ink60=100 * float(np.mean(a > 60)),
        gt150=100 * float(np.mean(a > 150)),
        gt200=100 * float(np.mean(a > 200)),
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="暗底线性图专用提亮：黑点保持 + 高光增益 "
                    "(out = black + (in - black) * gain)，黑底背景完全不动。",
        epilog="默认只预演（dry-run），加 --apply 才写盘（写盘前自动备份 _pre_<name>.png）。",
    )
    p.add_argument("target_dir", metavar="images_dir",
                   help="图片目录（*.png），或直接传单个 PNG 文件")
    p.add_argument("--target", type=float, default=TARGET,
                   help=f"目标：把 p99.9 提亮到这个亮度（默认 {TARGET}）")
    p.add_argument("--black-pct", type=float, default=BLACK_PCT,
                   help=f"黑点 = 全图第 N 百分位，暗底图里即背景色（默认 {BLACK_PCT}）")
    p.add_argument("--apply", action="store_true",
                   help="实际写盘；不加则只预演打印增益表")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    target = args.target
    d = args.target_dir

    if os.path.isfile(d):          # 也允许直接传单个文件
        files = [d]
    else:
        files = [p for p in sorted(glob.glob(os.path.join(d, "*.png")))
                 if not os.path.basename(p).startswith(("_pre_", "_raw_"))]
    if not files:
        print(f"没有可处理的 PNG：{d}", file=sys.stderr)
        raise SystemExit(1)

    print(f"{'file':16} {'gain':>5} | {'max':>4}→{'max':>4} {'p99.9':>5}→{'p99.9':>5} "
          f"{'>150%':>6}→{'>150%':>6} {'>200%':>6}→{'>200%':>6}")
    print("-" * 88)

    for p in files:
        im = Image.open(p)
        mode = im.mode
        a = np.asarray(im.convert("RGB"), dtype=np.float64)
        black = float(np.percentile(a, args.black_pct))
        hi = float(np.percentile(a, TOP_PCT))
        if hi <= black + 1:
            print(f"{os.path.basename(p):16} 跳过（无高光）")
            continue
        gain = (target - black) / (hi - black)
        before = metrics(np.asarray(im.convert("L"), dtype=np.float64))

        out = black + (a - black) * gain
        out = np.clip(out, 0, 255).astype(np.uint8)
        new = Image.fromarray(out, "RGB").convert(mode)
        after = metrics(np.asarray(new.convert("L"), dtype=np.float64))

        print(f"{os.path.basename(p):16} {gain:5.2f} | "
              f"{before['max']:4.0f}→{after['max']:4.0f} "
              f"{before['p999']:5.0f}→{after['p999']:5.0f} "
              f"{before['gt150']:6.2f}→{after['gt150']:6.2f} "
              f"{before['gt200']:6.2f}→{after['gt200']:6.2f}")

        if args.apply:
            bak = os.path.join(os.path.dirname(p) or ".", "_pre_" + os.path.basename(p))
            if not os.path.exists(bak):
                shutil.copy2(p, bak)
            new.save(p)

    print("-" * 88)
    print("已写盘 ✅" if args.apply else "预演模式（未写盘），加 --apply 执行")


if __name__ == "__main__":
    main()
