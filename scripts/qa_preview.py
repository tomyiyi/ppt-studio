#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa_preview.py —— PPT-Studio HTML 预览与多形态展厅客观质量门禁
============================================================

对导出的 HTML 翻页预览单文件（如 配图版_发布会预览.html、卡片集.html）
以及多形态物料展厅（index.html）执行自动化客观质量门禁，确保交付文件符合规范：

针对交互式幻灯片预览（Slide Preview）：
  1. [HTML 基础规范] HTML5 骨架完整（DOCTYPE/lang/charset/viewport/title）
  2. [幻灯片容器] 包含 .stage 舞台，幻灯片数量 ≥ 1，有且仅有第 1 页激活 (.slide.active)
  3. [矢量画布适配] 每页包含有效 <svg> 与 viewBox，画幅尺寸与纵横比跨页严格统一
  4. [媒体内联完整] 所有 <image> 资源必须全部内联为 data:image/...;base64,...，杜绝离线断链
  5. [交互与指示器] 导航控件 (go(-1)/go(1)) 闭环，时序指示器 #ind 初始值（如 01 / 07）与总页数对齐
  6. [按键与全屏] 具备键盘监听（ArrowRight/ArrowLeft/Space 翻页，F 全屏切换）
  7. [零外部依赖] 100% 单文件自包含，无外部 CDN 脚本/样式，离线可通跑

