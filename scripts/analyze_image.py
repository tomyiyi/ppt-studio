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
  python3 analyze_image.py [path ...] [--json] [--check]
"""

from __future__ import annotations

import argparse
import json
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
    寻找主体边界时使用 max(R,G,B)，防范彩色笔画（如 #6E7BFF）被转灰度权重压低。
    """
    rgb = np.asarray(im.convert("RGB"), dtype=np.float64)
    if rgb.size == 0 or rgb.max() == 0:
        return 0.0
    mx = rgb.max(axis=2)
    t = float(np.percentile(mx, pct))
    if t <= 0.0:
        t = 1.0
    ys, xs = np.where(mx >= t)
    if ys.size < 50:
        return 0.0
    pad = 24
    y0, y1 = max(0, ys.min() - pad), min(rgb.shape[0], ys.max() + pad)
    x0, x1 = max(0, xs.min() - pad), min(rgb.shape[1], xs.max() + pad)

    g = np.asarray(im.convert("L"), dtype=np.float64)
    var_g = _lap_var(g[y0:y1, x0:x1])
    var_mx = _lap_var(mx[y0:y1, x0:x1])
    return float(max(var_g, var_mx))


def measure_ink(im: Image.Image, thr: int = 35) -> float:
    """计算图像墨量比例（max(R,G,B) >= thr 的像素占比）。

    使用 max(R,G,B) 避免高饱和彩色笔画（如靛蓝 #6E7BFF）被相对亮度权重拉低。
    """
    a = np.asarray(im.convert("RGB"), dtype=np.uint8)
    if a.size == 0:
        return 0.0
    mx = a.max(axis=2)
    return float((mx >= thr).sum()) / float(mx.size)


def ink_map(im: Image.Image, thresh_pct: float = 97.0) -> np.ndarray:
    """亮像素在 3x3 网格中的占比矩阵（行=上中下，列=左中右）。

    使用 max(R,G,B) 判定高亮像素，确保高饱和彩色笔画（如 #6E7BFF）不被灰度加权压低。
    """
    a = np.asarray(im.convert("RGB"), dtype=np.float32)
    H, W = a.shape[:2]
    if H == 0 or W == 0:
        return np.zeros((3, 3), dtype=np.float32)
    mx = a.max(axis=2)
    t = np.percentile(mx, thresh_pct)
    mask = (mx >= t).astype(np.float32)
    m = np.zeros((3, 3), dtype=np.float32)
    if H < 3 or W < 3:
        mean_val = float(mask.mean())
        m.fill(mean_val / 9.0 if mean_val > 0 else 0.0)
        tot = m.sum() or 1.0
        return m / tot

    for r in range(3):
        r_start = r * H // 3
        r_end = (r + 1) * H // 3 if r < 2 else H
        for c in range(3):
            c_start = c * W // 3
            c_end = (c + 1) * W // 3 if c < 2 else W
            blk = mask[r_start:r_end, c_start:c_end]
            if blk.size > 0:
                m[r, c] = blk.mean()
    tot = float(m.sum())
    if tot == 0.0:
        return m
    return m / tot


def report(path: Path | str) -> dict:
    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"文件不存在: {path}")
    im = Image.open(p).convert("RGB")
    g = np.asarray(im.convert("L"), dtype=np.float32)
    m = ink_map(im)
    ink_ratio = measure_ink(im, thr=35)
    col = "左  中  右"
    return {
        "name": p.name,
        "path": str(p),
        "size": f"{im.size[0]}x{im.size[1]}",
        "width": im.size[0],
        "height": im.size[1],
        "sharp": laplacian_variance(im),
        "ssharp": subject_sharp(im),
        "mean": float(g.mean()),
        "p99": float(np.percentile(g, 99)),
        "ink_ratio": round(ink_ratio, 4),
        "ink_pct": round(ink_ratio * 100.0, 2),
        "ink": m,
        "seam": detect_seam(im),
        "colhead": col,
    }


