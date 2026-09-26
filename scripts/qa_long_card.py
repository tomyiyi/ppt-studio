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
import re
import sys
from pathlib import Path

# 确保在未显式激活 .venv 时也能从项目内 .venv 加载依赖
try:
    from PIL import Image
    import numpy as np
except ImportError:
    repo_root = Path(__file__).resolve().parent.parent
    for site_pkg in repo_root.glob(".venv/lib/python*/site-packages"):
        if site_pkg.is_dir() and str(site_pkg) not in sys.path:
            sys.path.insert(0, str(site_pkg))
    from PIL import Image
    import numpy as np

# 规范默认常量
STANDARD_WIDTH = 1080
STANDARD_CARD_HEIGHT = 1350
HEADER_HEIGHT = 420
FOOTER_HEIGHT = 320
ACCENT_RGB = (110, 123, 255)  # #6E7BFF
BG_RGB = (11, 12, 18)         # #0B0C12


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """十六进制颜色转 RGB 元组。"""
    hex_str = hex_str.strip().lstrip("#")
    if len(hex_str) == 6:
        try:
            return (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))
        except ValueError:
            pass
    return ACCENT_RGB


def parse_colors_from_spec_text(content: str) -> dict[str, str]:
    """从规范文本解析颜色定义（支持 colors 段落、YAML 列表、键值对以及行内注释）。"""
    colors: dict[str, str] = {}
    m_sec = re.search(r"^##\s+colors\s*$(.*?)(?=^##\s|\Z)", content, re.S | re.M)
    search_text = m_sec.group(1) if m_sec else content

    for line in search_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 支持:
        # - background: #08090C / background: "#08090C"
        # - bg: #0B0C12 / bg #0B0C12
        # - accent: #6E7BFF / accent #6E7BFF
        # accent_color: #6E7BFF
        m = re.search(r"^[-*]?\s*([a-zA-Z_]\w*)\s*[:=\s]\s*\"?(#[0-9a-fA-F]{6})\"?", line)
        if m:
            key = m.group(1).lower()
            val = m.group(2).upper()
            colors[key] = val

    if "accent" not in colors and "accent_color" not in colors:
        m = re.search(r"\baccent(?:_color)?\s*[:=\s]\s*\"?(#[0-9a-fA-F]{6})\"?", content)
        if m:
            colors["accent"] = m.group(1).upper()

    if "bg" not in colors and "background" not in colors and "bg_color" not in colors:
        m = re.search(r"\b(?:bg|background)(?:_color)?\s*[:=\s]\s*\"?(#[0-9a-fA-F]{6})\"?", content)
        if m:
            colors["bg"] = m.group(1).upper()

    return colors


def load_spec_colors(project_dir: Path | str | None) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """从 card_spec.md 或 spec_lock.md 读取 accent / bg 颜色定义。
    支持 background/bg, YAML 列表, 引号, 行内注释, 以及项目与全局规范动态发现。"""
    accent = ACCENT_RGB
    bg = BG_RGB

    candidate_files: list[Path] = []

    if project_dir:
        p = Path(project_dir).resolve()
        if p.is_file():
            if p.name in ("card_spec.md", "spec_lock.md"):
                candidate_files.append(p)
            candidate_files.append(p.parent / "card_spec.md")
            candidate_files.append(p.parent / "spec_lock.md")
        elif p.is_dir():
            candidate_files.append(p / "card_spec.md")
            candidate_files.append(p / "spec_lock.md")

    repo_root = Path(__file__).resolve().parent.parent
    for base in [Path.cwd(), repo_root]:
        candidate_files.append(base / "card_spec.md")
        candidate_files.append(base / "spec_lock.md")

    for base in [Path.cwd(), repo_root]:
        candidate_files.extend(sorted((base / "projects").glob("*/card_spec.md")))
        candidate_files.extend(sorted((base / "projects").glob("*/spec_lock.md")))

    found_accent: str | None = None
    found_bg: str | None = None

    seen_paths: set[Path] = set()
    for cand in candidate_files:
        if not cand.is_file():
            continue
        cand_resolved = cand.resolve()
        if cand_resolved in seen_paths:
            continue
        seen_paths.add(cand_resolved)

        try:
            content = cand_resolved.read_text(encoding="utf-8")
            parsed = parse_colors_from_spec_text(content)

            if not found_accent:
                acc_val = parsed.get("accent") or parsed.get("accent_color")
                if acc_val:
                    found_accent = acc_val
                    accent = hex_to_rgb(acc_val)

            if not found_bg:
                bg_val = parsed.get("bg") or parsed.get("background") or parsed.get("bg_color")
                if bg_val:
                    found_bg = bg_val
                    bg = hex_to_rgb(bg_val)

            if found_accent and found_bg:
                break
        except (OSError, UnicodeError):
            pass

    return accent, bg


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


