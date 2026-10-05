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


def fix_seam(im: Image.Image, x: int, band: int = 2) -> Image.Image:
    """抹平 x 处的竖向亮度台阶。

    三个反直觉但关键的结论（都经实测验证，别再改回去）：

    1) 必须「加偏移」而不是「乘增益」。乘增益会把台阶同比例放大
       （实测跳变 14 → 18.6，越修越糟）。

    2) 补偿必须是「与台阶对齐的硬阶跃」，不能做平滑过渡带。
       因为原始数据是硬台阶（Δ），若补偿在 x 附近平滑地从 0 变到 Δ，
       补偿自身在 x 处的变化量≈0，等于没补，跳变仍是 Δ。
       只有在 x 处做一个等量反向硬阶跃，两者才精确抵消（跳变 → 0）。
       实测：加过渡带后残差 13.05；硬阶跃后残差 ~0.2（仅噪声）。

    3) 补偿量必须等于 **detect_seam 测到的那个台阶**：全行列均值曲线
       在 x 处的跳变（分通道取，b 列平均降噪）。H 行平均把无规内容
       噪声压到 ~0.16，只剩系统性台阶；估计口径与检测口径一致，
       两者才不会打架。备选估计量都经实测证伪：
       ① 整图左右半区均值差——混入内容不对称（05 上 8.4 → 62.1，越修越糟）；
       ② 全行逐行中位数——01 在 x=761 处 24 列带内有 -19 的内容渐变，
          中位数被带偏到负值；
       ③ 暗行逐行中位数——05 的豹纹污染了暗行（暗行台阶分布 [-58,+106]），
          中位数 +20 而真实台阶只有 +8，严重过补偿（8.4 → 11.5）。
       只有列均值曲线能把「每行随机位置的内容边缘」平均掉，留下
       「每行同一位置的接缝」。

    4) 接缝可能是缓坡而非硬台阶（05：宽约 8 列，单列跳变分散）。
       单次 fix_seam 只能清掉峰值列——此时不要调大 band 去"抹平"，
       而是用 remove_seam() 以 detector 为 oracle 迭代 nibble：
       每次 band=1 精确清零当前最大单列跳变，单调收敛。

    :param band: 台阶高度估计时两侧各取的列数（默认 2），钳制在边界内；
        只影响估计，不影响补偿形状。
    """
    a = np.asarray(im, dtype=np.float32).copy()
    h, w = a.shape[0], a.shape[1]
    x = int(np.clip(x, 1, w - 1))
    b = max(1, min(int(band), x, w - x))  # 两侧采样带宽，钳制在边界内

    # 台阶高度 = detect_seam 测到的那个量：全行列均值曲线在 x 处的跳变，
    # 分通道估计（RGBA 只动 RGB，alpha 不动）。
    if a.ndim == 2:
        col = a.mean(axis=0)
        delta = float(col[x:x + b].mean() - col[x - b:x].mean())
        a[:, :x] += delta
    else:
        nch = 3 if a.shape[2] == 4 else a.shape[2]
        col = a[:, :, :nch].mean(axis=0)  # (w, nch)
        delta = (col[x:x + b].mean(axis=0)
                 - col[x - b:x].mean(axis=0)).astype(np.float32)
        a[:, :x, :nch] += delta

    mode = im.mode if im.mode in ("RGB", "RGBA", "L") else None
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), mode=mode)


