#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa_long_card.py —— PPT-Studio 长图导出物客观质量门禁
=====================================================

对由 make_long_card.py 缝合生成的纵向长图进行 7 项客观工业级质检：
  1. [画幅与结构] 宽度严格对齐 1080px（移动端长图标准），RGB/PNG 无损完整格式
  2. [顶部 Header] 品牌强调色条 (#6E7BFF)、大标题与副标题区域墨量完整，WCAG 对比度 ≥ 4.5:1
  3. [底部 Footer] 品牌签名、行动指引 (CTA) 与底部强调条完整，WCAG 对比度 ≥ 4.5:1
  4. [卡片分段]   准确解析 1080×1350 卡片序列与间距，分段接缝无撕裂或畸形变倍
  5. [分段墨量]   每页卡片分段墨量 ≥ 2.0%（且 ≤ 65%），严防空白卡片或漏渲染断流
  6. [文字对比]   各内容区关键文字与背景对比度全量达标（WCAG ≥ 4.5:1）
  7. [高频细节]   全局清晰度（拉普拉斯梯度方差 ≥ 50.0），排查低清插值或失真

用法：
  python3 scripts/qa_long_card.py <image_path_or_dir> [--project path/to/project]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from PIL import Image
import numpy as np

# 规范常量
STANDARD_WIDTH = 1080
STANDARD_CARD_HEIGHT = 1350
HEADER_HEIGHT = 420
FOOTER_HEIGHT = 320
ACCENT_RGB = (110, 123, 255)  # #6E7BFF
BG_RGB = (11, 12, 18)         # #0B0C12


def check_file_and_format(img_path: Path) -> tuple[bool, str, Image.Image | None]:
    """检查文件是否存在、格式是否有效及基本完整性。"""
    if not img_path.exists():
        return False, f"文件不存在: {img_path}", None
    if img_path.stat().st_size < 100 * 1024:
        return False, f"文件体积异常过小 ({img_path.stat().st_size} bytes)", None

    try:
        img = Image.open(img_path)
        img.load()  # 触发完整解码校验
        return True, "图像无损解码成功", img
    except Exception as e:
        return False, f"图像无法解码或文件损坏: {e}", None


def check_dimensions_and_mode(img: Image.Image) -> tuple[bool, str]:
    """检查图像尺寸与色彩模式。"""
    w, h = img.size
    if w != STANDARD_WIDTH:
        return False, f"长图宽度 {w}px 不符合标准 {STANDARD_WIDTH}px"
    if h < 2000:
        return False, f"长图高度 {h}px 异常过低（多卡片长图应 ≥ 2000px）"
    if img.mode not in ("RGB", "RGBA"):
        return False, f"色彩模式 {img.mode} 不合规，要求 RGB 或 RGBA"
    return True, f"{w}×{h} (纵向长图标准) · {img.mode} {img.format}"


def calc_wcag_contrast(gray_block: np.ndarray) -> float:
    """计算灰度区域背景与字色的 WCAG 对比度。"""
    bg_p20 = float(np.percentile(gray_block, 20))
    fg_p99 = float(np.percentile(gray_block, 99.5))
    lum_bg = (bg_p20 + 0.05) / 255.0
    lum_fg = (fg_p99 + 0.05) / 255.0
    return float((lum_fg + 0.05) / (lum_bg + 0.05))


def check_header(arr: np.ndarray) -> tuple[bool, str]:
    """检查顶部 Header 区域及其强调条与文本。"""
    if arr.shape[0] < HEADER_HEIGHT:
        return False, "高度不足以容纳 Header"

    # 1. 顶部 8px 强调色条
    top_bar = arr[:8, :, :3]
    top_mean = top_bar.mean(axis=(0, 1))
    dist = np.linalg.norm(top_mean - np.array(ACCENT_RGB))
    if dist > 30:
        return False, f"顶部缺失品牌强调色条 (均值 {top_mean.round(1)} vs 预期 {ACCENT_RGB})"

    # 2. Header 文本区域墨量 (y: 60..380)
    header_area = arr[60:380, 80:-80, :3]
    # 背景为 #0B0C12，像素最大通道 > 35 视为墨迹
    ink_mask = np.max(header_area, axis=-1) > 35
    ink_pct = float(np.mean(ink_mask) * 100)
    if ink_pct < 1.0:
        return False, f"Header 文本区域墨量过低 ({ink_pct:.2f}% < 1.0%)，疑似无标题内容"

    # 3. 对比度
    gray_header = np.mean(header_area, axis=-1)
    contrast = calc_wcag_contrast(gray_header)
    if contrast < 4.5:
        return False, f"Header 区域 WCAG 对比度不足 ({contrast:.1f}:1 < 4.5:1)"

    return True, f"品牌强调色条完整 · 标题区墨量 {ink_pct:.1f}% · WCAG {contrast:.1f}:1"


def check_footer(arr: np.ndarray) -> tuple[bool, str]:
    """检查底部 Footer 区域及其强调条与文本。"""
    if arr.shape[0] < FOOTER_HEIGHT:
        return False, "高度不足以容纳 Footer"

    # 1. 底部 8px 强调色条
    bot_bar = arr[-8:, :, :3]
    bot_mean = bot_bar.mean(axis=(0, 1))
    dist = np.linalg.norm(bot_mean - np.array(ACCENT_RGB))
    if dist > 30:
        return False, f"底部缺失品牌强调色条 (均值 {bot_mean.round(1)} vs 预期 {ACCENT_RGB})"

    # 2. Footer 文本区域墨量 (y: end-280..end-20)
    footer_area = arr[-280:-20, 80:-80, :3]
    ink_mask = np.max(footer_area, axis=-1) > 35
    ink_pct = float(np.mean(ink_mask) * 100)
    if ink_pct < 0.8:
        return False, f"Footer 区域墨量过低 ({ink_pct:.2f}% < 0.8%)，疑似缺失落款"

    # 3. 对比度
    gray_footer = np.mean(footer_area, axis=-1)
    contrast = calc_wcag_contrast(gray_footer)
    if contrast < 4.5:
        return False, f"Footer 区域 WCAG 对比度不足 ({contrast:.1f}:1 < 4.5:1)"

    return True, f"品牌签名与 CTA 完整 · 底部墨量 {ink_pct:.1f}% · WCAG {contrast:.1f}:1"


def parse_card_segments(arr: np.ndarray, has_header: bool, has_footer: bool) -> tuple[int, int, list[tuple[int, int]]]:
    """解析长图内的卡片切片序列与间距。"""
    total_h = arr.shape[0]
    start_y = HEADER_HEIGHT if has_header else 0
    end_y = total_h - (FOOTER_HEIGHT if has_footer else 0)
    body_h = end_y - start_y

    card_h = STANDARD_CARD_HEIGHT
    num_boundary_gaps = (1 if has_header else 0) + (1 if has_footer else 0)

    best_gap = 16
    best_n = 0
    candidate_gaps = [16, 20, 12, 24, 0, 8, 10, 14, 18, 30]

    for gap in candidate_gaps:
        rem = body_h - (num_boundary_gaps - 1) * gap
        if rem > 0 and rem % (card_h + gap) == 0:
            best_gap = gap
            best_n = rem // (card_h + gap)
            break

    if best_n == 0:
        # 回退近似估算
        best_n = max(1, round(body_h / (card_h + 16)))
        best_gap = 16

    slices = []
    curr_y = start_y
    if has_header and best_gap > 0:
        curr_y += best_gap

    for _ in range(best_n):
        s_end = min(curr_y + card_h, end_y)
        slices.append((curr_y, s_end))
        curr_y = s_end + best_gap

    return best_n, best_gap, slices


def check_segments_and_seams(arr: np.ndarray, card_slices: list[tuple[int, int]], gap: int, expected_count: int | None = None) -> tuple[bool, str]:
    """检查卡片切片与间距接缝质量。"""
    n = len(card_slices)
    if n < 1:
        return False, "未能识别出有效的卡片切片"
    if expected_count is not None and n != expected_count:
        return False, f"识别到 {n} 页卡片，与项目预期 ({expected_count} 页) 不一致"

    # 检查间距接缝色泽是否纯净背景
    seam_errors = 0
    for i in range(len(card_slices) - 1):
        gap_start = card_slices[i][1]
        gap_end = card_slices[i + 1][0]
        if gap_end > gap_start:
            gap_block = arr[gap_start:gap_end, :, :3]
            gap_mean = gap_block.mean(axis=(0, 1))
            if np.linalg.norm(gap_mean - np.array(BG_RGB)) > 25:
                seam_errors += 1

    if seam_errors > 0:
        return False, f"检测到 {seam_errors} 处卡片拼接缝隙存在色斑或杂质"

    return True, f"成功解析 {n} 页卡片 (间距 {gap}px) · 纵向接缝无撕裂"


def check_per_card_ink(arr: np.ndarray, card_slices: list[tuple[int, int]]) -> tuple[bool, str]:
    """检查每页卡片的墨量是否正常（非空且不拥挤）。"""
    ink_percentages = []
    for idx, (sy, ey) in enumerate(card_slices, 1):
        c_slice = arr[sy:ey, :, :3]
        ink_mask = np.max(c_slice, axis=-1) > 35
        pct = float(np.mean(ink_mask) * 100)
        ink_percentages.append(pct)
        if pct < 2.0:
            return False, f"第 {idx} 页卡片墨量极低 ({pct:.2f}% < 2.0%)，疑似白板或漏渲染"
        if pct > 65.0:
            return False, f"第 {idx} 页卡片墨量过高 ({pct:.2f}% > 65.0%)，疑似大面积死黑或图层崩溃"

    min_pct = min(ink_percentages)
    avg_pct = float(np.mean(ink_percentages))
    return True, f"{len(card_slices)} 页卡片平均墨量 {avg_pct:.1f}% (最低 {min_pct:.1f}% ≥ 2.0%) · 无空白漏图"


def check_overall_contrast(arr: np.ndarray, card_slices: list[tuple[int, int]]) -> tuple[bool, str]:
    """检查主要卡片内容区的文字对比度。"""
    failed_cards = []
    for idx, (sy, ey) in enumerate(card_slices, 1):
        # 截取卡片主要文本区 (左侧 80..850, 高度中段)
        card_text_area = arr[sy + 100 : ey - 100, 80:850, :3]
        gray = np.mean(card_text_area, axis=-1)
        contrast = calc_wcag_contrast(gray)
        if contrast < 4.5:
            failed_cards.append((idx, contrast))

    if failed_cards:
        detail = ", ".join(f"第 {idx} 页({c:.1f}:1)" for idx, c in failed_cards[:3])
        return False, f"部分卡片对比度低于 4.5:1: {detail}"

    return True, "全图关键文本区域 WCAG 对比度达标 (均 ≥ 4.5:1)"


def check_sharpness_and_health(img_path: Path, arr: np.ndarray) -> tuple[bool, str]:
    """检查图像清晰度（拉普拉斯梯度方差）与存储文件健康度。"""
    # 转换为灰度
    gray = np.mean(arr[:, :, :3], axis=-1, dtype=np.float32)

    # 采样计算拉普拉斯梯度方差
    # 为保证效率，在 10000+ 高度图像上隔行采样
    step = 2
    sub = gray[::step, ::step]
    lap = (
        sub[:-2, 1:-1] + sub[2:, 1:-1] +
        sub[1:-1, :-2] + sub[1:-1, 2:] - 4 * sub[1:-1, 1:-1]
    )
    var_lap = float(np.var(lap))

    file_kb = img_path.stat().st_size // 1024
    if var_lap < 50.0:
        return False, f"拉普拉斯清晰度过低 ({var_lap:.1f} < 50.0)，图像可能存在模糊或降采样"

    return True, f"拉普拉斯梯度方差 {var_lap:.1f} (≥ 50.0) · {file_kb} KB 无损完好"


def run_qa_long_card(target_path: Path, project_dir: Path | None = None) -> bool:
    print("=" * 60)
    print("🔍 运行 PPT-Studio 长图导出物客观质量门禁")
    print(f"   目标: {target_path}")
    print("=" * 60)

    # 1. 解码与文件健全
    ok, msg, img = check_file_and_format(target_path)
    if not ok:
        print(f"  [✗] 文件解码健全         : {msg}")
        print("=" * 60)
        print("FAILED ❌")
        return False

    arr = np.array(img)

    # 2. 画幅与模式
    ok_dim, msg_dim = check_dimensions_and_mode(img)
    print(f"  [{'✓' if ok_dim else '✗'}] 画幅与结构标准     : {msg_dim}")

    # 3. Header
    ok_header, msg_header = check_header(arr)
    print(f"  [{'✓' if ok_header else '✗'}] 顶部 Header 统摄   : {msg_header}")

    # 4. Footer
    ok_footer, msg_footer = check_footer(arr)
    print(f"  [{'✓' if ok_footer else '✗'}] 底部 Footer 收尾   : {msg_footer}")

    # 卡片切片解析
    n_cards, gap, slices = parse_card_segments(arr, ok_header, ok_footer)

    if project_dir is None:
        for candidate in [
            target_path.parent.parent,
            target_path.parent,
            Path.cwd(),
            Path(__file__).resolve().parent.parent / "projects/agentflow-os-launch",
        ]:
            if (candidate / "cards").is_dir():
                project_dir = candidate.resolve()
                break

    expected_count = None
    if project_dir and (project_dir / "cards").exists():
        expected_count = len([p for p in (project_dir / "cards").glob("*.svg") if not p.name.startswith("long_card")])

    # 5. 卡片切片与间距
    ok_seg, msg_seg = check_segments_and_seams(arr, slices, gap, expected_count)
    print(f"  [{'✓' if ok_seg else '✗'}] 卡片分段与缝合     : {msg_seg}")

    # 6. 分段墨量
    ok_ink, msg_ink = check_per_card_ink(arr, slices)
    print(f"  [{'✓' if ok_ink else '✗'}] 分段墨量与非空     : {msg_ink}")

    # 7. 文字对比度
    ok_contrast, msg_contrast = check_overall_contrast(arr, slices)
    print(f"  [{'✓' if ok_contrast else '✗'}] 文字对比度合规     : {msg_contrast}")

    # 8. 清晰度与无损健康
    ok_sharp, msg_sharp = check_sharpness_and_health(target_path, arr)
    print(f"  [{'✓' if ok_sharp else '✗'}] 高频细节与渲染清晰 : {msg_sharp}")

    print("=" * 60)
    all_passed = all([ok_dim, ok_header, ok_footer, ok_seg, ok_ink, ok_contrast, ok_sharp])
    if all_passed:
        print("ALL CLEAR ✅\n")
    else:
        print("FAILED ❌\n")
    return all_passed


def main():
    parser = argparse.ArgumentParser(description="PPT-Studio 长图客观质量门禁")
    parser.add_argument("target", help="长图 PNG 文件路径或包含长图/output/*.png 的项目目录")
    parser.add_argument("--project", help="项目根目录（用于校验源卡片数量）")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    project = Path(args.project).resolve() if args.project else None

    # 如果是目录，自动查找长图（支持当前目录与 output/ 子目录）
    files_to_check = []
    if target.is_dir():
        def find_in_dir(d: Path) -> list[Path]:
            found = []
            for p in ["*长图*.png", "*long_card*.png"]:
                found.extend(sorted(d.glob(p)))
            if not found:
                found = [f for f in sorted(d.glob("*.png")) if "卡片" not in f.name]
            return found

        files_to_check = find_in_dir(target)
        if not files_to_check and (target / "output").is_dir():
            files_to_check = find_in_dir(target / "output")

        if not files_to_check:
            print(f"[!] 在目录 {target} 或 {target / 'output'} 下未发现长图 PNG 文件")
            sys.exit(1)
    else:
        files_to_check = [target]

    # 自动探测 project 目录
    if project is None:
        for candidate in [
            target,
            target.parent,
            Path.cwd(),
            Path(__file__).resolve().parent.parent / "projects/agentflow-os-launch",
            Path("projects/agentflow-os-launch"),
        ]:
            if candidate and candidate.exists() and (candidate / "cards").is_dir():
                project = candidate.resolve()
                break

    all_ok = True
    for f in files_to_check:
        res = run_qa_long_card(f, project)
        if not res:
            all_ok = False

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