def check_dimensions_and_mode(
    img: Image.Image,
    require_header: bool = True,
    require_footer: bool = True,
) -> tuple[bool, str]:
    """检查图像尺寸与色彩模式。"""
    w, h = img.size
    if w != STANDARD_WIDTH:
        return False, f"长图宽度 {w}px 不符合标准 {STANDARD_WIDTH}px"
    min_h = 1350 if (not require_header and not require_footer) else 2000
    if h < min_h:
        return False, f"长图高度 {h}px 异常过低（多卡片长图应 ≥ {min_h}px）"
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


def check_header(arr: np.ndarray, accent_rgb: tuple[int, int, int] = ACCENT_RGB) -> tuple[bool, str]:
    """检查顶部 Header 区域及其强调条与文本。"""
    if arr.shape[0] < HEADER_HEIGHT:
        return False, "高度不足以容纳 Header"

    # 1. 顶部 8px 强调色条
    top_bar = arr[:8, :, :3]
    top_mean = top_bar.mean(axis=(0, 1))
    dist = np.linalg.norm(top_mean - np.array(accent_rgb))
    if dist > 30:
        return False, f"顶部缺失品牌强调色条 (均值 {top_mean.round(1)} vs 预期 {accent_rgb})"

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


def check_footer(arr: np.ndarray, accent_rgb: tuple[int, int, int] = ACCENT_RGB) -> tuple[bool, str]:
    """检查底部 Footer 区域及其强调条与文本。"""
    if arr.shape[0] < FOOTER_HEIGHT:
        return False, "高度不足以容纳 Footer"

    # 1. 底部 8px 强调色条
    bot_bar = arr[-8:, :, :3]
    bot_mean = bot_bar.mean(axis=(0, 1))
    dist = np.linalg.norm(bot_mean - np.array(accent_rgb))
    if dist > 30:
        return False, f"底部缺失品牌强调色条 (均值 {bot_mean.round(1)} vs 预期 {accent_rgb})"

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


def check_segments_and_seams(
    arr: np.ndarray,
    card_slices: list[tuple[int, int]],
    gap: int,
    expected_count: int | None = None,
    bg_rgb: tuple[int, int, int] = BG_RGB,
) -> tuple[bool, str]:
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
            if np.linalg.norm(gap_mean - np.array(bg_rgb)) > 25:
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


def resolve_project_dir(
    project_arg: str | Path | None = None,
    target_path: str | Path | None = None,
    base_dir: str | Path | None = None,
    strict: bool = False,
) -> Path | None:
    """自适应探测包含 cards/ 的项目根目录。

    1. 若显式指定 project_arg：
       - 保留显式路径行为；转换为绝对路径并校验存在性，不存在则抛出 FileNotFoundError。
    2. 若未显式指定 project_arg：
       a. 若传入 target_path，自底向上从其父级目录探测是否存在 cards/ 目录。
       b. 探测 base_dir（默认当前工作目录）本身是否为包含 cards/ 的项目。
       c. 探测 base_dir/projects、base_dir（若其本身名为 projects）或仓库根目录下的 projects/：
          - 收集包含 cards/ 目录的子项目；
          - 若唯一匹配则安全返回；
          - 若存在多个匹配的项目且未显式指定，抛出 ValueError（避免歧义导致规则误用）；
          - 若无匹配项：若 strict 为 True 抛出 FileNotFoundError，否则返回 None。
    """
    if project_arg is not None and str(project_arg).strip() != "":
        p = Path(project_arg)
        if not p.is_absolute() and base_dir is not None:
            p = (Path(base_dir) / p).resolve()
        else:
            p = p.resolve()
        if not p.exists():
            raise FileNotFoundError(f"指定的项目目录不存在: {project_arg}")
        return p

    # 2.a 从 target_path 自底向上探测
    if target_path is not None:
        t = Path(target_path)
        if not t.is_absolute() and base_dir is not None:
            t = (Path(base_dir) / t).resolve()
        else:
            t = t.resolve()
        candidates = [t.parent, t.parent.parent] if t.is_file() else [t, t.parent]
        for cand in candidates:
            if cand.is_dir() and (cand / "cards").is_dir():
                return cand.resolve()

    # 2.b 探测 base_dir / cwd
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    if (base / "cards").is_dir():
        return base

    # 2.c 从 projects/ 目录下安全发现
    candidate_projects_dirs: list[Path] = []
    if base.is_dir() and base.name == "projects":
        candidate_projects_dirs.append(base)
    elif (base / "projects").is_dir():
        candidate_projects_dirs.append(base / "projects")
    elif base_dir is None:
        repo_root = Path(__file__).resolve().parent.parent
        p_cand = repo_root / "projects"
        if p_cand.is_dir():
            candidate_projects_dirs.append(p_cand)

    found_projects: list[Path] = []
    seen: set[Path] = set()
    for p_dir in candidate_projects_dirs:
        if not p_dir.is_dir():
            continue
        for sub in sorted(p_dir.iterdir()):
            if sub.is_dir() and (sub / "cards").is_dir():
                r = sub.resolve()
                if r not in seen:
                    seen.add(r)
                    found_projects.append(r)

    if len(found_projects) == 1:
        return found_projects[0]
    elif len(found_projects) > 1:
        names = ", ".join(p.name for p in found_projects)
        raise ValueError(
            f"发现多个包含 cards/ 的项目 ({names})，无法安全确定，请显式指定 --project 参数"
        )

    if strict:
        raise FileNotFoundError(
            "未在当前目录或 projects/ 下发现包含 cards/ 的项目，请显式指定 --project 参数"
        )
    return None