def remove_seam(im: Image.Image, x: int | None = None,
                max_iter: int = 10, radius: int = 24
                ) -> tuple[Image.Image, list[int], bool]:
    """以 detect_seam 为 oracle，迭代抹平 x 附近的接缝（含缓坡型）。

    背景（第 32 轮实测）：05_essentials 的"接缝"不是硬台阶，而是宽约
    8 列的缓坡（提亮后单列跳变 6.4/6.75/8.35…排布在 734~742）。
    单次硬阶跃只能清掉峰值列——修完 740 又冒出 736。
    教训：补偿形状必须匹配接缝形状，而最可靠的形状就是 detector
    每次看到的"当前最大单列跳变"。

    每次迭代：在提亮图上 detect → 用 fix_seam(band=1) 精确清零该列。
    band=1 的硬阶跃只改变 x 处的单列跳变（其余列的列均值差严格不变），
    所以每次迭代消灭恰好一个超标列 → 单调收敛，不会震荡。
    显式指定 x 时只修与之相距 ±radius 的列（同一条接缝，不误伤别处）；
    x=None 的全自动模式则修掉所有检出的接缝（否则修完一条、
    另一条仍让 QA 失败，修复失去意义）。max_iter 兜底防死循环。

    :param x: 已知的接缝列；为 None 时自己检测、无接缝则原样返回，
        有多条接缝则逐条修复。
    :return: (修复后图像, 实际修复的列, 是否收敛到无检出)。
    """
    # 延迟导入：顶层导入 boost_ink 会形成循环
    # (prepare_agnes_image → boost_ink → analyze_image → prepare_agnes_image)，
    # 在 top-level 导入模式下被 except ImportError 静默吞掉，导致
    # boost_ink.detect_seam = None、QA 门禁的接缝检查被静默跳过。
    # 函数调用时本模块已加载完毕，无循环问题。
    try:
        from scripts.boost_ink import boost_image
    except ImportError:  # 直接以 scripts/ 为工作目录运行时
        from boost_ink import boost_image

    if x is None:
        boosted, *_ = boost_image(im)
        x = detect_seam(boosted)
        if x is None:
            return im, [], True
        auto = True
    else:
        auto = False
    x0 = int(x)
    fixed_cols: list[int] = []
    cur = im
    for _ in range(max_iter):
        boosted, *_ = boost_image(cur)
        xi = detect_seam(boosted)
        if xi is None:
            return cur, fixed_cols, True
        if not auto and abs(xi - x0) > radius:
            break  # 另一条接缝：不动，交还给调用方决定
        cur = fix_seam(cur, xi, band=1)
        fixed_cols.append(xi)
    boosted, *_ = boost_image(cur)
    converged = detect_seam(boosted) is None
    return cur, fixed_cols, converged


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
        # 与 QA 门禁同口径：remove_seam 内部在提亮图上检测
        # （弱接缝原图上不可见，实测 01_cover/05_essentials 的接缝只在提亮后浮现）
        im, fixed_cols, converged = remove_seam(im)
        if fixed_cols:
            report["seam"] = fixed_cols[0]
            report["fixed"] = True
            report["fixed_cols"] = fixed_cols
            report["seam_converged"] = converged
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
    target_path: list[str | Path] | str | Path | None = None,
    base_dir: str | Path | None = None,
) -> list[Path]:
    """解析目标图片文件列表。支持单个文件、图片目录、项目根目录（自动探寻 images/）、路径列表或自发现唯一项目。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    if target_path is not None:
        if isinstance(target_path, (list, tuple, set)):
            raw_list = list(target_path)
        elif str(target_path).strip():
            raw_list = [target_path]
        else:
            raw_list = []
    else:
        raw_list = []

    if raw_list:
        resolved: list[Path] = []
        seen = set()

        def add_path(p: Path):
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                resolved.append(p)

        for item in raw_list:
            item_str = str(item).strip()
            if not item_str:
                continue
            p = Path(item)
            if not p.is_absolute():
                p = (base / p).resolve()
            else:
                p = p.resolve()
            if not p.exists():
                raise FileNotFoundError(f"源图片文件不存在: {item}")
            if p.is_file():
                add_path(p)
            elif p.is_dir():
                if (p / "images").is_dir():
                    candidates = [
                        f for f in sorted((p / "images").glob("*.png"))
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
        if resolved:
            return resolved

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
            d for d in p_dir.iterdir()
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
    candidate_projects_dirs: list[Path] = []
    if base.is_dir() and base.name == "projects":
        candidate_projects_dirs.append(base)
    elif (base / "projects").is_dir():
        candidate_projects_dirs.append(base / "projects")
    projects_dir = repo_root / "projects"
    if projects_dir.is_dir() and projects_dir.resolve() not in [d.resolve() for d in candidate_projects_dirs]:
        candidate_projects_dirs.append(projects_dir)

    for p_dir in candidate_projects_dirs:
        found = []
        for sub in sorted(p_dir.iterdir()):
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


SCHEMA_VERSION: int = 1
COMMON_SCHEMA_KEYS: frozenset[str] = frozenset({
    "schema_version",
    "ok",
    "total",
    "success_count",
    "failure_count",
    "partial_success",
    "is_partial_success",
    "failures",
    "failed_items",
    "items",
})
PREPARE_SCHEMA_KEYS: frozenset[str] = COMMON_SCHEMA_KEYS | frozenset({"reports"})
CHECK_SCHEMA_KEYS: frozenset[str] = COMMON_SCHEMA_KEYS | frozenset({
    "unreadable",
    "failed_seams",
    "dimension_mismatches",
})
FAILURE_ITEM_KEYS: frozenset[str] = frozenset({
    "file",
    "name",
    "code",
    "reason",
})


class BatchResult(dict):
    """批量处理或门禁质检结构化结果字典，兼容序列下标与字典字段访问。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "schema_version" not in self:
            self["schema_version"] = SCHEMA_VERSION

    def __getitem__(self, key):
        if isinstance(key, int):
            return self.get("items", [])[key]
        return super().__getitem__(key)


