#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
boost_ink.py — 暗底线性图专用提亮：黑点保持 + 高光增益

为什么不用普通 brightness（乘法）：
  普通乘法把 #08090C 的底色一起提亮，黑底变灰底，图会"发雾"。
  正确做法是先减掉黑点、再增益、再把黑点加回去：
      out = black + (in - black) * gain
  这样 in == black 的像素（背景）完全不动，笔画被单独拉亮。

用法：
  python3 boost_ink.py [path] [--target 230] [--black-pct 5.0] [--top-pct 99.9] [--apply]

默认只预演（dry-run），加 --apply 才写盘（写盘前自动备份 _pre_<name>.png）。
"""
from __future__ import annotations

import argparse
import os
import shutil
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

TARGET = 230.0        # 目标：p99.9 提亮到这个亮度
BLACK_PCT = 5.0       # 黑点 = 全图第 N 百分位（暗底图里这就是背景色）
TOP_PCT = 99.9        # 用于自适应求 gain 的高光参考点


def metrics(a: np.ndarray, top_pct: float = TOP_PCT) -> dict[str, float]:
    """计算图像阵列的关键亮度与墨量指标。"""
    if a.size == 0:
        return dict(max=0.0, p999=0.0, p99=0.0, ink60=0.0, gt150=0.0, gt200=0.0)
    return dict(
        max=float(a.max()),
        p999=float(np.percentile(a, top_pct)),
        p99=float(np.percentile(a, 99.0)),
        ink60=100.0 * float(np.mean(a > 60.0)),
        gt150=100.0 * float(np.mean(a > 150.0)),
        gt200=100.0 * float(np.mean(a > 200.0)),
    )


def boost_image(
    im: Image.Image,
    target: float = TARGET,
    black_pct: float = BLACK_PCT,
    top_pct: float = TOP_PCT,
) -> tuple[Image.Image, float, dict[str, float], dict[str, float], str | None]:
    """对单张 PIL Image 进行黑点保持增益提亮，返回 (提亮图像, 增益系数, 提亮前指标, 提亮后指标, 跳过原因)。"""
    if not (0.0 < target <= 255.0):
        raise ValueError(f"目标亮度 target 必须在 (0, 255] 范围内: {target}")
    if not (0.0 <= black_pct < top_pct):
        raise ValueError(f"黑点百分位数 black_pct 必须满足 0 <= black_pct < top_pct: {black_pct}")
    if not (top_pct <= 100.0):
        raise ValueError(f"高光参考百分位数 top_pct 必须 <= 100: {top_pct}")

    mode = im.mode
    rgb_im = im.convert("RGB")
    a = np.asarray(rgb_im, dtype=np.float64)

    before_gray = np.asarray(im.convert("L"), dtype=np.float64)
    before_metrics = metrics(before_gray, top_pct=top_pct)

    black = float(np.percentile(a, black_pct))
    hi = float(np.percentile(a, top_pct))

    if hi <= black + 1.0:
        return im.copy(), 1.0, before_metrics, before_metrics.copy(), "无高光"
    if target <= black:
        return im.copy(), 1.0, before_metrics, before_metrics.copy(), "目标低于底色"

    gain = (target - black) / (hi - black)
    out = black + (a - black) * gain
    out = np.clip(out, 0, 255).astype(np.uint8)

    if mode == "RGBA" and "A" in im.getbands():
        alpha = im.getchannel("A")
        boosted = Image.fromarray(out, "RGB")
        boosted.putalpha(alpha)
    elif mode == "LA" and "A" in im.getbands():
        alpha = im.getchannel("A")
        boosted = Image.fromarray(out, "RGB").convert("L")
        boosted.putalpha(alpha)
    elif mode in ("RGB", "L", "P"):
        boosted = Image.fromarray(out, "RGB").convert(mode)
    else:
        boosted = Image.fromarray(out, "RGB")

    after_gray = np.asarray(boosted.convert("L"), dtype=np.float64)
    after_metrics = metrics(after_gray, top_pct=top_pct)
    return boosted, float(gain), before_metrics, after_metrics, None


def boost_file(
    file_path: Path | str,
    target: float = TARGET,
    black_pct: float = BLACK_PCT,
    top_pct: float = TOP_PCT,
    apply: bool = False,
    backup: bool = True,
) -> dict:
    """处理单个图片文件，支持写盘与备份。"""
    p = Path(file_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    im = Image.open(p)
    boosted, gain, before, after, skip_reason = boost_image(
        im, target=target, black_pct=black_pct, top_pct=top_pct
    )

    bak_path = None
    if apply and not skip_reason:
        if backup:
            bak_path = p.parent / f"_pre_{p.name}"
            if not bak_path.exists():
                shutil.copy2(p, bak_path)
        boosted.save(p)

    return {
        "path": p,
        "name": p.name,
        "gain": gain,
        "skipped_reason": skip_reason,
        "before": before,
        "after": after,
        "applied": apply and not skip_reason,
        "backup_path": bak_path,
    }


def resolve_image_targets(target_path: str | Path | None = None) -> list[Path]:
    """解析目标图片文件列表。支持单个文件、图片目录、项目根目录（自动探寻 images/）或自发现唯一项目。"""
    if target_path is not None and str(target_path).strip():
        p = Path(target_path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"指定的路径不存在: {target_path}")
        if p.is_file():
            return [p]
        if p.is_dir():
            # 若目录内有 images/ 且包含 png，优先采用
            if (p / "images").is_dir():
                candidates = [f for f in sorted((p / "images").glob("*.png"))
                              if not f.name.startswith(("_pre_", "_raw_"))]
                if candidates:
                    return candidates
            candidates = [f for f in sorted(p.glob("*.png"))
                          if not f.name.startswith(("_pre_", "_raw_"))]
            if candidates:
                return candidates
            raise ValueError(f"在目录 {target_path} 中未找到可处理的 PNG 图片")

    # 未显式指定 target_path 时，尝试自发现
    cwd_images = Path("images").resolve()
    if cwd_images.is_dir():
        candidates = [f for f in sorted(cwd_images.glob("*.png"))
                      if not f.name.startswith(("_pre_", "_raw_"))]
        if candidates:
            return candidates

    repo_root = Path(__file__).resolve().parent.parent
    projects_dir = repo_root / "projects"
    if projects_dir.is_dir():
        project_subdirs = [d for d in projects_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        projects_with_images = [
            d for d in project_subdirs
            if (d / "images").is_dir() and any((d / "images").glob("*.png"))
        ]
        if len(projects_with_images) == 1:
            candidates = [f for f in sorted((projects_with_images[0] / "images").glob("*.png"))
                          if not f.name.startswith(("_pre_", "_raw_"))]
            if candidates:
                return candidates
        elif len(projects_with_images) > 1:
            names = ", ".join(d.name for d in projects_with_images)
            raise ValueError(f"发现多个项目包含图片目录 ({names})，请显式指定路径")

    raise ValueError("未指定路径且无法安全自动发现图片目录，请提供图片文件或目录路径")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="boost_ink.py — 暗底线性图专用提亮：黑点保持 + 高光增益"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="目标图片文件、图片目录或项目路径（默认自发现当前或 projects/* 项目中的 images/）",
    )
    parser.add_argument(
        "--target",
        "--target-lum",
        dest="target",
        type=float,
        default=TARGET,
        help=f"目标亮度值（将 p99.9 提亮至此值，默认: {TARGET}）",
    )
    parser.add_argument(
        "--black-pct",
        type=float,
        default=BLACK_PCT,
        help=f"黑点百分位数（默认: {BLACK_PCT}）",
    )
    parser.add_argument(
        "--top-pct",
        type=float,
        default=TOP_PCT,
        help=f"高光参考百分位数（默认: {TOP_PCT}）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="写盘模式（写盘前自动备份 _pre_<name>.png），不加则仅预演",
    )

    args = parser.parse_args(argv)

    try:
        files = resolve_image_targets(args.path)
    except Exception as e:
        print(f"[err] {e}")
        return 1

    if not files:
        print("没有可处理的 PNG")
        return 1

    print(f"{'file':16} {'gain':>5} | {'max':>4}→{'max':>4} {'p99.9':>5}→{'p99.9':>5} "
          f"{'>150%':>6}→{'>150%':>6} {'>200%':>6}→{'>200%':>6}")
    print("-" * 88)

    for p in files:
        try:
            res = boost_file(
                p,
                target=args.target,
                black_pct=args.black_pct,
                top_pct=args.top_pct,
                apply=args.apply,
            )
            if res["skipped_reason"]:
                print(f"{res['name']:16} 跳过（{res['skipped_reason']}）")
                continue
            before = res["before"]
            after = res["after"]
            print(f"{res['name']:16} {res['gain']:5.2f} | "
                  f"{before['max']:4.0f}→{after['max']:4.0f} "
                  f"{before['p999']:5.0f}→{after['p999']:5.0f} "
                  f"{before['gt150']:6.2f}→{after['gt150']:6.2f} "
                  f"{before['gt200']:6.2f}→{after['gt200']:6.2f}")
        except Exception as e:
            print(f"{p.name:16} 处理失败: {e}")

    print("-" * 88)
    print("已写盘 ✅" if args.apply else "预演模式（未写盘），加 --apply 执行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
