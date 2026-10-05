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


def resolve_crop_targets(
    src_input: str | Path | list[str | Path] | None = None,
    base_dir: str | Path | None = None,
    repo_root_override: str | Path | None = None,
) -> list[Path]:
    """解析待裁切图片文件列表。支持单个文件、图片目录、项目根目录（自动探寻 images/）、
    纯文件名自发现、以及未指定参数时自动自发现当前或 projects/* 项目中的待裁切配图。
    """
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    repo_root = (
        Path(repo_root_override).resolve()
        if repo_root_override
        else Path(__file__).resolve().parent.parent
    )

    if src_input is not None:
        if isinstance(src_input, (str, Path)):
            raw_list = [src_input]
        else:
            raw_list = list(src_input)
    else:
        raw_list = []

    resolved: list[Path] = []
    seen: set[Path] = set()

    def add_path(p: Path) -> None:
        rp = p.resolve()
        if rp not in seen and rp.is_file():
            seen.add(rp)
            resolved.append(rp)

    if raw_list:
        for item in raw_list:
            item_str = str(item).strip()
            if not item_str:
                continue
            p = Path(item)
            # 1. 尝试作为绝对路径或相对于 base 的直接路径
            candidate = p if p.is_absolute() else (base / p).resolve()
            if candidate.is_file():
                add_path(candidate)
                continue
            if candidate.is_dir():
                img_dir = candidate / "images"
                target_dir = img_dir if img_dir.is_dir() else candidate
                found_imgs = [
                    f for f in sorted(target_dir.glob("*.png"))
                    if not f.name.startswith(("_pre_", "_raw_"))
                    and not f.stem.endswith("_panel")
                ]
                if not found_imgs:
                    found_imgs = [
                        f for f in sorted(target_dir.glob("*.png"))
                        if not f.name.startswith(("_pre_", "_raw_"))
                    ]
                if found_imgs:
                    for f in found_imgs:
                        add_path(f)
                    continue
                else:
                    raise ValueError(f"在目录 {item} 中未找到可处理的 PNG 图片")

            # 2. 尝试在 base / "images" 下按文件名寻找
            cand_img = (base / "images" / p.name).resolve()
            if cand_img.is_file():
                add_path(cand_img)
                continue

            # 3. 尝试在 repo_root / "projects" / * / images 下寻找
            projects_dir = repo_root / "projects"
            matches: list[Path] = []
            if projects_dir.is_dir():
                for sub in sorted(projects_dir.iterdir()):
                    if sub.is_dir() and not sub.name.startswith("."):
                        cand1 = (sub / "images" / p.name).resolve()
                        cand2 = (sub / p.name).resolve()
                        if cand1.is_file():
                            matches.append(cand1)
                        elif cand2.is_file():
                            matches.append(cand2)

            if len(matches) == 1:
                add_path(matches[0])
                continue
            elif len(matches) > 1:
                names = ", ".join(str(m) for m in matches)
                raise ValueError(f"发现多个项目包含同名图片 '{p.name}' ({names})，请显式指定完整路径")

            raise FileNotFoundError(f"源图片文件不存在: {item}")

        return resolved

    # 未指定任何参数时：自动发现
    if (base / "images").is_dir():
        cand = [
            f for f in sorted((base / "images").glob("*.png"))
            if not f.name.startswith(("_pre_", "_raw_"))
            and not f.stem.endswith("_panel")
        ]
        if cand:
            return cand

    projects_dir = repo_root / "projects"
    if projects_dir.is_dir():
        proj_candidates: list[Path] = []
        for sub in sorted(projects_dir.iterdir()):
            if sub.is_dir() and not sub.name.startswith("."):
                img_dir = sub / "images"
                if img_dir.is_dir():
                    imgs = [
                        f for f in sorted(img_dir.glob("*.png"))
                        if not f.name.startswith(("_pre_", "_raw_"))
                        and not f.stem.endswith("_panel")
                    ]
                    if imgs:
                        proj_candidates.extend(imgs)
        if proj_candidates:
            return proj_candidates

    raise FileNotFoundError("未指定输入图片，且在当前目录或 projects/*/images 下未发现有效待裁切图片")