def _resolve_and_dedup_targets(
    targets: list[Path | str] | Path | str | None = None,
    base_dir: str | Path | None = None,
) -> tuple[list[Path], list[dict]]:
    """解析并去重目标图片路径。
    返回 (目标文件列表, 解析阶段直接失败项列表)。
    保证 check_images 与 prepare_images 具有完全一致的目标列表与去重行为。
    """
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    target_files: list[Path] = []
    failures: list[dict] = []
    seen = set()

    def add_target_path(p: Path):
        try:
            rkey = p.resolve()
        except Exception:
            rkey = p.absolute()
        if rkey not in seen:
            seen.add(rkey)
            target_files.append(p)

    if targets is None:
        try:
            resolved = resolve_image_targets(None, base_dir=base)
            for p in resolved:
                add_target_path(p)
        except Exception as e:
            failures.append({
                "file": "",
                "name": "",
                "code": "TARGET_RESOLUTION_ERROR",
                "reason": str(e),
            })
        return target_files, failures

    if isinstance(targets, (str, Path)):
        p = Path(targets)
        if not p.is_absolute():
            p = (base / p).resolve()
        else:
            p = p.resolve()
        if p.is_dir():
            try:
                resolved = resolve_image_targets(p, base_dir=base)
                for item in resolved:
                    add_target_path(item)
            except Exception as e:
                failures.append({
                    "file": str(p),
                    "name": p.name,
                    "code": "TARGET_RESOLUTION_ERROR",
                    "reason": str(e),
                })
        else:
            add_target_path(p)
        return target_files, failures

    if isinstance(targets, (list, tuple, set)):
        raw_items = list(targets)
    else:
        raw_items = [targets]

    for item in raw_items:
        if isinstance(item, Path):
            p = item
        else:
            item_str = str(item).strip()
            if not item_str:
                continue
            p = Path(item_str)
        if not p.is_absolute():
            p = (base / p).resolve()
        else:
            p = p.resolve()

        try:
            rkey = p.resolve()
        except Exception:
            rkey = p.absolute()

        if rkey in seen:
            continue

        if p.is_dir():
            seen.add(rkey)
            try:
                expanded = resolve_image_targets(p, base_dir=base)
                for exp in expanded:
                    add_target_path(exp)
            except Exception as e:
                failures.append({
                    "file": str(p),
                    "name": p.name,
                    "code": "TARGET_RESOLUTION_ERROR",
                    "reason": str(e),
                })
        else:
            add_target_path(p)

    return target_files, failures


