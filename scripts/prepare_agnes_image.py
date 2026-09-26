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
                                 [--brightness 1.0] [--seam-fix auto|off|L,R]
"""

from __future__ import annotations

import argparse
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
    out: Path | str,
    size: tuple[int, int] = (2560, 1440),
    brightness: float = 1.0,
    seam: str = "auto",
) -> dict:
    raw_path = Path(raw)
    out_path = Path(out)
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

    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path, "PNG", optimize=True)
    report["out"] = f"{im.size[0]}x{im.size[1]}"
    report["kb"] = out_path.stat().st_size // 1024
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Agnes 配图后处理：裁 16:9 + 去接缝 + 压暗")
    ap.add_argument("raw", help="原始输入图片路径")
    ap.add_argument("out", help="处理后输出图片路径")
    ap.add_argument("--size", default="2560x1440", help="目标分辨率 (默认: 2560x1440)")
    ap.add_argument("--brightness", type=float, default=1.0, help="亮度缩放系数 (默认: 1.0)")
    ap.add_argument("--seam", default="auto", help="接缝处理模式: auto | off | 列号[,列号] (默认: auto)")
    a = ap.parse_args(argv)

    try:
        tw, th = parse_size(a.size)
        rep = prepare(Path(a.raw), Path(a.out), (tw, th), a.brightness, a.seam)
    except (FileNotFoundError, ValueError) as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[!] 处理失败: {e}", file=sys.stderr)
        return 1

    if rep["seam"]:
        if isinstance(rep["seam"], list):
            seam_txt = f"接缝@{','.join(str(c) for c in rep['seam'])} ✓已抹平"
        else:
            seam_txt = f"接缝@x={rep['seam']} ✓已抹平"
    else:
        seam_txt = "无接缝"
    print(f"✓ {Path(a.out).name}  {rep['src']} → {rep['out']}  {rep['kb']}KB  [{seam_txt}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