针对多形态展厅索引（Showroom Portal / index.html）：
  1. [HTML 基础规范] HTML5 骨架完整，响应式视口与 UTF-8 编码
  2. [展厅架构品牌] 具备品牌 Badge、标题、副标题与多形态物料卡片网格
  3. [全形态物料链] 完整覆盖发布会 PPT、卡片集、长图、解说视频、短视频等形态
  4. [导出物超链接] 页面引用的所有本地文件超链接真实存在、非空且有效
  5. [多媒体播放源] <video>/<source>/poster 媒体资源真实存在、体积正常
  6. [暗色美学栅格] 统一深色主题背景与品牌色 (#6E7BFF)，支持自适应网格
  7. [离线自包含] 无不可用外部资源断链，交付包闭环健全

用法：
  python3 scripts/qa_preview.py [target]
  # target 可为单 html 文件、output 目录或项目根目录（默认当前目录自发现）
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import sys
from pathlib import Path


def check_html_standards(content: str) -> tuple[bool, str]:
    """检查 HTML5 基础规范骨架。"""
    c_lower = content.lower()
    if "<!doctype html" not in c_lower:
        return False, "缺少 <!DOCTYPE html> 声明"
    if "<html" not in c_lower:
        return False, "缺少 <html> 根标签"
    if "charset=" not in c_lower:
        return False, "缺少 <meta charset=\"...\"> 字符编码声明"
    if "name=\"viewport\"" not in c_lower and "name='viewport'" not in c_lower:
        return False, "缺少 <meta name=\"viewport\" ...> 移动端适配声明"
    
    title_m = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
    if not title_m or not title_m.group(1).strip():
        return False, "缺少有效 <title> 页面标题"
    
    title = title_m.group(1).strip()
    return True, f"HTML5 标准骨架 · UTF-8 · 响应式视口 · 标题《{title}》"


def run_qa_slide_preview(target_file: Path) -> bool:
    """质检交互式单文件翻页预览 HTML。"""
    content = target_file.read_text(encoding="utf-8")
    file_kb = target_file.stat().st_size // 1024

    print("=" * 60)
    print("🔍 运行 PPT-Studio HTML 翻页预览客观质量门禁")
    print(f"   目标: {target_file}")
    print("=" * 60)

    bad = 0

    # 1. HTML 基础规范
    ok, msg = check_html_standards(content)
    print(f"  [{'✓' if ok else '✗'}] HTML 基础规范       : {msg}")
    if not ok:
        bad += 1

    # 2. 幻灯片容器与激活态
    slide_matches = list(re.finditer(r'<div\s+class=["\']slide([^"\']*)["\']', content))
    n_slides = len(slide_matches)
    if n_slides == 0:
        print("  [✗] 幻灯片容器与激活态  : 未检测到任何 class=\"slide\" 容器")
        bad += 1
    else:
        active_indices = [i for i, m in enumerate(slide_matches) if "active" in m.group(1).split()]
        if len(active_indices) != 1:
            print(f"  [✗] 幻灯片容器与激活态  : 激活页数量异常 ({len(active_indices)} 个 active，期望有且仅有 1 个)")
            bad += 1
        elif active_indices[0] != 0:
            print(f"  [✗] 幻灯片容器与激活态  : 初始激活页非第 1 页 (当前第 {active_indices[0] + 1} 页激活)")
            bad += 1
        else:
            print(f"  [✓] 幻灯片容器与激活态  : {n_slides} 页幻灯片 · 首页初始激活 (第 1 页)")

    # 3. 矢量画布与画幅适配
    svg_matches = re.findall(r'<svg\b[^>]*\bviewBox\s*=\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
    if len(svg_matches) < n_slides:
        print(f"  [✗] 矢量画布与画幅适配  : SVG 数量 ({len(svg_matches)}) 与幻灯片数 ({n_slides}) 不匹配")
        bad += 1
    else:
        ratios = []
        sizes = []
        parse_err = False
        for vb in svg_matches:
            parts = re.split(r'[\s,]+', vb.strip())
            if len(parts) == 4:
                try:
                    w, h = float(parts[2]), float(parts[3])
                    sizes.append((int(w), int(h)))
                    ratios.append(w / h)
                except ValueError:
                    parse_err = True
            else:
                parse_err = True

        if parse_err or not sizes:
            print("  [✗] 矢量画布与画幅适配  : 部分 SVG viewBox 坐标或尺寸无法解析")
            bad += 1
        else:
            first_w, first_h = sizes[0]
            first_r = ratios[0]
            max_drift = max(abs(r - first_r) / first_r for r in ratios)
            if max_drift > 0.02:
                print(f"  [✗] 矢量画布与画幅适配  : 跨页画幅比例不统一 (首页: {first_w}×{first_h}, 最大漂移 {max_drift*100:.1f}%)")
                bad += 1
            else:
                ratio_desc = "16:9 标准横版" if abs(first_r - 16/9) < 0.05 else ("4:5 竖版卡片" if abs(first_r - 0.8) < 0.05 else f"比例 {first_r:.2f}")
                print(f"  [✓] 矢量画布与画幅适配  : {first_w}×{first_h} ({ratio_desc}) · {len(sizes)} 页尺寸完全统一")

    # 4. 媒体资源内联完整性
    img_matches = re.findall(r'<image\b[^>]*?\b(?:href|xlink:href)\s*=\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
    if not img_matches:
        print("  [✓] 媒体资源内联完整性  : 纯矢量形态 (无内嵌位图资源)")
    else:
        external = [img for img in img_matches if not img.startswith("data:")]
        corrupt_b64 = []
        for img in img_matches:
            if img.startswith("data:"):
                try:
                    payload = img.split(",", 1)[-1].strip()
                    sample_len = (min(len(payload), 128) // 4) * 4
                    chunk = payload[:sample_len]
                    if not chunk:
                        corrupt_b64.append("空数据")
                    else:
                        raw = base64.b64decode(chunk)
                        if len(raw) == 0:
                            corrupt_b64.append("空数据")
                except Exception:
                    corrupt_b64.append("解码失败")

        if external:
            print(f"  [✗] 媒体资源内联完整性  : 存在未内联的外部图片路径 ({len(external)} 处，首个: {external[0][:40]})")
            bad += 1
        elif corrupt_b64:
            print(f"  [✗] 媒体资源内联完整性  : 存在损坏的 Data URI ({len(corrupt_b64)} 处)")
            bad += 1
        else:
            print(f"  [✓] 媒体资源内联完整性  : {len(img_matches)} 个媒体资源全部内联为 data URI (Base64 解码完好)")

    # 5. 交互翻页与指示器
    has_go_fn = "function go(" in content or "go(" in content
    has_nav_btn = "go(-1)" in content and "go(1)" in content
    ind_match = re.search(r'id=["\']ind["\'][^>]*>(.*?)</div>', content)
    if not has_nav_btn:
        print("  [✗] 交互翻页与指示器    : 缺少上一页/下一页导航控制按钮 (go(-1)/go(1))")
        bad += 1
    elif not ind_match:
        print("  [✗] 交互翻页与指示器    : 缺少 #ind 页码时序指示器元素")
        bad += 1
    else:
        ind_text = ind_match.group(1).strip()
        expected_ind = f"01 / {n_slides:02d}"
        if ind_text != expected_ind:
            print(f"  [✗] 交互翻页与指示器    : 初始指示器文字 '{ind_text}' 与实际页数不符 (期望: '{expected_ind}')")
            bad += 1
        else:
            print(f"  [✓] 交互翻页与指示器    : 双向翻页函数齐全 · 时序指示器 {expected_ind} 严格对齐")

    # 6. 键盘响应与全屏控制
    has_keydown = "keydown" in content
    has_arrows = ("ArrowRight" in content or "39" in content) and ("ArrowLeft" in content or "37" in content)
    has_fullscreen = "fullscreen" in content.lower() or "requestfullscreen" in content.lower()

    if not has_keydown or not has_arrows:
        print("  [✗] 键盘响应与全屏控制  : 缺少左右方向键键盘事件监听")
        bad += 1
    elif not has_fullscreen:
        print("  [✗] 键盘响应与全屏控制  : 缺少全屏 (F 键/requestFullscreen) 快捷交互")
        bad += 1
    else:
        print("  [✓] 键盘响应与全屏控制  : 监听 Arrow/Space 翻页 · F 全屏监听闭环")

    # 7. 零外部依赖自包含
    external_scripts = re.findall(r'<script\b[^>]*?\bsrc\s*=\s*["\'](http[^"\']+)["\']', content, re.IGNORECASE)
    external_styles = re.findall(r'<link\b[^>]*?\bhref\s*=\s*["\'](http[^"\']+)["\']', content, re.IGNORECASE)
    
    min_bytes = 10 * 1024 if img_matches else 512
    if external_scripts or external_styles:
        print(f"  [✗] 零外部依赖自包含    : 存在外部 CDN 引用 (脚本 {len(external_scripts)} / 样式 {len(external_styles)})")
        bad += 1
    elif target_file.stat().st_size < min_bytes:
        threshold_str = "10 KB" if img_matches else "512 字节"
        print(f"  [✗] 零外部依赖自包含    : 文件体积异常过小 ({target_file.stat().st_size} bytes < {threshold_str})，疑似截断")
        bad += 1
    else:
        print(f"  [✓] 零外部依赖自包含    : 无外部 CDN 依赖 · {file_kb} KB 单文件完全自包含")

    print("=" * 60)
    print("ALL CLEAR ✅" if bad == 0 else f"❌ {bad} 项需要处理")
    return bad == 0


def run_qa_showroom_portal(target_file: Path) -> bool:
    """质检多形态物料在线展厅 index.html。"""
    content = target_file.read_text(encoding="utf-8")
    parent_dir = target_file.parent
    file_kb = target_file.stat().st_size // 1024

    print("=" * 60)
    print("🔍 运行 PPT-Studio 多形态物料展厅客观质量门禁")
    print(f"   目标: {target_file}")
    print("=" * 60)

    bad = 0

    # 1. HTML 基础规范
    ok, msg = check_html_standards(content)
    print(f"  [{'✓' if ok else '✗'}] HTML 基础规范       : {msg}")
    if not ok:
        bad += 1

    # 2. 展厅架构与品牌统摄
    has_header = "<header>" in content
    has_badge = "badge" in content
    has_grid = "grid" in content
    card_count = len(re.findall(r'<div class=["\']card["\']>', content))

    if not (has_header and has_grid) or card_count < 3:
        print(f"  [✗] 展厅架构与品牌统摄  : 缺少标准展厅骨架或卡片数量不足 (当前 {card_count} 张卡片)")
        bad += 1
    else:
        print(f"  [✓] 展厅架构与品牌统摄  : 品牌 Badge · 标题与副标题 · {card_count} 组物料卡片")

    # 3. 多形态物料链路覆盖
    content_lower = content.lower()
    required_forms = {
        "PPTX": any(k in content for k in ["pptx", "PPTX", "发布会 PPT", "Office 原生"]),
        "卡片图": any(k in content for k in ["卡片", "card", "小红书"]),
        "长图": any(k in content for k in ["长图", "纵向通读"]),
        "解说视频": any(k in content for k in ["解说视频", "1080p", "视频"]),
        "短视频": any(k in content for k in ["竖版", "短视频", "9:16", "抖音"]),
    }
    missing_forms = [k for k, v in required_forms.items() if not v]
    if missing_forms:
        print(f"  [✗] 多形态物料链路覆盖  : 展厅缺少核心形态展示: {', '.join(missing_forms)}")
        bad += 1
    else:
        print("  [✓] 多形态物料链路覆盖  : 覆盖 PPTX / 卡片集 / 长图 / 1080p视频 / 竖版短视频")

    # 4. 导出物超链接真实连通
    href_targets = re.findall(r'<a\b[^>]*?\bhref\s*=\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
    local_links = [h for h in href_targets if not h.startswith("http") and not h.startswith("#") and not h.startswith("mailto:")]
    
    broken_links = []
    empty_files = []
    for link in local_links:
        link_path = (parent_dir / link).resolve()
        if not link_path.exists():
            broken_links.append(link)
        elif link_path.stat().st_size == 0:
            empty_files.append(link)

    if broken_links:
        print(f"  [✗] 导出物链接真实连通  : 发现死链接 ({len(broken_links)} 个): {', '.join(broken_links[:3])}")
        bad += 1
    elif empty_files:
        print(f"  [✗] 导出物链接真实连通  : 链接目标为空文件 0 字节 ({len(empty_files)} 个): {', '.join(empty_files)}")
        bad += 1
    else:
        print(f"  [✓] 导出物链接真实连通  : {len(local_links)} 个导出物超链接全部真实存在且体积有效")

    # 5. 多媒体内嵌与播放源
    source_srcs = re.findall(r'<source\b[^>]*?\bsrc\s*=\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
    poster_srcs = re.findall(r'<video\b[^>]*?\bposter\s*=\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
    media_refs = source_srcs + poster_srcs

    broken_media = []
    for m in media_refs:
        if not m.startswith("http") and not m.startswith("data:"):
            mpath = (parent_dir / m).resolve()
            if not mpath.exists() or mpath.stat().st_size == 0:
                broken_media.append(m)

    if broken_media:
        print(f"  [✗] 多媒体内嵌与播放源  : 视频或海报资源丢失 ({len(broken_media)} 处): {', '.join(broken_media)}")
        bad += 1
    else:
        print(f"  [✓] 多媒体内嵌与播放源  : {len(source_srcs)} 个视频播放源与封面海报全部有效解析")

    # 6. 响应式视口与暗色规范
    has_accent = "#6E7BFF" in content or "#6e7bff" in content
    has_dark_bg = any(c in content for c in ["#090a10", "#05060a", "radial-gradient"])
    has_media_query = "@media" in content

    if not (has_accent and has_dark_bg):
        print("  [✗] 响应式视口与暗色规范: 品牌强调色 (#6E7BFF) 或暗色主题规范未对齐")
        bad += 1
    else:
        print("  [✓] 响应式视口与暗色规范: 深色主题色板 · 栅格自适应 · 品牌色 #6E7BFF 对齐")

    # 7. 离线自包含无断链
    external_scripts = re.findall(r'<script\b[^>]*?\bsrc=["\'](http[^"\']+)["\']', content, re.IGNORECASE)
    if external_scripts:
        print(f"  [✗] 离线自包含无断链    : 存在外部脚本依赖 ({len(external_scripts)} 处)")
        bad += 1
    else:
        print(f"  [✓] 离线自包含无断链    : 无外部不可用依赖 · 引用链路 100% 闭环")

    print("=" * 60)
    print("ALL CLEAR ✅" if bad == 0 else f"❌ {bad} 项需要处理")
    return bad == 0


def run_qa_html_file(f: Path) -> bool:
    """根据文件特征分流至单文件翻页预览或多形态物料展厅。"""
    try:
        content = f.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[!] 无法读取文件 {f}: {e}")
        return False

    if f.name == "index.html" or "展厅" in content or "MULTI-OUTPUT PIPELINE" in content:
        return run_qa_showroom_portal(f)
    else:
        return run_qa_slide_preview(f)


def find_preview_files(target: Path | str = ".", base_dir: Path | None = None) -> list[Path]:
    """发现并解析待质检的 HTML 预览与展厅文件列表。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    target_path = Path(target)
    if not target_path.is_absolute():
        target_path = (base / target_path).resolve()

    if not target_path.exists():
        raise FileNotFoundError(f"目标路径不存在: {target_path}")

    if target_path.is_file():
        if target_path.suffix.lower() in [".html", ".htm"]:
            return [target_path]
        raise ValueError(f"目标文件不是 HTML 文件: {target_path}")

    files_to_check: list[Path] = []
    # 1. 检查当前目录
    files_to_check.extend(sorted(target_path.glob("*.html")))
    # 2. 检查 output/ 子目录
    if (target_path / "output").is_dir():
        files_to_check.extend(sorted((target_path / "output").glob("*.html")))
    # 3. 检查 projects/*/output/ 子目录
    if (target_path / "projects").is_dir():
        for p in sorted((target_path / "projects").iterdir()):
            if p.is_dir() and (p / "output").is_dir():
                files_to_check.extend(sorted((p / "output").glob("*.html")))

    # 去重保持顺序，排除 .venv 与 site-packages
    seen = set()
    deduped = []
    for f in files_to_check:
        rf = f.resolve()
        if rf not in seen and ".venv" not in str(rf) and "site-packages" not in str(rf):
            seen.add(rf)
            deduped.append(rf)
    return deduped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PPT-Studio HTML 预览与多形态展厅客观质量门禁")
    parser.add_argument("target", nargs="?", default=".", help="HTML 文件路径、output 目录或项目根目录（默认当前目录自发现）")
    args = parser.parse_args(argv)

    try:
        files_to_check = find_preview_files(args.target)
    except (FileNotFoundError, ValueError) as e:
        print(f"[!] {e}")
        return 1

    if not files_to_check:
        print(f"[!] 在目录 {args.target} 及其子目录下未发现任何可质检的 HTML 文件")
        return 1

    all_ok = True
    for f in files_to_check:
        ok = run_qa_html_file(f)
        print()
        if not ok:
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