def check_images(
    targets: list[Path | str] | Path | str | None = None,
    size: tuple[int, int] | None = None,
    verbose: bool = True,
    base_dir: str | Path | None = None,
) -> BatchResult:
    """客观质量门禁判定：验证目标图片是否存在未抹平接缝、尺寸或格式损坏。"""
    target_files, failures = _resolve_and_dedup_targets(targets, base_dir=base_dir)

    results: list[dict] = []
    failed_seams: list[str] = []
    unreadable: list[str] = []
    dimension_mismatches: list[str] = []

    for f in failures:
        unreadable.append(f["reason"])

    for p in target_files:
        if not p.is_file():
            reason = f"源图片文件不存在: {p}"
            unreadable.append(f"{p.name} (空文件或不存在)")
            failures.append({
                "file": str(p),
                "name": p.name,
                "code": "FILE_NOT_FOUND",
                "reason": reason,
            })
            continue

        if p.stat().st_size == 0:
            reason = f"空图片文件 (0 字节): {p.name}"
            unreadable.append(f"{p.name} (空文件或不存在)")
            failures.append({
                "file": str(p),
                "name": p.name,
                "code": "EMPTY_FILE",
                "reason": reason,
            })
            continue

        try:
            with Image.open(p) as src_im:
                im = src_im.convert("RGB")
        except Exception as e:
            reason = f"无法读取或解析图片: {e}"
            unreadable.append(f"{p.name} ({e})")
            failures.append({
                "file": str(p),
                "name": p.name,
                "code": "UNREADABLE_IMAGE",
                "reason": reason,
            })
            continue

        w, h = im.size
        seam_x = detect_seam(im)
        dim_mismatch = False
        if size is not None:
            tw, th = size
            if (w, h) != (tw, th):
                dim_mismatch = True
                dimension_mismatches.append(f"{p.name} ({w}x{h} vs 期望 {tw}x{th})")

        if seam_x is not None:
            failed_seams.append(f"{p.name} (x={seam_x})")

        if seam_x is not None and dim_mismatch:
            failures.append({
                "file": str(p),
                "name": p.name,
                "code": "SEAM_AND_DIMENSION_MISMATCH",
                "reason": f"{p.name} 存在残留接缝 (x={seam_x}) 且尺寸不符合预期 ({w}x{h} vs 期望 {size[0]}x{size[1]})",
            })
        elif seam_x is not None:
            failures.append({
                "file": str(p),
                "name": p.name,
                "code": "SEAM_DETECTED",
                "reason": f"{p.name} 存在残留接缝 (x={seam_x})",
            })
        elif dim_mismatch:
            failures.append({
                "file": str(p),
                "name": p.name,
                "code": "DIMENSION_MISMATCH",
                "reason": f"{p.name} 尺寸不匹配: {w}x{h} (期望 {size[0]}x{size[1]})",
            })
        else:
            results.append({
                "file": str(p),
                "name": p.name,
                "size": f"{w}x{h}",
                "seam": seam_x,
            })

    total_count = len(results) + len(failures)
    success_count = len(results)
    failure_count = len(failures)
    partial_success = (success_count > 0 and failure_count > 0)
    ok = (total_count > 0 and failure_count == 0)

    res = BatchResult({
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "total": total_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "partial_success": partial_success,
        "is_partial_success": partial_success,
        "failures": failures,
        "failed_items": failures,
        "unreadable": unreadable,
        "failed_seams": failed_seams,
        "dimension_mismatches": dimension_mismatches,
        "items": results,
    })

    if verbose:
        print("=" * 60)
        print("🔍 运行 PPT-Studio 配图客观后处理门禁")
        print(f"   目标数量: {total_count} 张图片")
        print("=" * 60)
        if not unreadable:
            print(f"  [✓] 文件实体与完整性   : {total_count} 张图片均有效且可读取")
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
            print("  [门禁] ✓ 配图客观后处理门禁通过")
        else:
            print("❌ 门禁未通过")
        print("=" * 60)

    return res


