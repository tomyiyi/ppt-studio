#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配图客观验收（当无法肉眼看图时用数据代替眼睛）
==============================================

输出四个可判定的指标：
  1. 清晰度   —— 拉普拉斯方差。越大越锐利；< 40 基本是糊的
  2. 墨迹分布 —— 亮像素在 3x3 网格各格的占比，验证主体位置是否符合提示词
  3. 亮度     —— 均值 / P99，判断压暗是否到位
  4. 接缝     —— 复用 prepare_agnes_image.detect_seam

用法：
  python3 analyze_image.py <img> [<img> ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保在未显式激活 .venv 时也能从项目内 .venv 加载依赖
try:
    import numpy as np
    from PIL import Image
except ImportError:
    repo_root = Path(__file__).resolve().parent.parent
    for site_pkg in repo_root.glob(".venv/lib/python*/site-packages"):
        if site_pkg.is_dir() and str(site_pkg) not in sys.path:
            sys.path.insert(0, str(site_pkg))
    import numpy as np
    from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_agnes_image import detect_seam  # noqa: E402


def _lap_var(g: np.ndarray) -> float:
    k = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)
    h, w = g.shape
    if h < 3 or w < 3:
        return 0.0
    out = np.zeros((h - 2, w - 2), dtype=np.float64)
    for dy in range(3):
        for dx in range(3):
            if k[dy, dx]:
                out += k[dy, dx] * g[dy:dy + h - 2, dx:dx + w - 2]
    return float(out.var())


def laplacian_variance(im: Image.Image) -> float:
    """全图清晰度。注意：大面积平黑会稀释数值，需配合 subject_sharp 看。"""
    return _lap_var(np.asarray(im.convert("L"), dtype=np.float64))


def subject_sharp(im: Image.Image, pct: float = 99.0) -> float:
    """只算「主体区域」的清晰度 —— 取最亮 1% 像素的外接框再放大边距。

    全图拉普拉斯方差会被大片纯黑背景拉低（主体只占 10% 时，数值没有可比性），
    所以判断"线条是否锐利"必须框定到主体上再算。
    """
    g = np.asarray(im.convert("L"), dtype=np.float64)
    t = np.percentile(g, pct)
    ys, xs = np.where(g >= t)
    if ys.size < 50:
        return 0.0
    pad = 24
    y0, y1 = max(0, ys.min() - pad), min(g.shape[0], ys.max() + pad)
    x0, x1 = max(0, xs.min() - pad), min(g.shape[1], xs.max() + pad)
    return _lap_var(g[y0:y1, x0:x1])


def ink_map(im: Image.Image, thresh_pct: float = 97.0) -> np.ndarray:
    """亮像素在 3x3 网格中的占比矩阵（行=上中下，列=左中右）。"""
    g = np.asarray(im.convert("L"), dtype=np.float32)
    t = np.percentile(g, thresh_pct)
    mask = (g >= t).astype(np.float32)
    H, W = mask.shape
    m = np.zeros((3, 3), dtype=np.float32)
    for r in range(3):
        for c in range(3):
            blk = mask[r * H // 3:(r + 1) * H // 3, c * W // 3:(c + 1) * W // 3]
            m[r, c] = blk.mean()
    tot = m.sum() or 1.0
    return m / tot


def report(path: Path) -> dict:
    im = Image.open(path).convert("RGB")
    g = np.asarray(im.convert("L"), dtype=np.float32)
    m = ink_map(im)
    col = "左  中  右"
    return {
        "name": path.name,
        "size": f"{im.size[0]}x{im.size[1]}",
        "sharp": laplacian_variance(im),
        "ssharp": subject_sharp(im),
        "mean": float(g.mean()),
        "p99": float(np.percentile(g, 99)),
        "ink": m,
        "seam": detect_seam(im),
        "colhead": col,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python3 analyze_image.py <img> [<img> ...]")
        return 2
    print(f"{'文件':<22}{'尺寸':>10}{'全图锐':>8}{'主体锐':>8}{'均亮':>7}{'P99':>7}  "
          f"主体分布(上/中/下 × 左/中/右, %)      接缝")
    print("-" * 128)
    for p in sys.argv[1:]:
        r = report(Path(p))
        rows = ["  ".join(f"{r['ink'][i][j]*100:5.1f}" for j in range(3)) for i in range(3)]
        print(f"{r['name']:<22}{r['size']:>10}{r['sharp']:>8.1f}{r['ssharp']:>8.1f}"
              f"{r['mean']:>7.1f}{r['p99']:>7.1f}  "
              f"{rows[0]}  |  {rows[1]}  |  {rows[2]}   {r['seam']}")
    print("\n判读：")
    print("  主体锐 —— 只框定最亮 1% 像素区域算的拉普拉斯方差，判断线条是否锐利；<80 判糊")
    print("  全图锐 —— 含大片纯黑，会被稀释，仅作参考")
    print("  主体分布 —— 每格 11% 为均匀分布基线；最高格 >=25% 才有明确主体，<15% 视为没画出图形")
    print("  P99 —— 亮部强度，<40 说明整体过暗没高光")
    print("  接缝 —— None 为无；有数值交由 prepare_agnes_image.py --seam 修")
    return 0


if __name__ == "__main__":
    sys.exit(main())
