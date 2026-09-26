#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crop_panel.py — 按"主体包围盒"裁切配图，让主体填满面板

背景：Agnes 出的是 16:9 整幅构图，主体只占一小块。直接整幅塞进
      右半面板（1.51:1）时，主体在面板里只有 3% 的墨量，看着是空的。
      正确做法是先算出亮像素的包围盒，按面板比例裁一块"刚好包住主体"
      的图，SVG 再把这块图铺满面板——主体视觉占比立刻翻几倍。

用法：
  python3 crop_panel.py <src.png> [--aspect 580:385] [--pad 1.12] [--out x.png] [--apply]
默认预演，加 --apply 写盘。
"""
from __future__ import annotations

import argparse
import os
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

INK_T = 80          # max 通道 > 80 视为"有笔画"
TRIM = 0.5          # 坐标取 0.5%~99.5% 分位，丢掉零星噪点


def parse_aspect(aspect_val: str | float) -> float:
    """解析宽高比字符串（支持 '580:385', '16:9', '16/9' 或浮点数字符串/数值）。"""
    if isinstance(aspect_val, (int, float)):
        val = float(aspect_val)
        if val <= 0:
            raise ValueError(f"宽高比必须大于 0: {aspect_val}")
        return val
    s = str(aspect_val).strip()
    if not s:
        raise ValueError("宽高比不能为空")
    if ":" in s:
        parts = s.split(":")
    elif "/" in s:
        parts = s.split("/")
    else:
        val = float(s)
        if val <= 0:
            raise ValueError(f"宽高比必须大于 0: {aspect_val}")
        return val

    if len(parts) != 2:
        raise ValueError(f"无效的宽高比格式: {aspect_val}")
    w, h = float(parts[0]), float(parts[1])
    if w <= 0 or h <= 0:
        raise ValueError(f"宽高比数值必须大于 0: {aspect_val}")
    return w / h


def bbox_of(a: np.ndarray, t: int = INK_T) -> tuple[float, float, float, float] | None:
    """计算图像数组中的主体包围盒 (x0, y0, x1, y1)。如果亮像素不足则返回 None。"""
    if a.ndim == 3:
        mx = a.max(axis=2)
    else:
        mx = a
    ys, xs = np.where(mx > t)
    if len(xs) < 50:
        return None
    y0, y1 = np.percentile(ys, [TRIM, 100 - TRIM])
    x0, x1 = np.percentile(xs, [TRIM, 100 - TRIM])
    return float(x0), float(y0), float(x1), float(y1)


def cover(a: np.ndarray, box: tuple[float, float, float, float], t: int = INK_T) -> float:
    """计算矩形区域内亮像素（墨量）百分比。"""
    x, y, w, h = [int(round(v)) for v in box]
    if a.ndim == 3:
        c = a[y:y + h, x:x + w].max(axis=2)
    else:
        c = a[y:y + h, x:x + w]
    if c.size == 0:
        return 0.0
    return 100.0 * float(np.mean(c > t))


def calculate_crop(
    w: int,
    h: int,
    bbox: tuple[float, float, float, float],
    tgt_aspect: float,
    pad: float = 1.12,
) -> tuple[float, float, float, float]:
    """按目标比例与安全边距扩张主体包围盒，并严格限制在画幅内，保持比例不失真。"""
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    bw, bh = max(1.0, (x1 - x0) * pad), max(1.0, (y1 - y0) * pad)

    # 按面板比例扩张到"刚好包住主体"
    if bw / bh > tgt_aspect:
        bh = bw / tgt_aspect
    else:
        bw = bh * tgt_aspect

    # 若扩张后尺寸超出原画幅限制，等比缩小以维持目标比例
    if bw > w:
        scale = w / bw
        bw *= scale
        bh *= scale
    if bh > h:
        scale = h / bh
        bw *= scale
        bh *= scale

    # 夹到画布内（越界则平移居中限制，不破坏画幅与比例）
    left = cx - bw / 2.0
    top = cy - bh / 2.0
    left = max(0.0, min(left, float(w) - bw))
    top = max(0.0, min(top, float(h) - bh))

    return left, top, bw, bh


def crop_image(
    src_path: str | Path,
    out_path: str | Path | None = None,
    aspect: str | float = "580:385",
    pad: float = 1.12,
    apply: bool = False,
) -> dict:
    """执行裁切计算与可选落盘，返回结果指标字典。"""
    src_p = Path(src_path)
    if not src_p.is_file():
        raise FileNotFoundError(f"源图片文件不存在: {src_path}")

    tgt_aspect = parse_aspect(aspect)
    if pad <= 0:
        raise ValueError(f"边距系数 pad 必须大于 0: {pad}")

    im = Image.open(src_p).convert("RGB")
    a = np.asarray(im, dtype=np.float64)
    h, w = a.shape[:2]

    bb = bbox_of(a)
    if bb is None:
        raise ValueError(f"{src_path}: 没找到主体（亮像素太少）")

    x0, y0, x1, y1 = bb
    left, top, bw, bh = calculate_crop(w, h, bb, tgt_aspect, pad)

    before = cover(a, (0, 0, w, h))
    after = cover(a, (left, top, bw, bh))

    final_out = Path(out_path) if out_path else src_p.with_name(f"{src_p.stem}_panel.png")

    if apply:
        final_out.parent.mkdir(parents=True, exist_ok=True)
        ix, iy, iw, ih = [int(round(v)) for v in (left, top, bw, bh)]
        cropped = Image.fromarray(a[iy:iy + ih, ix:ix + iw].astype(np.uint8))
        cropped.save(final_out)

    return {
        "src": str(src_p),
        "name": src_p.name,
        "width": w,
        "height": h,
        "bbox": (x0, y0, x1, y1),
        "crop_box": (left, top, bw, bh),
        "target_aspect": tgt_aspect,
        "actual_aspect": bw / bh if bh > 0 else 0.0,
        "before_cover": before,
        "after_cover": after,
        "out": str(final_out),
        "applied": apply,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="按'主体包围盒'裁切配图，让主体填满面板"
    )
    parser.add_argument("src", help="源图片路径 (PNG/JPEG 等)")
    parser.add_argument(
        "--aspect",
        default="580:385",
        help="目标宽高比，如 580:385, 16:9 或 1.506 (默认: 580:385)",
    )
    parser.add_argument(
        "--pad",
        type=float,
        default=1.12,
        help="主体包围盒向外扩张系数 (默认: 1.12)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="输出图片路径 (默认: <src_stem>_panel.png)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正写盘保存裁切后图片（默认仅预演）",
    )

    args = parser.parse_args(argv)

    try:
        res = crop_image(
            src_path=args.src,
            out_path=args.out,
            aspect=args.aspect,
            pad=args.pad,
            apply=args.apply,
        )
    except FileNotFoundError as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[!] 裁切失败: {e}", file=sys.stderr)
        return 1

    x0, y0, x1, y1 = res["bbox"]
    left, top, bw, bh = res["crop_box"]
    tgt = res["target_aspect"]
    actual = res["actual_aspect"]
    before = res["before_cover"]
    after = res["after_cover"]

    print(f"{res['name']}  {res['width']}x{res['height']}")
    print(f"  主体 bbox  x {x0:.0f}-{x1:.0f} ({x1-x0:.0f}px)  y {y0:.0f}-{y1:.0f} ({y1-y0:.0f}px)")
    print(f"  裁切框     x {left:.0f} y {top:.0f}  {bw:.0f}x{bh:.0f}  (比例 {actual:.3f} vs 目标 {tgt:.3f})")
    ratio_multiplier = after / max(before, 1e-6)
    print(f"  主体占画面  {before:.2f}%  →  {after:.2f}%   ({ratio_multiplier:.1f}×)")

    if res["applied"]:
        print(f"  已保存 {res['out']}")
    else:
        print("  [提示] 当前为预演模式（未写盘），加 --apply 执行写盘")

    return 0


if __name__ == "__main__":
    sys.exit(main())