def run_qa_prepared_images(
    targets: list[Path | str] | Path | str | None = None,
    size: tuple[int, int] | None = None,
    verbose: bool = True,
    base_dir: str | Path | None = None,
) -> bool:
    """运行 PPT-Studio 配图客观后处理门禁校验。

    :param targets: 目标图片、目录、项目路径或图片列表（默认自发现）
    :param size: 期望尺寸 (宽, 高) 元组，例如 (2560, 1440)
    :param verbose: 是否输出人类可读的门禁检验报告（默认 True）
    :param base_dir: 基础工作目录（可选）
    :return: 门禁是否通过 (True / False)
    """
    res = check_images(targets, size=size, verbose=verbose, base_dir=base_dir)
    return bool(res.get("ok"))


qa_prepared_images = run_qa_prepared_images
qa_single_prepared_image = check_images
run_qa_single_prepared_image = check_images


def prepare_agnes_images(
    targets: str | Path | list[str | Path] | None = None,
    out: str | Path | None = None,
    size: tuple[int, int] | str = (2560, 1440),
    brightness: float = 1.0,
    seam: str = "auto",
    apply: bool = False,
    no_backup: bool = False,
    check: bool = False,
    verbose: bool = False,
    base_dir: str | Path | None = None,
) -> BatchResult:
    """批量或单张执行 Agnes 配图后处理（裁切、去接缝、亮度调整），支持质量门禁校验与可选写盘。

    :param targets: 目标图片文件、图片目录、项目路径或图片列表（默认自发现）
    :param out: 单张处理时的显式输出路径或批量输出目录（可选）
    :param size: 目标分辨率元组 (宽, 高) 或字符串 "2560x1440"
    :param brightness: 亮度缩放系数 (默认: 1.0)
    :param seam: 接缝处理模式: auto | off | 列号[,列号] (默认: auto)
    :param apply: 是否原地写盘（默认 False 仅预演）
    :param no_backup: 写盘时是否跳过备份原图
    :param check: 处理后是否执行客观质量门禁校验 (check_images)
    :param verbose: 是否打印处理日志
    :param base_dir: 基础目录，用于相对路径解析（可选）
    :return: 包含总数、成功数、失败数、定位明细与报告的结构化结果 (BatchResult)
    """
    tw, th = parse_size(size) if isinstance(size, str) else size
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    target_files, failures = _resolve_and_dedup_targets(targets, base_dir=base)

    out_path = Path(out) if out else None
    if out_path and not out_path.is_absolute():
        out_path = (base / out_path).resolve()
    single_out = None
    batch_out_dir = None
    if out_path:
        if len(target_files) == 1 and not out_path.is_dir() and (out_path.suffix or not out_path.exists()):
            single_out = out_path
        else:
            batch_out_dir = out_path
            if apply:
                batch_out_dir.mkdir(parents=True, exist_ok=True)

    reports: list[dict] = []
    processed_targets: list[Path] = []

    for src_p in target_files:
        if not src_p.is_file():
            failures.append({
                "file": str(src_p),
                "name": src_p.name,
                "code": "FILE_NOT_FOUND",
                "reason": f"源图片文件不存在: {src_p}",
            })
            if verbose:
                print(f"[!] 找不到图片文件: {src_p}", file=sys.stderr)
            continue

        if src_p.stat().st_size == 0:
            failures.append({
                "file": str(src_p),
                "name": src_p.name,
                "code": "EMPTY_FILE",
                "reason": f"空图片文件 (0 字节): {src_p.name}",
            })
            if verbose:
                print(f"[!] 图片文件为空: {src_p}", file=sys.stderr)
            continue

        if single_out:
            dest_p = single_out if apply else None
            record_out = single_out
        elif batch_out_dir:
            dest_p = batch_out_dir / src_p.name if apply else None
            record_out = batch_out_dir / src_p.name
        elif apply:
            dest_p = src_p
            record_out = src_p
        else:
            dest_p = None
            record_out = src_p

        if apply and not no_backup and dest_p == src_p:
            bak = src_p.parent / f"_pre_{src_p.name}"
            if not bak.exists():
                shutil.copy2(src_p, bak)

        try:
            rep = prepare(src_p, dest_p, size=(tw, th), brightness=brightness, seam=seam)
            rep["name"] = src_p.name
            rep["file"] = str(src_p)
            rep["applied"] = apply
            rep["out"] = str(record_out)
            reports.append(rep)
            processed_targets.append(record_out if apply else src_p)

            if verbose:
                seam_msg = (
                    f"接缝@{rep['seam']} ✓已抹平"
                    if (rep.get("seam") and apply)
                    else (f"接缝@{rep['seam']} 需抹平" if rep.get("seam") else "无接缝")
                )
                mode_tag = "(已写盘)" if apply else "[预演]"
                print(f"{mode_tag} {src_p.name}  {rep['src']} → {rep['out']}  {rep['kb']}KB  [{seam_msg}]")
        except Exception as e:
            failures.append({
                "file": str(src_p),
                "name": src_p.name,
                "code": "PREPARE_ERROR",
                "reason": f"后处理执行失败: {e}",
            })
            if verbose:
                print(f"[!] 处理图片 {src_p.name} 失败: {e}", file=sys.stderr)

    if check:
        chk_targets = processed_targets if apply else target_files
        gate_res = check_images(chk_targets, size=(tw, th), verbose=verbose, base_dir=base)
        if not gate_res["ok"]:
            issues_summary = []
            if gate_res.get("unreadable"):
                issues_summary.extend(gate_res["unreadable"])
            if gate_res.get("failed_seams"):
                issues_summary.extend([f"残留接缝: {s}" for s in gate_res["failed_seams"]])
            if gate_res.get("dimension_mismatches"):
                issues_summary.extend([f"尺寸偏差: {s}" for s in gate_res["dimension_mismatches"]])
            raise RuntimeError(f"配图客观后处理门禁未通过: {'; '.join(issues_summary)}")

    total_count = len(reports) + len(failures)
    success_count = len(reports)
    failure_count = len(failures)
    partial_success = (success_count > 0 and failure_count > 0)
    ok = (total_count > 0 and failure_count == 0)

    return BatchResult({
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "total": total_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "partial_success": partial_success,
        "is_partial_success": partial_success,
        "failures": failures,
        "failed_items": failures,
        "items": reports,
        "reports": reports,
    })