def crop_image(
    src_path: str | Path,
    out_path: str | Path | None = None,
    aspect: str | float = "580:385",
    pad: float = 1.12,
    apply: bool = False,
    base_dir: str | Path | None = None,
    check: bool = False,
    min_ink: float = 3.0,
) -> dict:
    """执行裁切计算与可选落盘，返回结果指标字典。"""
    targets = resolve_crop_targets(src_path, base_dir=base_dir)
    if not targets:
        raise FileNotFoundError(f"源图片文件不存在: {src_path}")
    src_p = targets[0]

    tgt_aspect = parse_aspect(aspect)
    if pad <= 0:
        raise ValueError(f"边距系数 pad 必须大于 0: {pad}")

    im = Image.open(src_p).convert("RGB")
    a = np.asarray(im, dtype=np.float64)
    h, w = a.shape[:2]

    bb = bbox_of(a)
    if bb is None:
        raise ValueError(f"{src_p.name}: 没找到主体（亮像素太少）")

    x0, y0, x1, y1 = bb
    left, top, bw, bh = calculate_crop(w, h, bb, tgt_aspect, pad)

    before = cover(a, (0, 0, w, h))
    after = cover(a, (left, top, bw, bh))

    if out_path:
        out_p = Path(out_path)
        base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
        final_out = (base / out_p).resolve() if not out_p.is_absolute() else out_p.resolve()
    else:
        final_out = src_p.with_name(f"{src_p.stem}_panel.png")

    if apply:
        final_out.parent.mkdir(parents=True, exist_ok=True)
        ix, iy, iw, ih = [int(round(v)) for v in (left, top, bw, bh)]
        cropped = Image.fromarray(a[iy:iy + ih, ix:ix + iw].astype(np.uint8))
        cropped.save(final_out)

    check_passed = after >= min_ink
    issues: list[str] = []
    if not check_passed:
        issues.append(f"主体墨量不足 ({after:.2f}% < {min_ink:.2f}%)")

    if check and not check_passed:
        raise ValueError(f"{src_p.name}: 客观质量门禁未通过: {'; '.join(issues)}")

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
        "check_passed": check_passed,
        "issues": issues,
    }


def crop_panel(
    targets: str | Path | list[str | Path] | None = None,
    out_dir: str | Path | None = None,
    aspect: str | float = "580:385",
    pad: float = 1.12,
    apply: bool = False,
    check: bool = False,
    min_ink: float = 3.0,
    verbose: bool = False,
    base_dir: str | Path | None = None,
    repo_root_override: str | Path | None = None,
) -> list[dict]:
    """批量或单张执行主体包围盒面板裁切，支持质量门禁校验与可选写盘。

    :param targets: 目标图片、目录、项目路径或图片列表（默认自发现）
    :param out_dir: 可选输出目录（缺省时保存在原图片同目录下）
    :param aspect: 目标宽高比（默认: 580:385）
    :param pad: 主体包围盒向外扩张系数（默认: 1.12）
    :param apply: 是否真正写盘（默认 False 仅预演）
    :param check: 是否在裁切后执行客观质量门禁校验（墨量 >= min_ink）
    :param min_ink: 质量门禁最低墨量百分比阈值（默认: 3.0%）
    :param verbose: 是否输出日志（默认 False）
    :param base_dir: 基准目录
    :param repo_root_override: 仓库根目录覆盖（测试用）
    :return: 处理结果字典列表
    """
    resolved = resolve_crop_targets(
        targets, base_dir=base_dir, repo_root_override=repo_root_override
    )
    if not resolved:
        raise FileNotFoundError("未找到可处理的待裁切图片")

    results: list[dict] = []
    gate_failures: list[str] = []

    out_directory = Path(out_dir).resolve() if out_dir else None
    if out_directory and apply:
        out_directory.mkdir(parents=True, exist_ok=True)

    for p in resolved:
        out_path = None
        if out_directory:
            out_path = out_directory / f"{p.stem}_panel.png"

        try:
            res = crop_image(
                src_path=p,
                out_path=out_path,
                aspect=aspect,
                pad=pad,
                apply=apply,
                base_dir=base_dir,
                check=False,
                min_ink=min_ink,
            )
            results.append(res)
            if verbose:
                mode_tag = "(已写盘)" if apply else "[预演]"
                print(f"✓ {mode_tag} {p.name} → {res['out']} (墨量 {res['after_cover']:.2f}%)")
            if not res["check_passed"]:
                gate_failures.append(f"{p.name}: {'; '.join(res['issues'])}")
        except Exception as e:
            gate_failures.append(f"{p.name}: 裁切失败: {e}")
            if verbose:
                print(f"[!] 裁切 {p.name} 失败: {e}", file=sys.stderr)

    if check and gate_failures:
        raise ValueError("裁切客观质量门禁未通过:\n  " + "\n  ".join(gate_failures))

    return results