def find_long_cards(target: Path) -> list[Path]:
    """在目标路径或其子目录中查找长图文件。"""
    if not target.is_dir():
        return [target]

    found: list[Path] = []
    for pattern in ["*长图*.png", "*long_card*.png"]:
        found.extend(sorted(target.glob(pattern)))
    if not found:
        found = [f for f in sorted(target.glob("*.png")) if "卡片" not in f.name and "render" not in f.name]
    if not found and (target / "output").is_dir():
        for pattern in ["*长图*.png", "*long_card*.png"]:
            found.extend(sorted((target / "output").glob(pattern)))
        if not found:
            found = [f for f in sorted((target / "output").glob("*.png")) if "卡片" not in f.name and "render" not in f.name]
    if not found:
        candidate_p_dirs = []
        if (target / "projects").is_dir():
            candidate_p_dirs.append(target / "projects")
        elif target.name == "projects":
            candidate_p_dirs.append(target)
        for p_dir in candidate_p_dirs:
            for p in sorted(p_dir.iterdir()):
                if p.is_dir() and (p / "output").is_dir():
                    found.extend(sorted((p / "output").glob("*长图*.png")))
                    found.extend(sorted((p / "output").glob("*long_card*.png")))

    seen: set[Path] = set()
    deduped: list[Path] = []
    for f in found:
        rf = f.resolve()
        if rf not in seen:
            seen.add(rf)
            deduped.append(rf)
    return deduped


def run_qa_long_card(
    target_path: Path,
    project_dir: Path | None = None,
    require_header: bool = True,
    require_footer: bool = True,
) -> bool:
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

    # 自动探测 project_dir
    if project_dir is None:
        try:
            project_dir = resolve_project_dir(None, target_path=target_path)
        except ValueError:
            project_dir = None

    accent_rgb, bg_rgb = load_spec_colors(project_dir)

    # 2. 画幅与模式
    ok_dim, msg_dim = check_dimensions_and_mode(img, require_header=require_header, require_footer=require_footer)
    print(f"  [{'✓' if ok_dim else '✗'}] 画幅与结构标准     : {msg_dim}")

    # 3. Header
    if require_header:
        ok_header, msg_header = check_header(arr, accent_rgb)
    else:
        ok_header = True
        msg_header = "跳过（已声明不含 Header）"
    print(f"  [{'✓' if ok_header else '✗'}] 顶部 Header 统摄   : {msg_header}")

    # 4. Footer
    if require_footer:
        ok_footer, msg_footer = check_footer(arr, accent_rgb)
    else:
        ok_footer = True
        msg_footer = "跳过（已声明不含 Footer）"
    print(f"  [{'✓' if ok_footer else '✗'}] 底部 Footer 收尾   : {msg_footer}")

    # 卡片切片解析
    n_cards, gap, slices = parse_card_segments(arr, require_header, require_footer)

    expected_count = None
    if project_dir and (project_dir / "cards").exists():
        expected_count = len([
            p for p in (project_dir / "cards").glob("*.svg")
            if not p.name.startswith("long_card") and not p.name.startswith(".") and "长图" not in p.name
        ])

    # 5. 卡片切片与间距
    ok_seg, msg_seg = check_segments_and_seams(arr, slices, gap, expected_count, bg_rgb)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PPT-Studio 长图客观质量门禁")
    parser.add_argument("target", nargs="?", default=".", help="长图 PNG 文件路径或包含长图/output/*.png 的项目目录（默认当前目录）")
    parser.add_argument("--project", help="项目根目录（用于校验源卡片数量与版式规范）")
    parser.add_argument("--no-header", action="store_true", help="声明长图不包含顶部 Header")
    parser.add_argument("--no-footer", action="store_true", help="声明长图不包含底部 Footer")
    args = parser.parse_args(argv)

    target = Path(args.target).resolve()

    explicit_project = None
    if args.project:
        try:
            explicit_project = resolve_project_dir(args.project)
        except FileNotFoundError as err:
            print(f"[!] {err}", file=sys.stderr)
            return 1

    files_to_check = find_long_cards(target)
    if not files_to_check:
        print(f"[!] 在目录 {target} 或 output/、projects/*/output/ 下未发现长图 PNG 文件", file=sys.stderr)
        return 1

    all_ok = True
    for f in files_to_check:
        try:
            proj = explicit_project or resolve_project_dir(None, target_path=f)
        except ValueError as err:
            print(f"[!] {err}", file=sys.stderr)
            return 1
        res = run_qa_long_card(
            f,
            proj,
            require_header=not args.no_header,
            require_footer=not args.no_footer,
        )
        if not res:
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