prepare_images = prepare_agnes_images


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    ap = argparse.ArgumentParser(description="Agnes 配图后处理：裁 16:9 + 去接缝 + 压暗")
    ap.add_argument("raw", nargs="*", default=[], help="原始输入图片路径、图片目录或项目路径（默认自发现，支持多个目标）")
    ap.add_argument("--base-dir", default=None, help="指定基础工作目录 (默认: 当前工作目录)")
    ap.add_argument("--out", dest="out_flag", default=None, help="显式指定输出图片路径或目录")
    ap.add_argument("--size", default="2560x1440", help="目标分辨率 (默认: 2560x1440)")
    ap.add_argument("--brightness", type=float, default=1.0, help="亮度缩放系数 (默认: 1.0)")
    ap.add_argument("--seam", default="auto", help="接缝处理模式: auto | off | 列号[,列号] (默认: auto)")
    ap.add_argument("--apply", action="store_true", help="写盘模式（写盘前自动备份 _pre_<name>.png），不加则仅预演")
    ap.add_argument("--no-backup", action="store_true", help="写盘时跳过创建 _pre_<name>.png 备份")
    ap.add_argument("--manifest", nargs="?", const="", default=None, help="基于 image_prompts.json 清单批量执行对应 postprocess 参数")
    ap.add_argument("--check", action="store_true", help="客观门禁检验：扫描目标图片是否存在未抹平接缝或画幅异常")
    ap.add_argument("--json", action="store_true", help="以 JSON 格式输出处理或质检结果")
    ap.add_argument("--verbose", "-v", action="store_true", default=True, help="详细日志输出（默认开启）")
    ap.add_argument("--quiet", "-q", action="store_true", help="静默模式（仅通过退出码返回结果）")
    a = ap.parse_args(argv)
    verbose = not a.quiet if a.quiet else a.verbose
    effective_base = Path(a.base_dir).resolve() if a.base_dir else (Path(base_dir).resolve() if base_dir else Path.cwd().resolve())

    # 1. 门禁模式
    if a.check:
        try:
            tw, th = parse_size(a.size) if a.size else (2560, 1440)
        except ValueError as e:
            if verbose:
                print(f"[!] {e}", file=sys.stderr)
            return 1
        raw_args = argv if argv is not None else sys.argv[1:]
        target_size = (tw, th) if "--size" in raw_args else None
        check_targets = a.raw if len(a.raw) > 1 else (a.raw[0] if len(a.raw) == 1 else None)

        if a.json:
            # 显式 opt-in 机器可读模式：直接序列化 check_images 结构化结果
            # stdout 纯净，不混入人类日志
            res = check_images(check_targets, size=target_size, verbose=False, base_dir=effective_base)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0 if res["ok"] else 1
        else:
            try:
                targets = resolve_image_targets(check_targets, base_dir=effective_base)
                res = check_images(targets, size=target_size, verbose=verbose, base_dir=effective_base)
                return 0 if res["ok"] else 1
            except Exception as e:
                if verbose:
                    print(f"[!] 门禁检查失败: {e}", file=sys.stderr)
                return 1

    # 2. 清单模式 (--manifest)
    if a.manifest is not None:
        raw_manifest_arg = a.manifest if a.manifest != "" else (a.raw[0] if a.raw else None)
        try:
            mf_path = resolve_manifest_target(raw_manifest_arg, base_dir=effective_base)
        except (FileNotFoundError, ValueError) as e:
            if verbose:
                print(f"[!] {e}", file=sys.stderr)
            return 1
        try:
            mf_data = json.loads(mf_path.read_text(encoding="utf-8"))
        except Exception as e:
            if verbose:
                print(f"[!] 读取或解析清单失败: {e}", file=sys.stderr)
            return 1

        img_dir = mf_path.parent if mf_path.parent.name == "images" else mf_path.parent / "images"
        items = mf_data.get("items") or []
        if not a.json and verbose:
            print(f"· 基于清单 {mf_path.name} 处理 {len(items)} 项配图...")
        ok_count = 0
        reports = []
        for it in items:
            fn = it.get("filename")
            if not fn:
                continue
            src_file = img_dir / fn
            if not src_file.is_file():
                if not a.json and verbose:
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
                if not a.json and verbose:
                    seam_msg = f"接缝@{rep['seam']} ✓已抹平" if rep["seam"] else "无接缝"
                    print(f"✓ {fn}  {rep['src']} → {rep['out']}  {rep['kb']}KB  [{seam_msg}] (已写盘)")
            else:
                rep = prepare(src_file, None, size=cfg["size"], brightness=cfg["brightness"], seam=cfg["seam"])
                rep["name"] = fn
                reports.append(rep)
                if not a.json and verbose:
                    seam_msg = f"接缝@{rep['seam']} 需抹平" if rep["seam"] else "无接缝"
                    print(f"[预演] {fn}  {rep['src']} → {rep['out']}  [{seam_msg}]")
            ok_count += 1
        if not a.apply and not a.json and verbose:
            print("[提示] 当前为预演模式（未写盘），加 --apply 执行写盘")
        if a.json:
            print(json.dumps(reports, ensure_ascii=False, indent=2))
        return 0

    # 3. 常规图片处理
    output_target = a.out_flag
    raw_targets = a.raw
    if not output_target and len(a.raw) == 2 and not a.apply:
        # 传统两参数调用: <raw.png> <out.png>
        raw_targets = [a.raw[0]]
        output_target = a.raw[1]
    elif not output_target and len(a.raw) == 1:
        raw_targets = a.raw[0]
    elif not output_target and len(a.raw) == 0:
        raw_targets = None
    try:
        tw, th = parse_size(a.size)
    except ValueError as e:
        if verbose:
            print(f"[!] {e}", file=sys.stderr)
        return 1

    if a.brightness < 0:
        if verbose:
            print(f"[!] 亮度系数必须 >= 0，当前为: {a.brightness}", file=sys.stderr)
        return 1

    seam_norm = a.seam.strip().lower()
    if seam_norm not in ("auto", "off"):
        parts = [p.strip() for p in a.seam.split(",") if p.strip()]
        if not parts:
            if verbose:
                print(f"[!] 接缝参数格式无效: '{a.seam}'", file=sys.stderr)
            return 1
        for p in parts:
            try:
                int(p)
            except ValueError:
                if verbose:
                    print(f"[!] 无效的接缝列号: '{p}' (完整参数: '{a.seam}')", file=sys.stderr)
                return 1

    if a.json:
        # --json 必须直接序列化当前 prepare_images 的结构化结果，不重新实现统计逻辑
        # stdout 不混入人类日志
        res = prepare_images(
            targets=raw_targets,
            out=output_target,
            size=(tw, th),
            brightness=a.brightness,
            seam=a.seam,
            apply=a.apply or bool(output_target),
            no_backup=a.no_backup,
            check=False,
            verbose=False,
            base_dir=effective_base,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 1

    # 默认不带 --json 的 CLI 输出必须完全保持现状
    try:
        targets = resolve_image_targets(raw_targets, base_dir=effective_base)
    except (FileNotFoundError, ValueError) as e:
        if verbose:
            print(f"[!] {e}", file=sys.stderr)
        return 1

    # 单张且明确给了目标输出文件（传统两参数调用）
    if len(targets) == 1 and output_target:
        src_p = targets[0]
        out_p = Path(output_target)
        if not out_p.is_absolute():
            out_p = (effective_base / out_p).resolve()
        try:
            rep = prepare(src_p, out_p, (tw, th), a.brightness, a.seam)
        except (FileNotFoundError, ValueError) as e:
            if verbose:
                print(f"[!] {e}", file=sys.stderr)
            return 1
        except Exception as e:
            if verbose:
                print(f"[!] 处理失败: {e}", file=sys.stderr)
            return 1

        if verbose:
            seam_txt = (
                f"接缝@{','.join(str(c) for c in rep['seam'])} ✓已抹平"
                if isinstance(rep["seam"], list)
                else (f"接缝@x={rep['seam']} ✓已抹平" if rep["seam"] else "无接缝")
            )
            print(f"✓ {out_p.name}  {rep['src']} → {rep['out']}  {rep['kb']}KB  [{seam_txt}]")
        return 0

    # 批量或单张原地处理
    reports = []
    has_failure = False
    for src_p in targets:
        if a.apply:
            if not a.no_backup:
                bak = src_p.parent / f"_pre_{src_p.name}"
                if not bak.exists():
                    shutil.copy2(src_p, bak)
            try:
                rep = prepare(src_p, src_p, (tw, th), a.brightness, a.seam)
                rep["name"] = src_p.name
                reports.append(rep)
                if verbose:
                    seam_txt = f"接缝@{rep['seam']} ✓已抹平" if rep["seam"] else "无接缝"
                    print(f"✓ {src_p.name}  {rep['src']} → {rep['out']}  {rep['kb']}KB  [{seam_txt}] (已写盘)")
            except Exception as e:
                has_failure = True
                if verbose:
                    print(f"[!] 处理图片 {src_p.name} 失败: {e}", file=sys.stderr)
        else:
            try:
                rep = prepare(src_p, None, (tw, th), a.brightness, a.seam)
                rep["name"] = src_p.name
                reports.append(rep)
                if verbose:
                    seam_txt = f"接缝@{rep['seam']} 需抹平" if rep["seam"] else "无接缝"
                    print(f"[预演] {src_p.name}  {rep['src']} → {rep['out']}  [{seam_txt}]")
            except Exception as e:
                has_failure = True
                if verbose:
                    print(f"[!] 处理图片 {src_p.name} 失败: {e}", file=sys.stderr)

    if not a.apply and verbose:
        print("[提示] 当前为预演模式（未写盘），加 --apply 执行写盘")
    return 0 if not has_failure else 1


if __name__ == "__main__":
    sys.exit(main())
