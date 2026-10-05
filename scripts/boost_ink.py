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
  python3 boost_ink.py [path ...] [--target 230] [--black-pct 5.0] [--top-pct 99.9] [--apply] [--check] [--min-ink 2.0]

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

try:
    from scripts.analyze_image import (
        detect_seam,
        laplacian_variance,
        measure_ink,
        subject_sharp,
    )
except ImportError:
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    if str(repo_root / "scripts") not in sys.path:
        sys.path.insert(0, str(repo_root / "scripts"))
    try:
        from scripts.analyze_image import (
            detect_seam,
            laplacian_variance,
            measure_ink,
            subject_sharp,
        )
    except ImportError:
        detect_seam = None
        laplacian_variance = None
        measure_ink = None
        subject_sharp = None

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
        "boosted_image": boosted,
    }


def resolve_image_targets(
    target_paths: list[str | Path] | str | Path | None = None,
    base_dir: str | Path | None = None,
) -> list[Path]:
    """解析目标图片文件列表。支持单个文件、图片目录、项目根目录（自动探寻 images/）或自发现唯一项目。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
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
            item_str = str(item).strip()
            if not item_str:
                continue
            p = Path(item)
            cand = (base / p).resolve() if not p.is_absolute() else p.resolve()
            if not cand.exists():
                raise FileNotFoundError(f"指定的路径不存在: {item}")
            if cand.is_file():
                add_path(cand)
            elif cand.is_dir():
                img_dir = cand / "images"
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
                    f for f in sorted(cand.glob("*.png"))
                    if not f.name.startswith(("_pre_", "_raw_"))
                ]
                if candidates:
                    for c in candidates:
                        add_path(c)
                else:
                    raise ValueError(f"在目录 {item} 中未找到可处理的 PNG 图片")
        return resolved

    # 未显式指定 target_paths 时，尝试自发现
    base_images = (base / "images").resolve() if base.is_dir() else (base.parent / "images").resolve()
    if base_images.is_dir():
        candidates = [
            f for f in sorted(base_images.glob("*.png"))
            if not f.name.startswith(("_pre_", "_raw_"))
        ]
        if candidates:
            return candidates

    repo_root = Path(__file__).resolve().parent.parent
    candidate_projects_dirs: list[Path] = []
    if base.is_dir() and base.name == "projects":
        candidate_projects_dirs.append(base)
    elif (base / "projects").is_dir():
        candidate_projects_dirs.append(base / "projects")
    projects_dir = repo_root / "projects"
    if projects_dir.is_dir() and projects_dir.resolve() not in [d.resolve() for d in candidate_projects_dirs]:
        candidate_projects_dirs.append(projects_dir)

    for p_dir in candidate_projects_dirs:
        project_subdirs = [
            d for d in p_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
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


def check_boosted_quality(
    im: Image.Image | str | Path,
    min_ink: float = 2.0,
) -> tuple[bool, list[str]]:
    """验证提亮后图像是否满足客观质量门禁（接缝、主体清晰度、整体暗度与有效墨量）。"""
    if isinstance(im, (str, Path)):
        p = Path(im)
        if not p.is_file():
            return False, [f"文件不存在: {im}"]
        try:
            im = Image.open(p)
        except Exception as e:
            return False, [f"无法读取图片: {e}"]
    issues: list[str] = []
    rgb = im.convert("RGB")
    if detect_seam is not None:
        seam_x = detect_seam(rgb)
        if seam_x is not None:
            issues.append(f"存在接缝 (x={seam_x})")
    if subject_sharp is not None:
        ssharp = subject_sharp(rgb)
        if ssharp < 40.0:
            issues.append(f"主体模糊 (主体锐 {ssharp:.1f} < 40.0)")
    g = np.asarray(im.convert("L"), dtype=np.float64)
    p99 = float(np.percentile(g, 99.0))
    if p99 < 30.0:
        issues.append(f"整体过暗 (P99 {p99:.1f} < 30.0)")
    if measure_ink is not None:
        ink_ratio = measure_ink(rgb, thr=35)
        ink_pct = round(ink_ratio * 100.0, 2)
        if ink_pct < min_ink:
            issues.append(f"墨量不足 ({ink_pct:.2f}% < {min_ink:.1f}%)")
    return len(issues) == 0, issues


def boost_ink(
    path: str | Path | list[str | Path] | None = None,
    target: float = TARGET,
    black_pct: float = BLACK_PCT,
    top_pct: float = TOP_PCT,
    apply: bool = False,
    backup: bool = True,
    check: bool = False,
    min_ink: float = 2.0,
    verbose: bool = False,
    base_dir: str | Path | None = None,
) -> list[dict]:
    """批量或单张执行黑点保持高光增益提亮，支持客观质量门禁校验。

    :param path: 目标图片、目录、项目路径或图片列表（默认自发现）
    :param target: 目标亮度值（默认: 230.0）
    :param black_pct: 黑点百分位数（默认: 5.0）
    :param top_pct: 高光参考百分位数（默认: 99.9）
    :param apply: 是否真正写盘（默认 False 仅预演）
    :param backup: 写盘时是否先自动备份原图（默认 True）
    :param check: 是否在提亮后执行客观质量门禁检验（墨量 >= min_ink，P99 >= 30，主体锐 >= 40，无接缝）
    :param min_ink: 质量门禁最低墨量百分比阈值（默认: 2.0%）
    :param verbose: 是否输出日志（默认 False）
    :param base_dir: 基础目录，用于相对路径解析（可选）
    :return: 处理结果字典列表
    """
    files = resolve_image_targets(path, base_dir=base_dir)
    if not files:
        raise FileNotFoundError("未找到可处理的 PNG 图片")

    results: list[dict] = []
    gate_failures: list[str] = []

    for p in files:
        res = boost_file(
            p,
            target=target,
            black_pct=black_pct,
            top_pct=top_pct,
            apply=apply,
            backup=backup,
        )
        if verbose:
            mode_tag = "(已写盘)" if (apply and not res.get("skipped_reason")) else "[预演]"
            if res.get("skipped_reason"):
                print(f"[跳过] {res['name']}: {res['skipped_reason']}", file=sys.stderr)
            else:
                print(f"✓ {mode_tag} {res['name']} (增益 {res['gain']:.2f}×)")
        if check:
            boosted_im = res.get("boosted_image")
            if boosted_im is None:
                try:
                    boosted_im = Image.open(p)
                except Exception:
                    boosted_im = None
            if boosted_im is not None:
                passed, issues = check_boosted_quality(boosted_im, min_ink=min_ink)
            else:
                passed = False
                issues = [res.get("skipped_reason") or "无法读取图片"]
            res["quality_gate_passed"] = passed
            res["quality_gate_issues"] = issues
            if not passed:
                gate_failures.append(f"{res['name']}: {', '.join(issues)}")
        results.append(res)

    if check and gate_failures:
        raise RuntimeError(f"配图客观质量门禁未通过: {'; '.join(gate_failures)}")

    return results


def check_boost_ink(
    target: str | Path | Image.Image,
    target_lum: float = TARGET,
    black_pct: float = BLACK_PCT,
    top_pct: float = TOP_PCT,
    min_ink: float = 2.0,
) -> tuple[bool, dict, list[str]]:
    """客观质量门禁判定：验证单张图片提亮后是否满足客观质量门禁（接缝、清晰度、亮度、墨量）。

    :param target: 图片文件路径 (Path/str) 或 PIL Image 对象
    :param target_lum: 目标亮度值（默认: 230.0）
    :param black_pct: 黑点百分位数（默认: 5.0）
    :param top_pct: 高光参考百分位数（默认: 99.9）
    :param min_ink: 最低有效墨量百分比阈值（默认: 2.0%）
    :return: (通过布尔值, 统计指标字典, 未通过原因列表)
    """
    min_ink_val = float(min_ink)
    if isinstance(target, Image.Image):
        try:
            im = target.convert("RGB")
            name = getattr(target, "filename", None) or "image.png"
            name = Path(name).name if name else "image.png"
            boosted, gain, before, after, skip = boost_image(
                im, target=target_lum, black_pct=black_pct, top_pct=top_pct
            )
            passed, issues = check_boosted_quality(boosted, min_ink=min_ink_val)
            res = {
                "path": getattr(target, "filename", "") or "",
                "name": name,
                "gain": gain,
                "skipped_reason": skip,
                "before": before,
                "after": after,
                "applied": False,
                "boosted_image": boosted,
                "quality_gate_passed": passed,
                "quality_gate_issues": issues,
            }
            return passed, res, issues
        except Exception as e:
            name = getattr(target, "filename", None) or "image.png"
            name = Path(name).name if name else "image.png"
            err = f"提亮分析异常: {e}"
            return False, {"name": name, "issues": [err]}, [err]
    else:
        try:
            p = Path(target)
            if not p.is_file():
                err = f"文件不存在: {target}"
                return False, {"name": p.name, "issues": [err]}, [err]
            res = boost_file(
                p,
                target=target_lum,
                black_pct=black_pct,
                top_pct=top_pct,
                apply=False,
                backup=False,
            )
            boosted_im = res.get("boosted_image")
            if boosted_im is not None:
                passed, issues = check_boosted_quality(boosted_im, min_ink=min_ink_val)
            else:
                passed = False
                issues = [res.get("skipped_reason") or "无法读取图片"]
            res["quality_gate_passed"] = passed
            res["quality_gate_issues"] = issues
            return passed, res, issues
        except Exception as e:
            name = Path(target).name if isinstance(target, (str, Path)) else "image.png"
            err = f"提亮处理异常: {e}"
            return False, {"name": name, "issues": [err]}, [err]


def run_qa_boost_ink(
    targets: str | Path | list[str | Path] | None = None,
    target_lum: float = TARGET,
    black_pct: float = BLACK_PCT,
    top_pct: float = TOP_PCT,
    min_ink: float = 2.0,
    verbose: bool = True,
    base_dir: str | Path | None = None,
) -> bool:
    """运行 PPT-Studio 配图提亮客观质量门禁。

    :param targets: 目标图片、目录、项目路径或图片列表（默认自发现）
    :param target_lum: 目标亮度值（默认: 230.0）
    :param black_pct: 黑点百分位数（默认: 5.0）
    :param top_pct: 高光参考百分位数（默认: 99.9）
    :param min_ink: 最低墨量百分比阈值（默认: 2.0%）
    :param verbose: 是否输出日志（默认 True）
    :param base_dir: 基础目录，用于相对路径解析（可选）
    :return: 全部通过返回 True，否则返回 False
    """
    try:
        resolved = resolve_image_targets(targets, base_dir=base_dir)
    except Exception as e:
        if verbose:
            print(f"[err] {e}", file=sys.stderr)
        return False

    if not resolved:
        if verbose:
            print("[err] 未找到任何可处理的 PNG 图片", file=sys.stderr)
        return False

    all_ok = True
    failed_items = []
    min_ink_val = float(min_ink)
    for p in resolved:
        ok, res, issues = check_boost_ink(
            p,
            target_lum=target_lum,
            black_pct=black_pct,
            top_pct=top_pct,
            min_ink=min_ink_val,
        )
        if not ok:
            all_ok = False
            failed_items.append((p.name, issues))
        elif verbose:
            after_metrics = res.get("after", {})
            p99 = after_metrics.get("p999", 0.0)
            print(f"  [✓] {p.name}: 增益 {res.get('gain', 1.0):.2f}× (P99.9 {p99:.1f})")

    if verbose:
        if not all_ok:
            print("\n[门禁] ⚠️ 存在未通过客观质量门禁的提亮配图:", file=sys.stderr)
            for fname, issues in failed_items:
                print(f"  ✗ {fname}: {', '.join(issues)}", file=sys.stderr)
        else:
            print("  [门禁] ✓ 配图提亮客观质量门禁通过")

    return all_ok


qa_boost_ink = run_qa_boost_ink
qa_single_boost_ink = check_boost_ink
run_qa_single_boost_ink = check_boost_ink


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="boost_ink.py — 暗底线性图专用提亮：黑点保持 + 高光增益"
    )
    parser.add_argument(
        "path",
        nargs="*",
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
    parser.add_argument(
        "--base-dir",
        default=None,
        help="指定基础工作目录 (默认: 当前工作目录)",
    )

    args = parser.parse_args(argv)
    verbose = not args.quiet if args.quiet else args.verbose
    effective_base = (
        Path(args.base_dir).resolve()
        if args.base_dir
        else (Path(base_dir).resolve() if base_dir else Path.cwd().resolve())
    )

    path_arg = args.path if args.path else None
    try:
        results = boost_ink(
            path=path_arg,
            target=args.target,
            black_pct=args.black_pct,
            top_pct=args.top_pct,
            apply=args.apply,
            check=False,
            min_ink=args.min_ink,
            base_dir=effective_base,
        )
    except Exception as e:
        if verbose:
            print(f"[err] {e}", file=sys.stderr)
        return 1

    if not results:
        if verbose:
            print("没有可处理的 PNG", file=sys.stderr)
        return 1

    if verbose:
        print(f"{'file':16} {'gain':>5} | {'max':>4}→{'max':>4} {'p99.9':>5}→{'p99.9':>5} "
              f"{'>150%':>6}→{'>150%':>6} {'>200%':>6}→{'>200%':>6}")
        print("-" * 88)

        for res in results:
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

        print("-" * 88)
        print("已写盘 ✅" if args.apply else "预演模式（未写盘），加 --apply 执行")

    if args.check:
        gate_failures = []
        for res in results:
            boosted_im = res.get("boosted_image")
            if boosted_im is None:
                try:
                    boosted_im = Image.open(res["path"])
                except Exception:
                    boosted_im = None
            if boosted_im is not None:
                passed, issues = check_boosted_quality(boosted_im, min_ink=args.min_ink)
            else:
                passed = False
                issues = [res.get("skipped_reason") or "无法读取图片"]
            if not passed:
                gate_failures.append(f"{res['name']}: {', '.join(issues)}")

        if gate_failures:
            if verbose:
                print("\n[门禁] ⚠️ 存在未通过客观质量门禁的配图（模糊/接缝/过暗/墨量不足）:", file=sys.stderr)
                for f in gate_failures:
                    print(f"  ✗ {f}", file=sys.stderr)
            return 1
        else:
            if verbose:
                print("  [门禁] ✓ 配图客观质量门禁通过")

    return 0


if __name__ == "__main__":
    sys.exit(main())