def resolve_image_targets(
    target_paths: list[str | Path] | str | Path | None = None,
) -> list[Path]:
    """解析目标图片文件列表。支持单个文件、图片目录、项目根目录（自动探寻 images/）或自发现唯一项目。"""
    if target_paths is not None:
        if isinstance(target_paths, (str, Path)):
            raw_list = [target_paths]
        else:
            raw_list = list(target_paths)
    else:
        raw_list = []

    resolved: list[Path] = []
    seen = set()

    def add_path(p: Path):
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            resolved.append(p)

    if raw_list:
        for item in raw_list:
            p = Path(item).resolve()
            if not p.exists():
                raise FileNotFoundError(f"指定的路径不存在: {item}")
            if p.is_file():
                add_path(p)
            elif p.is_dir():
                img_dir = p / "images"
                if img_dir.is_dir():
                    candidates = [
                        f for f in sorted(img_dir.glob("*.png"))
                        if not f.name.startswith(("_pre_", "_raw_"))
                    ]
                    if candidates:
                        for c in candidates:
                            add_path(c)
                        continue
                candidates = [
                    f for f in sorted(p.glob("*.png"))
                    if not f.name.startswith(("_pre_", "_raw_"))
                ]
                if candidates:
                    for c in candidates:
                        add_path(c)
                else:
                    raise ValueError(f"在目录 {item} 中未找到可处理的 PNG 图片")
        return resolved

    # 未显式指定 target_paths 时，尝试自发现
    cwd_images = Path("images").resolve()
    if cwd_images.is_dir():
        candidates = [
            f for f in sorted(cwd_images.glob("*.png"))
            if not f.name.startswith(("_pre_", "_raw_"))
        ]
        if candidates:
            return candidates

    repo_root = Path(__file__).resolve().parent.parent
    projects_dir = repo_root / "projects"
    if projects_dir.is_dir():
        project_subdirs = [
            d for d in projects_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
        ]
        projects_with_images = [
            d for d in project_subdirs
            if (d / "images").is_dir() and any((d / "images").glob("*.png"))
        ]
        if len(projects_with_images) == 1:
            candidates = [
                f for f in sorted((projects_with_images[0] / "images").glob("*.png"))
                if not f.name.startswith(("_pre_", "_raw_"))
            ]
            if candidates:
                return candidates
        elif len(projects_with_images) > 1:
            names = ", ".join(d.name for d in projects_with_images)
            raise ValueError(f"发现多个项目包含图片目录 ({names})，请显式指定路径")

    raise ValueError("未指定路径且无法安全自动发现图片目录，请提供图片文件或目录路径")


def check_image_quality(
    target: Path | str | Image.Image,
    min_ink: float = 2.0,
) -> tuple[bool, dict, list[str]]:
    """客观质量门禁判定：验证单张图片是否满足清晰度、接缝、亮度和墨量要求。

    :param target: 图片文件路径 (Path/str) 或 PIL Image 对象
    :param min_ink: 最低有效墨量百分比阈值（默认: 2.0%）
    :return: (通过布尔值, 统计指标字典, 未通过原因列表)
    """
    if isinstance(target, Image.Image):
        im = target.convert("RGB")
        g = np.asarray(im.convert("L"), dtype=np.float32)
        m = ink_map(im)
        ink_ratio = measure_ink(im, thr=35)
        ssharp = subject_sharp(im)
        p99 = float(np.percentile(g, 99))
        seam = detect_seam(im)
        ink_pct = round(ink_ratio * 100.0, 2)
        name = getattr(target, "filename", None) or "image.png"
        name = Path(name).name if name else "image.png"
        r = {
            "name": name,
            "path": getattr(target, "filename", "") or "",
            "size": f"{im.size[0]}x{im.size[1]}",
            "width": im.size[0],
            "height": im.size[1],
            "sharp": laplacian_variance(im),
            "ssharp": ssharp,
            "mean": float(g.mean()),
            "p99": p99,
            "ink_ratio": round(ink_ratio, 4),
            "ink_pct": ink_pct,
            "ink": m,
            "seam": seam,
            "colhead": "左  中  右",
        }
    else:
        r = report(target)

    issues: list[str] = []
    if r["ssharp"] < 40.0:
        issues.append(f"严重模糊 (主体锐 {r['ssharp']:.1f} < 40.0)")
    if r["seam"] is not None:
        issues.append(f"存在接缝 (x={r['seam']})")
    if r["p99"] < 30.0:
        issues.append(f"整体过暗 (P99 {r['p99']:.1f} < 30.0)")
    if r["ink_pct"] < min_ink:
        issues.append(f"墨量不足 ({r['ink_pct']:.2f}% < {min_ink:.1f}%)")

    ok = len(issues) == 0
    return ok, r, issues