def check_crop_panel(
    target: str | Path | Image.Image,
    aspect: str | float = "580:385",
    pad: float = 1.12,
    min_ink: float = 3.0,
    base_dir: str | Path | None = None,
) -> tuple[bool, dict, list[str]]:
    """客观质量门禁判定：验证单张图片是否能有效识别主体并完成面板裁切且墨量达标。

    :param target: 图片文件路径 (Path/str) 或 PIL Image 对象
    :param aspect: 目标宽高比（默认: 580:385）
    :param pad: 主体包围盒向外扩张系数（默认: 1.12）
    :param min_ink: 最低有效墨量百分比阈值（默认: 3.0%）
    :param base_dir: 基准目录
    :return: (通过布尔值, 统计指标字典, 未通过原因列表)
    """
    min_ink_val = float(min_ink)
    if isinstance(target, Image.Image):
        im = target.convert("RGB")
        a = np.asarray(im, dtype=np.float64)
        h, w = a.shape[:2]
        bb = bbox_of(a)
        name = getattr(target, "filename", None) or "image.png"
        name = Path(name).name if name else "image.png"
        if bb is None:
            issue = f"{name}: 没找到主体（亮像素太少）"
            return False, {"name": name, "width": w, "height": h, "issues": [issue]}, [issue]
        tgt_aspect = parse_aspect(aspect)
        left, top, bw, bh = calculate_crop(w, h, bb, tgt_aspect, pad)
        before = cover(a, (0, 0, w, h))
        after = cover(a, (left, top, bw, bh))
        check_passed = after >= min_ink_val
        issues = [] if check_passed else [f"{name}: 主体墨量不足 ({after:.2f}% < {min_ink_val:.2f}%)"]
        res = {
            "src": getattr(target, "filename", "") or "",
            "name": name,
            "width": w,
            "height": h,
            "bbox": bb,
            "crop_box": (left, top, bw, bh),
            "target_aspect": tgt_aspect,
            "actual_aspect": bw / bh if bh > 0 else 0.0,
            "before_cover": before,
            "after_cover": after,
            "out": "",
            "applied": False,
            "check_passed": check_passed,
            "issues": issues,
        }
        return check_passed, res, issues
    else:
        try:
            res = crop_image(
                src_path=target,
                aspect=aspect,
                pad=pad,
                apply=False,
                base_dir=base_dir,
                check=False,
                min_ink=min_ink_val,
            )
            return res["check_passed"], res, res["issues"]
        except Exception as e:
            name = Path(target).name if isinstance(target, (str, Path)) else "image.png"
            err_msg = str(e)
            return False, {"name": name, "issues": [err_msg]}, [err_msg]


def run_qa_crop_panel(
    targets: str | Path | list[str | Path] | None = None,
    aspect: str | float = "580:385",
    pad: float = 1.12,
    min_ink: float = 3.0,
    verbose: bool = True,
    base_dir: str | Path | None = None,
) -> bool:
    """运行 PPT-Studio 面板裁切客观质量门禁。

    :param targets: 目标图片、目录、项目路径或图片列表（默认自发现）
    :param aspect: 目标宽高比（默认: 580:385）
    :param pad: 主体包围盒向外扩张系数（默认: 1.12）
    :param min_ink: 最低墨量百分比阈值（默认: 3.0%）
    :param verbose: 是否输出日志（默认 True）
    :param base_dir: 基准目录
    :return: 全部通过返回 True，否则返回 False
    """
    try:
        resolved = resolve_crop_targets(targets, base_dir=base_dir)
    except Exception as e:
        if verbose:
            print(f"[err] {e}", file=sys.stderr)
        return False

    if not resolved:
        if verbose:
            print("[err] 未找到任何可裁切的图片", file=sys.stderr)
        return False

    all_ok = True
    failed_items = []
    min_ink_val = float(min_ink)
    for p in resolved:
        ok, res, issues = check_crop_panel(p, aspect=aspect, pad=pad, min_ink=min_ink_val, base_dir=base_dir)
        if not ok:
            all_ok = False
            failed_items.append((p.name, issues))
        elif verbose:
            print(f"  [✓] {p.name}: 墨量 {res.get('after_cover', 0.0):.2f}% (≥ {min_ink_val:.1f}%)")

    if verbose:
        if not all_ok:
            print("\n[门禁] ⚠️ 存在未通过客观质量门禁的裁切目标:", file=sys.stderr)
            for fname, issues in failed_items:
                print(f"  ✗ {fname}: {', '.join(issues)}", file=sys.stderr)
        else:
            print("  [门禁] ✓ 面板裁切客观质量门禁通过")

    return all_ok


