#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_long_card.py —— 多卡片纵向缝合为单张长图
===============================================

把项目 cards/ 目录下的若干张卡片（1080×1350）纵向缝合成一张适合
微信公众号、知乎、知识星球、社群分享的一体化长图。

特性：
  - 自动渲染缺失的 card PNG
  - 可选顶部统摄 Header（标题、主张、发布时间）
  - 卡片间微间距与流式衔接过渡
  - 底部收尾 Footer（来源归属、CTA 行动指引）
  - 同时输出高质量 PNG 与矢量 SVG

用法：
  python3 scripts/make_long_card.py <project_dir> [--out long_card.png] [--gap 20]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# 确保在未显式激活 .venv 时也能从项目内 .venv 加载依赖
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    repo_root = Path(__file__).resolve().parent.parent
    for site_pkg in repo_root.glob(".venv/lib/python*/site-packages"):
        if site_pkg.is_dir() and str(site_pkg) not in sys.path:
            sys.path.insert(0, str(site_pkg))
    from PIL import Image, ImageDraw, ImageFont

BG_COLOR = (11, 12, 18)        # #0B0C12
SURFACE_COLOR = (18, 19, 27)   # #12131B
RULE_COLOR = (35, 36, 46)      # #23242E
TEXT_MAIN = (247, 247, 249)    # #F7F7F9
TEXT_MUTED = (168, 169, 180)   # #A8A9B4
TEXT_DIM = (127, 128, 144)     # #7F8090
ACCENT_COLOR = (110, 123, 255) # #6E7BFF


def hex_to_rgb(hex_str: str, default: tuple[int, int, int]) -> tuple[int, int, int]:
    """十六进制颜色转 RGB 元组。"""
    hex_str = hex_str.strip().lstrip("#")
    if len(hex_str) == 6:
        try:
            return (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))
        except ValueError:
            pass
    return default


def read_project_meta(project_dir: Path) -> dict[str, any]:
    """从 spec_lock.md / card_spec.md 提取核心项目元信息与品牌色。"""
    meta = {
        "title": project_dir.name.replace("-", " ").title(),
        "core_message": "内容到多形态物料的可验证流水线",
        "objective": "全景长图浏览",
        "accent_color": ACCENT_COLOR,
        "bg_color": BG_COLOR,
    }
    for spec_name in ["card_spec.md", "spec_lock.md"]:
        spec_path = project_dir / spec_name
        if spec_path.exists():
            try:
                content = spec_path.read_text(encoding="utf-8")
                m_obj = re.search(r"-\s*objective:\s*(.+)", content)
                if m_obj and meta["objective"] == "全景长图浏览":
                    meta["objective"] = m_obj.group(1).strip()
                m_msg = re.search(r"-\s*core_message:\s*(.+)", content)
                if m_msg and meta["core_message"] == "内容到多形态物料的可验证流水线":
                    meta["core_message"] = m_msg.group(1).strip()
                m_acc = re.search(r"accent(?:_color)?\s*[:=]?\s*\"?(#[0-9a-fA-F]{6})\"?", content)
                if m_acc:
                    meta["accent_color"] = hex_to_rgb(m_acc.group(1), ACCENT_COLOR)
                m_bg = re.search(r"bg(?:_color)?\s*[:=]?\s*\"?(#[0-9a-fA-F]{6})\"?", content)
                if m_bg:
                    meta["bg_color"] = hex_to_rgb(m_bg.group(1), BG_COLOR)
            except Exception:
                pass

    # 如果有 notes/01_cover.md，尝试提取首句
    cover_note = project_dir / "notes" / "01_cover.md"
    if cover_note.exists():
        txt = cover_note.read_text(encoding="utf-8")
        m_cover = re.search(r"只说一句话[：:]\s*(.+)", txt)
        if m_cover:
            meta["headline"] = m_cover.group(1).strip()
    return meta