def run_qa_images(
    targets: str | Path | list[str | Path] | None = None,
    min_ink: float = 2.0,
    verbose: bool = True,
) -> bool:
    """运行 PPT-Studio 配图客观质量门禁。

    :param targets: 目标图片、目录、项目路径或图片列表（默认自发现）
    :param min_ink: 最低墨量百分比阈值（默认: 2.0%）
    :param verbose: 是否输出日志（默认 True）
    :return: 全部通过返回 True，否则返回 False
    """
    try:
        paths = resolve_image_targets(targets)
    except Exception as e:
        if verbose:
            print(f"[err] {e}", file=sys.stderr)
        return False

    if not paths:
        if verbose:
            print("[err] 没有可分析的 PNG 图片", file=sys.stderr)
        return False

    all_ok = True
    reports = []
    failed_items: list[tuple[str, list[str]]] = []

    for p in paths:
        try:
            ok, r, issues = check_image_quality(p, min_ink=min_ink)
            reports.append(r)
            if not ok:
                all_ok = False
                failed_items.append((r["name"], issues))
        except Exception as e:
            all_ok = False
            failed_items.append((Path(p).name, [f"分析失败: {e}"]))

    if verbose:
        print(f"{'文件':<22}{'尺寸':>10}{'全图锐':>8}{'主体锐':>8}{'均亮':>7}{'P99':>7}{'墨量%':>8}  "
              f"主体分布(上/中/下 × 左/中/右, %)      接缝")
        print("-" * 138)
        for r in reports:
            rows = ["  ".join(f"{r['ink'][i][j]*100:5.1f}" for j in range(3)) for i in range(3)]
            print(f"{r['name']:<22}{r['size']:>10}{r['sharp']:>8.1f}{r['ssharp']:>8.1f}"
                  f"{r['mean']:>7.1f}{r['p99']:>7.1f}{r['ink_pct']:>7.1f}%  "
                  f"{rows[0]}  |  {rows[1]}  |  {rows[2]}   {r['seam']}")

        print("\n判读：")
        print("  主体锐 —— 只框定最亮 1% 像素区域算的拉普拉斯方差，判断线条是否锐利；<80 判糊")
        print("  全图锐 —— 含大片纯黑，会被稀释，仅作参考")
        print("  墨量   —— 画面有效笔画像素占比 (max(R,G,B) ≥ 35)；<2.0% 判漏图/空白，≥6.0% 为充盈")
        print("  主体分布 —— 每格 11% 为均匀分布基线；最高格 >=25% 才有明确主体，<15% 视为没画出图形")
        print("  P99 —— 亮部强度，<40 说明整体过暗没高光")
        print("  接缝 —— None 为无；有数值交由 prepare_agnes_image.py --seam 修")

        if not all_ok:
            print("\n[门禁] ⚠️ 存在未通过客观质量门禁的配图（模糊/接缝/过暗/墨量不足）:", file=sys.stderr)
            for fname, issues in failed_items:
                print(f"  ✗ {fname}: {', '.join(issues)}", file=sys.stderr)
        else:
            print("\n[门禁] ✓ 配图客观质量门禁通过")

    return all_ok