qa_crop_panel = run_qa_crop_panel
qa_single_crop_panel = check_crop_panel
run_qa_single_crop_panel = check_crop_panel


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="按'主体包围盒'裁切配图，让主体填满面板"
    )
    parser.add_argument(
        "src",
        nargs="*",
        default=None,
        help="源图片路径、纯文件名、图片目录或项目路径（默认自发现）",
    )
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
        help="输出图片路径 (仅单张图片时有效，默认: <src_stem>_panel.png)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正写盘保存裁切后图片（默认仅预演）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="运行质量门禁判定：若发现主体未检出或裁切后面板墨量不足 (默认 < 3.0%%) 则返回退出码 1",
    )
    parser.add_argument(
        "--min-ink",
        type=float,
        default=3.0,
        help="质量门禁最低墨量百分比阈值（默认: 3.0%%，防面板偏空）",
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

    src_args = args.src if args.src else None
    try:
        targets = resolve_crop_targets(src_args, base_dir=base_dir)
    except (FileNotFoundError, ValueError) as e:
        if verbose:
            print(f"[!] {e}", file=sys.stderr)
        return 1

    if not targets:
        if verbose:
            print("[!] 未找到任何可裁切的图片", file=sys.stderr)
        return 1

    if args.out and len(targets) > 1:
        if verbose:
            print("[!] --out 参数仅支持单张图片裁切，批量处理时请省略该参数", file=sys.stderr)
        return 1

    all_passed = True
    for i, t in enumerate(targets):
        out_p = args.out if (args.out and len(targets) == 1) else None
        try:
            res = crop_image(
                src_path=t,
                out_path=out_p,
                aspect=args.aspect,
                pad=args.pad,
                apply=args.apply,
                base_dir=base_dir,
            )
        except (FileNotFoundError, ValueError) as e:
            if verbose:
                print(f"[!] {t.name}: 裁切失败: {e}", file=sys.stderr)
            all_passed = False
            continue
        except Exception as e:
            if verbose:
                print(f"[!] {t.name}: 裁切发生异常: {e}", file=sys.stderr)
            all_passed = False
            continue

        x0, y0, x1, y1 = res["bbox"]
        left, top, bw, bh = res["crop_box"]
        tgt = res["target_aspect"]
        actual = res["actual_aspect"]
        before = res["before_cover"]
        after = res["after_cover"]

        if verbose:
            print(f"{res['name']}  {res['width']}x{res['height']}")
            print(f"  主体 bbox  x {x0:.0f}-{x1:.0f} ({x1-x0:.0f}px)  y {y0:.0f}-{y1:.0f} ({y1-y0:.0f}px)")
            print(f"  裁切框     x {left:.0f} y {top:.0f}  {bw:.0f}x{bh:.0f}  (比例 {actual:.3f} vs 目标 {tgt:.3f})")
            ratio_multiplier = after / max(before, 1e-6)
            print(f"  主体占画面  {before:.2f}%  →  {after:.2f}%   ({ratio_multiplier:.1f}×)")

            if res["applied"]:
                print(f"  已保存 {res['out']}")
            else:
                print("  [提示] 当前为预演模式（未写盘），加 --apply 执行写盘")

        if args.check:
            if after < args.min_ink:
                if verbose:
                    print(f"  [门禁] ⚠️ 主体墨量不足 {args.min_ink:.1f}% (当前 {after:.2f}%)，面板可能偏空", file=sys.stderr)
                all_passed = False
            else:
                if verbose:
                    print(f"  [门禁] ✓ 墨量达标 ({after:.2f}% ≥ {args.min_ink:.1f}%)")

        if verbose and i < len(targets) - 1:
            print()

    if args.check and all_passed and verbose:
        print("  [门禁] ✓ 面板裁切客观质量门禁通过")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
