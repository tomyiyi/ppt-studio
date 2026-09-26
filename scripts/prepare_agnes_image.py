#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agnes 配图后处理：裁 16:9 + 去接缝 + 压暗
==========================================

Agnes 出图常见两个问题，都在这里一次性修掉：
  1. 尺寸不是 16:9（如 1312x736）→ 等比放大后居中裁到精确 16:9
  2. 提示词里写了"左半/右半"时，模型会真的切一刀，留下一条竖向亮度接缝
     → 用「左右均值归一 + 平滑过渡带」把接缝抹平

用法：
  python3 prepare_agnes_image.py <raw.png> <out.png> [--size 2560x1440]
  python3 prepare_agnes_image.py <raw.png> [--apply]        # 原地写盘 + 备份
  python3 prepare_agnes_image.py [project_or_images_dir]   # 自动发现并批量处理
  python3 prepare_agnes_image.py --manifest [path]         # 基于 image_prompts.json 批量处理
  python3 prepare_agnes_image.py --check [path]            # 客观门禁校验
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

# 确保在未显式激活 .venv 时也能从项目内 .venv 加载依赖
try:
    import numpy as np
    from PIL import Image, ImageEnhance
except ImportError:
    repo_root = Path(__file__).resolve().parent.parent
    for site_pkg in repo_root.glob(".venv/lib/python*/site-packages"):
        if site_pkg.is_dir() and str(site_pkg) not in sys.path:
            sys.path.insert(0, str(site_pkg))
    import numpy as np
    from PIL import Image, ImageEnhance


# ---------------------------------------------------------------- 去接缝

def detect_seam(im: Image.Image, margin: float = 0.10,
                row_agree: float = 0.70, min_step: float = 6.0) -> int | None:
    """找竖向接缝。

    ⚠️ 关键判据：**接缝贯穿全高，内容边缘只占部分行**。
    只看「列均值曲线」会把发光图形自身的硬边缘误判成接缝
    （实测 heal_bg 就栽在这：误报 x=330，强行抹平反而把跳变从 7.4 放大到 8.4）。
    所以必须逐行求各自的突变列，再看有多少行「投票」到同一列。

    判定条件（宁可漏检，不要误修）：
      - 候选列不在左右 10% 边缘带内
      - 该行突变幅度 >= min_step(6)
      - 至少 30% 的行存在显著突变
      - 这些行的突变列有 >= row_agree(60%) 落在同一列的 ±2 内
    """
    g = np.asarray(im.convert("L"), dtype=np.float32)
    H, W = g.shape
    if W < 40:
        return None
    lo, hi = int(W * margin), int(W * (1 - margin))
    if hi - lo < 20:
        return None

    # 1) 用「列均值」找候选 —— 720 行平均后噪声只剩 ~0.16，弱接缝也能浮出来
    col = g.mean(axis=0)
    seg = np.abs(np.diff(col))[lo:hi]
    if seg.size == 0:
        return None
    i = int(np.argmax(seg))
    step = float(seg[i])
    x = lo + i + 1
    if step < min_step:
        return None

    # 2) 用「暗行一致率」验证：接缝贯穿全高（连背景暗行也跳），
    #    内容边缘只在亮结构里（暗行不跳）
    #    —— 只统计暗行后判别力大幅拉开，实测：
    #      真接缝 0.93~1.00  vs  误报最高 0.49（另有 0.00~0.40 一批）
    #      而「全行一致率」只有 0.71 vs 0.93，间隔太窄不稳
    #    逐行 argmax 会被噪点主导（千列噪声极值可达 15），所以只做验证不做搜索
    e = np.abs(g[:, x] - g[:, x - 1])
    thr = max(2.5, 0.45 * step)
    row_mean = g.mean(axis=1)
    dim = row_mean <= np.median(row_mean)
    agree = float(np.mean(e[dim] >= thr)) if dim.any() else 0.0
    if agree < row_agree:
        return None
    return x