qa_images = run_qa_images
qa_single_image = check_image_quality
run_qa_single_image = check_image_quality


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="配图客观验收（当无法肉眼看图时用数据代替眼睛）"
    )
    parser.add_argument(
        "images",
        nargs="*",
        default=None,
        help="目标图片文件、图片目录或项目路径（默认自发现当前或 projects/* 项目中的 images/）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出分析指标",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="运行质量门禁判定：若发现严重模糊 (主体锐 < 40)、存在接缝、整体过暗 (P99 < 30) 或墨量不足 (默认 < 2.0%%) 则返回退出码 1",
    )
    parser.add_argument(
        "--min-ink",
        type=float,
        default=2.0,
        help="质量门禁最低墨量百分比阈值（默认: 2.0%%，防漏图/空白画布）",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=True,
        help="详细日志输出（默认开启）",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="静默模式（仅通过退出码返回结果）",
    )

    args = parser.parse_args(argv)
    verbose = not args.quiet if args.quiet else args.verbose

    try:
        paths = resolve_image_targets(args.images if args.images else None)
    except Exception as e:
        if verbose:
            print(f"[err] {e}", file=sys.stderr)
        return 1

    if not paths:
        if verbose:
            print("[err] 没有可分析的 PNG 图片", file=sys.stderr)
        return 1

    reports = []
    has_check_failure = False
    failed_items: list[tuple[str, list[str]]] = []

    for p in paths:
        try:
            ok, r, issues = check_image_quality(p, min_ink=args.min_ink)
            reports.append(r)
            if not ok:
                has_check_failure = True
                failed_items.append((r["name"], issues))
        except Exception as e:
            if verbose:
                print(f"[err] 分析 {p} 失败: {e}", file=sys.stderr)
            has_check_failure = True
            failed_items.append((Path(p).name, [f"分析失败: {e}"]))

    if args.json:
        json_data = []
        for r in reports:
            item = dict(r)
            item["ink"] = item["ink"].tolist() if hasattr(item["ink"], "tolist") else item["ink"]
            json_data.append(item)
        print(json.dumps(json_data, ensure_ascii=False, indent=2))
        return 1 if (args.check and has_check_failure) else 0

    if verbose:
        print(f"{'文件':<22}{'尺寸':>10}{'全图锐':>8}{'主体锐':>8}{'均亮':>7}{'P99':>7}{'墨量%':>8}  "
              f"主体分布(上/中/下 × 左/中/右, %)      接缝")
        print("-" * 138)
        for r in reports:
            rows = ["  ".join(f"{r['ink'][i][j]*100:5.1f}" for j in range(3)) for i in range(3)]
            print(f"{r['name']:<22}{r['size']:>10}{r['sharp']:>8.1f}{r['ssharp']:>8.1f}"
                  f"{r['mean']:>7.1f}{r['p99']:>7.1f}{r['ink_pct']:>7.1f}%  "
                  f"{rows[0]}  |  {rows[1]}  |  {rows[2]}   {r['seam']}")

        print("\n判读：")
        print("  主体锐 —— 只框定最亮 1% 像素区域算的拉普拉斯方差，判断线条是否锐利；<80 判糊")
        print("  全图锐 —— 含大片纯黑，会被稀释，仅作参考")
        print("  墨量   —— 画面有效笔画像素占比 (max(R,G,B) ≥ 35)；<2.0% 判漏图/空白，≥6.0% 为充盈")
        print("  主体分布 —— 每格 11% 为均匀分布基线；最高格 >=25% 才有明确主体，<15% 视为没画出图形")
        print("  P99 —— 亮部强度，<40 说明整体过暗没高光")
        print("  接缝 —— None 为无；有数值交由 prepare_agnes_image.py --seam 修")

        if args.check:
            if has_check_failure:
                print("\n[门禁] ⚠️ 存在未通过客观质量门禁的配图（模糊/接缝/过暗/墨量不足）", file=sys.stderr)
            else:
                print("\n[门禁] ✓ 配图客观质量门禁通过")

    if args.check and has_check_failure:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