def ensure_rendered_cards(project_dir: Path, card_svgs: list[Path], render_dir: Path) -> list[Path]:
    """确保所有 card SVG 都有对应的 PNG 渲染结果。"""
    render_dir.mkdir(parents=True, exist_ok=True)
    out_pngs = []
    missing_svgs = []

    for svg in card_svgs:
        png_path = render_dir / f"{svg.stem}.png"
        if not png_path.exists() or png_path.stat().st_mtime < svg.stat().st_mtime:
            missing_svgs.append(svg)
        out_pngs.append(png_path)

    if missing_svgs:
        print(f"[*] 发现 {len(missing_svgs)} 张未渲染或过期的卡片，执行 render_svg.py...")
        # 尝试调用脚本内的 render_one
        script_dir = Path(__file__).resolve().parent
        sys.path.insert(0, str(script_dir))
        try:
            from render_svg import render_one
            for svg in missing_svgs:
                target_png = render_dir / f"{svg.stem}.png"
                render_one(svg, target_png, scale=1.0)
                print(f"    ✓ 渲染成功: {target_png.name}")
        except Exception as e:
            print(f"[!] 调用内置渲染器失败: {e}，请先运行 render_svg.py")
            raise

    return out_pngs


def find_font(size: int, bold: bool = False):
    """尝试加载中文字体，失败回退到默认字体。"""
    font_candidates = [
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    if bold:
        font_candidates.insert(0, "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc")
    for f in font_candidates:
        if os.path.exists(f):
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                continue
    return ImageFont.load_default()


def build_header_image(width: int, meta: dict[str, any], card_count: int) -> Image.Image:
    """构建顶部 Header 区域。"""
    header_h = 420
    bg_color = meta.get("bg_color", BG_COLOR)
    accent_color = meta.get("accent_color", ACCENT_COLOR)
    img = Image.new("RGB", (width, header_h), bg_color)
    draw = ImageDraw.Draw(img)

    # 顶部装饰线与品牌条
    draw.rectangle([(0, 0), (width, 8)], fill=accent_color)

    # Kicker
    font_kicker = find_font(28)
    draw.text((80, 70), "LONG FORMAT · EXCLUSIVE DECK", fill=TEXT_MUTED, font=font_kicker)

    # 页数标签
    chip_text = f"共 {card_count} 页精选"
    draw.rounded_rectangle([(width - 240, 60), (width - 80, 110)], radius=25, fill=SURFACE_COLOR, outline=RULE_COLOR)
    draw.text((width - 210, 72), chip_text, fill=accent_color, font=find_font(24))

    # 主标题
    title = meta.get("headline", meta["title"])
    if len(title) > 20:
        title = title[:20] + "…"
    font_title = find_font(68, bold=True)
    draw.text((80, 130), title, fill=TEXT_MAIN, font=font_title)

    # 副标 / 核心主张
    font_sub = find_font(34)
    core_msg = meta.get("core_message", "")
    draw.text((80, 240), core_msg, fill=TEXT_MUTED, font=font_sub)

    # 底部分割线
    draw.line([(80, 370), (width - 80, 370)], fill=RULE_COLOR, width=2)
    draw.text((80, 385), "下滑浏览完整篇章", fill=TEXT_DIM, font=find_font(24))
    draw.text((width - 80, 385), "PPT-STUDIO 流水线", fill=TEXT_DIM, font=find_font(24), anchor="ra")

    return img


def build_footer_image(width: int, meta: dict[str, any]) -> Image.Image:
    """构建底部 Footer 区域。"""
    footer_h = 320
    bg_color = meta.get("bg_color", BG_COLOR)
    accent_color = meta.get("accent_color", ACCENT_COLOR)
    img = Image.new("RGB", (width, footer_h), bg_color)
    draw = ImageDraw.Draw(img)

    # 顶部分割线
    draw.line([(80, 40), (width - 80, 40)], fill=RULE_COLOR, width=2)

    # 品牌 LOGO / 签名
    font_logo = find_font(44, bold=True)
    draw.text((80, 80), "PPT-STUDIO", fill=TEXT_MAIN, font=font_logo)

    font_desc = find_font(28)
    draw.text((80, 150), "内容到多形态物料的可验证流水线 · 画布为唯一真源", fill=TEXT_MUTED, font=font_desc)
    draw.text((80, 200), "PPTX · HTML · 传播卡片 · 长图模式 · 视频+配音", fill=TEXT_DIM, font=font_desc)

    # 底部版权与行动指引
    draw.text((width - 80, 150), "申请试点 / 了解详情", fill=accent_color, font=find_font(30, bold=True), anchor="ra")
    draw.text((width - 80, 200), "END OF PRESENTATION", fill=TEXT_DIM, font=find_font(24), anchor="ra")

    # 底部装饰条
    draw.rectangle([(0, footer_h - 8), (width, footer_h)], fill=accent_color)

    return img


def resolve_project_dir(target_arg: str | None = None) -> Path:
    """自适应探测包含卡片 SVG 的项目目录。"""
    target = Path(target_arg or ".").resolve()
    # 1. 目标目录内直接包含 cards/
    if (target / "cards").is_dir() and list((target / "cards").glob("*.svg")):
        return target
    # 2. 目标本身就是 cards/
    if target.name == "cards" and target.is_dir() and list(target.glob("*.svg")):
        return target.parent
    # 3. 探索 projects/ 子目录
    for base in [target, target.parent, Path.cwd(), Path(__file__).resolve().parent.parent]:
        p_dir = base / "projects"
        if p_dir.is_dir():
            for sub in sorted(p_dir.iterdir()):
                if sub.is_dir() and (sub / "cards").is_dir() and list((sub / "cards").glob("*.svg")):
                    return sub
    return target


def make_long_card(
    project_dir: Path,
    out_path: Path | None = None,
    gap: int = 16,
    include_header: bool = True,
    include_footer: bool = True,
) -> Path:
    card_dir = project_dir / "cards"
    render_dir = project_dir / "render_cards"
    if not card_dir.exists():
        raise FileNotFoundError(f"项目未找到 cards 目录: {card_dir}，请先运行 make_cards.py")

    card_svgs = sorted([p for p in card_dir.glob("*.svg") if not p.name.startswith("long_card")])
    if not card_svgs:
        raise FileNotFoundError(f"cards/ 目录下无卡片 SVG 文件")

    print(f"[*] 找到 {len(card_svgs)} 张卡片，准备合成长图...")
    png_paths = ensure_rendered_cards(project_dir, card_svgs, render_dir)

    # 加载所有图片
    card_images = [Image.open(p) for p in png_paths]
    card_w, card_h = card_images[0].size

    meta = read_project_meta(project_dir)

    header_img = build_header_image(card_w, meta, len(card_images)) if include_header else None
    footer_img = build_footer_image(card_w, meta) if include_footer else None

    # 计算总高
    total_h = 0
    if header_img:
        total_h += header_img.height + gap
    total_h += len(card_images) * card_h + max(0, len(card_images) - 1) * gap
    if footer_img:
        total_h += gap + footer_img.height

    print(f"[*] 长图规格: {card_w} × {total_h} px (内含 {len(card_images)} 页卡片)")

    # 创建大画布并粘贴
    long_canvas = Image.new("RGB", (card_w, total_h), meta.get("bg_color", BG_COLOR))
    curr_y = 0

    if header_img:
        long_canvas.paste(header_img, (0, curr_y))
        curr_y += header_img.height + gap

    for idx, card in enumerate(card_images):
        long_canvas.paste(card, (0, curr_y))
        curr_y += card.height
        if idx < len(card_images) - 1:
            curr_y += gap

    if footer_img:
        curr_y += gap
        long_canvas.paste(footer_img, (0, curr_y))

    if out_path is None:
        repo_root = Path(__file__).resolve().parent.parent
        if (project_dir / "output").is_dir():
            out_path = project_dir / "output" / f"{project_dir.name}_长图.png"
        elif (repo_root / "output").is_dir():
            out_path = repo_root / "output" / f"{project_dir.name}_长图.png"
        else:
            out_path = project_dir / "output" / f"{project_dir.name}_长图.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    long_canvas.save(out_path, format="PNG", optimize=True)
    print(f"✓ 长图导出成功: {out_path} ({out_path.stat().st_size // 1024} KB)")
    print(f"[i] 建议质检: python3 scripts/qa_long_card.py {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="多卡片纵向缝合为单张长图")
    parser.add_argument("project", nargs="?", default=".", help="项目根目录，例如 projects/agentflow-os-launch（默认当前目录自发现）")
    parser.add_argument("--out", help="输出图片路径，默认输出至 <project>/output/<name>_长图.png")
    parser.add_argument("--gap", type=int, default=16, help="卡片之间的纵向缝隙像素，默认 16")
    parser.add_argument("--no-header", action="store_true", help="不包含顶部 Header")
    parser.add_argument("--no-footer", action="store_true", help="不包含底部 Footer")
    args = parser.parse_args()

    proj_dir = resolve_project_dir(args.project)
    out_p = Path(args.out).resolve() if args.out else None

    make_long_card(
        project_dir=proj_dir,
        out_path=out_p,
        gap=args.gap,
        include_header=not args.no_header,
        include_footer=not args.no_footer,
    )


if __name__ == "__main__":
    main()