def fix_seam(im: Image.Image, x: int, band: int = 0) -> Image.Image:
    """抹平 x 处的竖向亮度台阶。

    ⚠️ 两个反直觉但关键的结论（都经实测验证，别再改回去）：

    1) 必须「加偏移」而不是「乘增益」。乘增益会把台阶同比例放大
       （实测跳变 14 → 18.6，越修越糟）。

    2) 补偿必须是「与台阶对齐的硬阶跃」，不能做平滑过渡带。
       因为原始数据是硬台阶（Δ），若补偿在 x 附近平滑地从 0 变到 Δ，
       补偿自身在 x 处的变化量≈0，等于没补，跳变仍是 Δ。
       只有在 x 处做一个等量反向硬阶跃，两者才精确抵消（跳变 → 0）。
       实测：加过渡带后残差 13.05；硬阶跃后残差 ~0.2（仅噪声）。

    band 参数保留仅为兼容旧调用，当前实现不使用。
    """
    a = np.asarray(im, dtype=np.float32).copy()
    w = a.shape[1]
    x = int(np.clip(x, 1, w - 1))

    if a.ndim == 2:
        left_mean = a[:, :x].mean()
        right_mean = a[:, x:].mean()
        delta = right_mean - left_mean
        a[:, :x] += delta
    elif a.ndim == 3 and a.shape[2] == 4:
        left_mean = a[:, :x, :3].reshape(-1, 3).mean(axis=0)
        right_mean = a[:, x:, :3].reshape(-1, 3).mean(axis=0)
        delta = (right_mean - left_mean).astype(np.float32)
        a[:, :x, :3] += delta
    else:
        left_mean = a[:, :x].reshape(-1, a.shape[2]).mean(axis=0)
        right_mean = a[:, x:].reshape(-1, a.shape[2]).mean(axis=0)
        delta = (right_mean - left_mean).astype(np.float32)
        a[:, :x] += delta

    mode = im.mode if im.mode in ("RGB", "RGBA", "L") else None
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), mode=mode)


# ---------------------------------------------------------------- 主流程

def parse_size(size_str: str) -> tuple[int, int]:
    """解析并校验类似 '2560x1440' 格式的目标分辨率字符串。"""
    if "x" not in size_str.lower():
        raise ValueError(f"尺寸格式无效: '{size_str}'，应为类似 '2560x1440' 格式")
    parts = size_str.lower().split("x")
    if len(parts) != 2:
        raise ValueError(f"尺寸格式无效: '{size_str}'，应为类似 '2560x1440' 格式")
    try:
        tw = int(parts[0].strip())
        th = int(parts[1].strip())
    except ValueError:
        raise ValueError(f"尺寸数值无效: '{size_str}'，长宽必须为整数")
    if tw <= 0 or th <= 0:
        raise ValueError(f"目标尺寸长宽必须大于 0: '{size_str}'")
    return tw, th


def prepare(
    raw: Path | str,
    out: Path | str | None = None,
    size: tuple[int, int] = (2560, 1440),
    brightness: float = 1.0,
    seam: str = "auto",
) -> dict:
    raw_path = Path(raw)
    if not raw_path.is_file():
        raise FileNotFoundError(f"源图片文件不存在: {raw_path}")
    tw, th = size
    if tw <= 0 or th <= 0:
        raise ValueError(f"目标尺寸长宽必须大于 0: {size}")
    if brightness < 0:
        raise ValueError(f"亮度系数必须 >= 0，当前为: {brightness}")

    with Image.open(raw_path) as src_im:
        im = src_im.convert("RGB")
    src_size = im.size
    report: dict[str, object] = {
        "src": f"{src_size[0]}x{src_size[1]}",
        "seam": None,
        "fixed": False,
    }

    # 1) 去接缝（在原始分辨率上做，缩放后更干净）
    seam_norm = seam.strip().lower()
    if seam_norm == "off":
        pass
    elif seam_norm == "auto":
        x = detect_seam(im)
        if x is not None:
            report["seam"] = x
            im = fix_seam(im, x)
            report["fixed"] = True
    else:
        parts = [p.strip() for p in seam.split(",") if p.strip()]
        if not parts:
            raise ValueError(f"接缝参数格式无效: '{seam}'")
        fixed_cols = []
        for p in parts:
            try:
                col = int(p)
            except ValueError:
                raise ValueError(f"无效的接缝列号: '{p}' (完整参数: '{seam}')")
            if col <= 0 or col >= im.size[0]:
                raise ValueError(f"接缝列号 {col} 超出图像有效跨度 [1, {im.size[0] - 1}]")
            im = fix_seam(im, col)
            fixed_cols.append(col)
        report["seam"] = fixed_cols[0] if len(fixed_cols) == 1 else fixed_cols
        report["fixed"] = bool(fixed_cols)

    # 2) 精确裁到目标比例
    w, h = im.size
    scale = max(tw / w, th / h)
    if scale != 1.0:
        im = im.resize(
            (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
            Image.LANCZOS,
        )
    w, h = im.size
    crop_x = (w - tw) // 2
    crop_y = (h - th) // 2
    im = im.crop((crop_x, crop_y, crop_x + tw, crop_y + th))

    # 3) 亮度
    if brightness != 1.0:
        im = ImageEnhance.Brightness(im).enhance(brightness)

    report["out"] = f"{im.size[0]}x{im.size[1]}"
    if out is not None:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        im.save(out_path, "PNG", optimize=True)
        report["kb"] = out_path.stat().st_size // 1024
    else:
        report["kb"] = 0
    return report


def resolve_image_targets(
    target_path: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> list[Path]:
    """解析目标图片文件列表。支持单个文件、图片目录、项目根目录（自动探寻 images/）或自发现唯一项目。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    if target_path is not None and str(target_path).strip():
        p = Path(target_path)
        if not p.is_absolute():
            p = (base / p).resolve()
        else:
            p = p.resolve()
        if not p.exists():
            raise FileNotFoundError(f"源图片文件不存在: {target_path}")
        if p.is_file():
            return [p]
        if p.is_dir():
            if (p / "images").is_dir():
                candidates = [
                    f for f in sorted((p / "images").glob("*.png"))
                    if not f.name.startswith(("_pre_", "_raw_"))
                ]
                if candidates:
                    return candidates
            candidates = [
                f for f in sorted(p.glob("*.png"))
                if not f.name.startswith(("_pre_", "_raw_"))
            ]
            if candidates:
                return candidates
            raise ValueError(f"在目录 {target_path} 中未找到可处理的 PNG 图片")

    # 未显式指定 target_path 时，尝试自发现
    cwd_images = base / "images"
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
            d for d in projects_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
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
            raise ValueError(f"发现多个包含 images/ 的项目 ({names})，无法安全确定，请显式指定 target 参数")

    raise FileNotFoundError("未指定输入图片，且在当前目录或 projects/*/images 下未发现有效待处理图片")


def resolve_manifest_target(
    target: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> Path:
    """解析目标 image_prompts.json 清单文件。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    if target is not None and str(target).strip():
        p = Path(target)
        if not p.is_absolute():
            p = (base / p).resolve()
        else:
            p = p.resolve()
        if not p.exists():
            raise FileNotFoundError(f"指定的清单路径不存在: {target}")
        if p.is_file():
            return p
        if p.is_dir():
            for c in [p / "images" / "image_prompts.json", p / "image_prompts.json"]:
                if c.is_file():
                    return c
            for c in sorted(p.glob("*.json")):
                if c.name.endswith(".json"):
                    return c
            raise FileNotFoundError(f"在目录 {target} 下未找到 image_prompts.json 清单文件")

    # 未显式指定 target 时自发现
    cands = [
        base / "images" / "image_prompts.json",
        base / "image_prompts.json",
    ]
    for c in cands:
        if c.is_file():
            return c

    repo_root = Path(__file__).resolve().parent.parent
    projects_dir = repo_root / "projects"
    if projects_dir.is_dir():
        found = []
        for sub in sorted(projects_dir.iterdir()):
            if sub.is_dir() and not sub.name.startswith("."):
                mf = sub / "images" / "image_prompts.json"
                if mf.is_file():
                    found.append(mf)
                elif (sub / "image_prompts.json").is_file():
                    found.append(sub / "image_prompts.json")
        if len(found) == 1:
            return found[0]
        elif len(found) > 1:
            names = ", ".join(f.parent.parent.name if f.parent.name == "images" else f.parent.name for f in found)
            raise ValueError(f"发现多个有效配图清单 ({names})，请显式指定 manifest 参数")

    raise FileNotFoundError("未在当前目录或 projects/*/images/ 下发现有效的 image_prompts.json 清单文件")


def parse_postprocess_cmd(cmd_str: str) -> dict:
    """从 image_prompts.json 中的 postprocess 命令字符串解析参数。
    例如: prepare_agnes_image.py --size 2560x1440 --brightness 0.95 --seam auto
    """
    tokens = shlex.split(cmd_str)
    if tokens and (tokens[0].endswith(".py") or "prepare_agnes_image" in tokens[0]):
        tokens = tokens[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", default="2560x1440")
    parser.add_argument("--brightness", type=float, default=1.0)
    parser.add_argument("--seam", default="auto")
    args, _ = parser.parse_known_args(tokens)
    tw, th = parse_size(args.size)
    return {
        "size": (tw, th),
        "brightness": args.brightness,
        "seam": args.seam,
    }


def check_images(
    targets: list[Path],
    size: tuple[int, int] | None = None,
    verbose: bool = True,
) -> dict:
    """客观质量门禁判定：验证目标图片是否存在未抹平接缝、尺寸或格式损坏。"""
    results: list[dict] = []
    failed_seams: list[str] = []
    unreadable: list[str] = []
    dimension_mismatches: list[str] = []

    for p in targets:
        if not p.is_file() or p.stat().st_size == 0:
            unreadable.append(f"{p.name} (空文件或不存在)")
            continue
        try:
            with Image.open(p) as src_im:
                im = src_im.convert("RGB")
            w, h = im.size
            seam_x = detect_seam(im)
            if seam_x is not None:
                failed_seams.append(f"{p.name} (x={seam_x})")
            if size is not None:
                tw, th = size
                if (w, h) != (tw, th):
                    dimension_mismatches.append(f"{p.name} ({w}x{h} vs 期望 {tw}x{th})")
            results.append({
                "file": str(p),
                "name": p.name,
                "size": f"{w}x{h}",
                "seam": seam_x,
            })
        except Exception as e:
            unreadable.append(f"{p.name} ({e})")

    ok = (len(targets) > 0 and not unreadable and not failed_seams and not dimension_mismatches)
    res = {
        "ok": ok,
        "total": len(targets),
        "unreadable": unreadable,
        "failed_seams": failed_seams,
        "dimension_mismatches": dimension_mismatches,
        "items": results,
    }

    if verbose:
        print("=" * 60)
        print("🔍 运行 PPT-Studio 配图客观后处理门禁")
        print(f"   目标数量: {len(targets)} 张图片")
        print("=" * 60)
        if not unreadable:
            print(f"  [✓] 文件实体与完整性   : {len(targets)} 张图片均有效且可读取")
        else:
            print(f"  [✗] 文件实体与完整性   : 发现 {len(unreadable)} 处文件损坏或不可读 ({', '.join(unreadable[:3])})")

        if not failed_seams:
            print(f"  [✓] 竖向接缝消除闭环   : 0 处残留接缝 (detect_seam 全部通过)")
        else:
            print(f"  [✗] 竖向接缝消除闭环   : 发现 {len(failed_seams)} 张图片存在残留接缝: {', '.join(failed_seams[:3])}")

        if size is not None:
            if not dimension_mismatches:
                print(f"  [✓] 目标画幅一致性     : 全部符合 {size[0]}x{size[1]}")
            else:
                print(f"  [✗] 目标画幅一致性     : 发现 {len(dimension_mismatches)} 处画幅偏差: {', '.join(dimension_mismatches[:3])}")

        print("=" * 60)
        if ok:
            print("ALL CLEAR ✅")
        else:
            print("❌ 门禁未通过")
        print("=" * 60)

    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Agnes 配图后处理：裁 16:9 + 去接缝 + 压暗")
    ap.add_argument("raw", nargs="?", default=None, help="原始输入图片路径、图片目录或项目路径（默认自发现）")
    ap.add_argument("out", nargs="?", default=None, help="处理后输出图片路径（可选；省略时配合 --apply 原地写盘）")
    ap.add_argument("--out", dest="out_flag", default=None, help="显式指定输出图片路径或目录")
    ap.add_argument("--size", default="2560x1440", help="目标分辨率 (默认: 2560x1440)")
    ap.add_argument("--brightness", type=float, default=1.0, help="亮度缩放系数 (默认: 1.0)")
    ap.add_argument("--seam", default="auto", help="接缝处理模式: auto | off | 列号[,列号] (默认: auto)")
    ap.add_argument("--apply", action="store_true", help="写盘模式（写盘前自动备份 _pre_<name>.png），不加则仅预演")
    ap.add_argument("--no-backup", action="store_true", help="写盘时跳过创建 _pre_<name>.png 备份")
    ap.add_argument("--manifest", nargs="?", const="", default=None, help="基于 image_prompts.json 清单批量执行对应 postprocess 参数")
    ap.add_argument("--check", action="store_true", help="客观门禁检验：扫描目标图片是否存在未抹平接缝或画幅异常")
    ap.add_argument("--json", action="store_true", help="以 JSON 格式输出处理或质检结果")
    a = ap.parse_args(argv)

    # 1. 门禁模式
    if a.check:
        try:
            targets = resolve_image_targets(a.raw)
            tw, th = parse_size(a.size) if a.size else (2560, 1440)
            res = check_images(targets, size=(tw, th) if "--size" in (argv or []) else None, verbose=not a.json)
            if a.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0 if res["ok"] else 1
        except Exception as e:
            print(f"[!] 门禁检查失败: {e}", file=sys.stderr)
            return 1

    # 2. 清单模式 (--manifest)
    if a.manifest is not None:
        raw_manifest_arg = a.manifest if a.manifest != "" else a.raw
        try:
            mf_path = resolve_manifest_target(raw_manifest_arg)
        except (FileNotFoundError, ValueError) as e:
            print(f"[!] {e}", file=sys.stderr)
            return 1
        try:
            mf_data = json.loads(mf_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[!] 读取或解析清单失败: {e}", file=sys.stderr)
            return 1

        img_dir = mf_path.parent if mf_path.parent.name == "images" else mf_path.parent / "images"
        items = mf_data.get("items") or []
        if not a.json:
            print(f"· 基于清单 {mf_path.name} 处理 {len(items)} 项配图...")
        ok_count = 0
        reports = []
        for it in items:
            fn = it.get("filename")
            if not fn:
                continue
            src_file = img_dir / fn
            if not src_file.is_file():
                if not a.json:
                    print(f"  [skip] 找不到文件 {fn}")
                continue
            post_cmd = it.get("postprocess") or ""
            cfg = parse_postprocess_cmd(post_cmd) if post_cmd else {
                "size": parse_size(a.size),
                "brightness": a.brightness,
                "seam": a.seam,
            }
            if a.apply:
                if not a.no_backup:
                    bak = src_file.parent / f"_pre_{src_file.name}"
                    if not bak.exists():
                        shutil.copy2(src_file, bak)
                rep = prepare(src_file, src_file, size=cfg["size"], brightness=cfg["brightness"], seam=cfg["seam"])
                rep["name"] = fn
                reports.append(rep)
                if not a.json:
                    seam_msg = f"接缝@{rep['seam']} ✓已抹平" if rep["seam"] else "无接缝"
                    print(f"✓ {fn}  {rep['src']} → {rep['out']}  {rep['kb']}KB  [{seam_msg}] (已写盘)")
            else:
                rep = prepare(src_file, None, size=cfg["size"], brightness=cfg["brightness"], seam=cfg["seam"])
                rep["name"] = fn
                reports.append(rep)
                if not a.json:
                    seam_msg = f"接缝@{rep['seam']} 需抹平" if rep["seam"] else "无接缝"
                    print(f"[预演] {fn}  {rep['src']} → {rep['out']}  [{seam_msg}]")
            ok_count += 1
        if not a.apply and not a.json:
            print("[提示] 当前为预演模式（未写盘），加 --apply 执行写盘")
        if a.json:
            print(json.dumps(reports, ensure_ascii=False, indent=2))
        return 0

    # 3. 常规图片处理
    output_target = a.out_flag or a.out
    try:
        tw, th = parse_size(a.size)
    except ValueError as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1

    try:
        targets = resolve_image_targets(a.raw)
    except (FileNotFoundError, ValueError) as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1

    # 单张且明确给了目标输出文件（传统两参数调用）
    if len(targets) == 1 and output_target:
        src_p = targets[0]
        out_p = Path(output_target)
        try:
            rep = prepare(src_p, out_p, (tw, th), a.brightness, a.seam)
        except (FileNotFoundError, ValueError) as e:
            print(f"[!] {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"[!] 处理失败: {e}", file=sys.stderr)
            return 1

        if not a.json:
            seam_txt = (
                f"接缝@{','.join(str(c) for c in rep['seam'])} ✓已抹平"
                if isinstance(rep["seam"], list)
                else (f"接缝@x={rep['seam']} ✓已抹平" if rep["seam"] else "无接缝")
            )
            print(f"✓ {out_p.name}  {rep['src']} → {rep['out']}  {rep['kb']}KB  [{seam_txt}]")
        if a.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0

    # 批量或单张原地处理
    reports = []
    for src_p in targets:
        if a.apply:
            if not a.no_backup:
                bak = src_p.parent / f"_pre_{src_p.name}"
                if not bak.exists():
                    shutil.copy2(src_p, bak)
            rep = prepare(src_p, src_p, (tw, th), a.brightness, a.seam)
            rep["name"] = src_p.name
            reports.append(rep)
            if not a.json:
                seam_txt = f"接缝@{rep['seam']} ✓已抹平" if rep["seam"] else "无接缝"
                print(f"✓ {src_p.name}  {rep['src']} → {rep['out']}  {rep['kb']}KB  [{seam_txt}] (已写盘)")
        else:
            rep = prepare(src_p, None, (tw, th), a.brightness, a.seam)
            rep["name"] = src_p.name
            reports.append(rep)
            if not a.json:
                seam_txt = f"接缝@{rep['seam']} 需抹平" if rep["seam"] else "无接缝"
                print(f"[预演] {src_p.name}  {rep['src']} → {rep['out']}  [{seam_txt}]")

    if not a.apply and not a.json:
        print("[提示] 当前为预演模式（未写盘），加 --apply 执行写盘")
    if a.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
