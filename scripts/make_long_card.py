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
import tempfile
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

try:
    from scripts.qa_long_card import run_qa_long_card
except ImportError:
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from scripts.qa_long_card import run_qa_long_card
    except ImportError:
        run_qa_long_card = None

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


def read_project_meta(project_dir: Path) -> dict[str, any]:
    """从 spec_lock.md / card_spec.md 提取核心项目元信息与品牌色。"""
    meta = {
        "title": project_dir.name.replace("-", " ").title(),
        "core_message": "内容到多形态物料的可验证流水线",
        "objective": "全景长图浏览",
        "accent_color": ACCENT_COLOR,
        "bg_color": BG_COLOR,
        "surface_color": SURFACE_COLOR,
        "rule_color": RULE_COLOR,
        "text_main": TEXT_MAIN,
        "text_muted": TEXT_MUTED,
        "text_dim": TEXT_DIM,
    }

    # 规范文件候选集
    candidate_specs: list[Path] = [
        project_dir / "card_spec.md",
        project_dir / "spec_lock.md",
    ]
    repo_root = Path(__file__).resolve().parent.parent
    for base in [Path.cwd(), repo_root]:
        candidate_specs.append(base / "card_spec.md")
        candidate_specs.append(base / "spec_lock.md")

    seen_specs = set()
    found_spec_title = False
    found_colors: set[str] = set()

    for spec_path in candidate_specs:
        if not spec_path.is_file():
            continue
        r_spec = spec_path.resolve()
        if r_spec in seen_specs:
            continue
        seen_specs.add(r_spec)

        try:
            content = r_spec.read_text(encoding="utf-8")
            m_obj = re.search(r"-\s*objective\s*[:=]\s*(.+)", content)
            if m_obj and meta["objective"] == "全景长图浏览":
                meta["objective"] = m_obj.group(1).strip()

            m_msg = re.search(r"-\s*core_message\s*[:=]\s*(.+)", content)
            if m_msg and meta["core_message"] == "内容到多形态物料的可验证流水线":
                meta["core_message"] = m_msg.group(1).strip()

            m_title = re.search(r"^[-*]?\s*title\s*[:=]\s*(.+)", content, re.M)
            if m_title and not found_spec_title:
                cand = m_title.group(1).split("#")[0].strip().strip('"\'')
                if cand and not cand.isdigit() and len(cand) <= 40:
                    meta["title"] = cand
                    found_spec_title = True

            parsed_colors = parse_colors_from_spec_text(content)

            bg_hex = parsed_colors.get("bg") or parsed_colors.get("background") or parsed_colors.get("bg_color")
            if bg_hex and "bg" not in found_colors:
                meta["bg_color"] = hex_to_rgb(bg_hex, BG_COLOR)
                found_colors.add("bg")

            accent_hex = parsed_colors.get("accent") or parsed_colors.get("accent_color")
            if accent_hex and "accent" not in found_colors:
                meta["accent_color"] = hex_to_rgb(accent_hex, ACCENT_COLOR)
                found_colors.add("accent")

            surface_hex = parsed_colors.get("surface") or parsed_colors.get("surface_color")
            if surface_hex and "surface" not in found_colors:
                meta["surface_color"] = hex_to_rgb(surface_hex, SURFACE_COLOR)
                found_colors.add("surface")

            rule_hex = parsed_colors.get("divider") or parsed_colors.get("rule") or parsed_colors.get("rule_color")
            if rule_hex and "rule" not in found_colors:
                meta["rule_color"] = hex_to_rgb(rule_hex, RULE_COLOR)
                found_colors.add("rule")

            main_hex = parsed_colors.get("primary_text") or parsed_colors.get("text_main") or parsed_colors.get("fg")
            if main_hex and "main" not in found_colors:
                meta["text_main"] = hex_to_rgb(main_hex, TEXT_MAIN)
                found_colors.add("main")

            muted_hex = parsed_colors.get("secondary_text") or parsed_colors.get("text_muted") or parsed_colors.get("muted")
            if muted_hex and "muted" not in found_colors:
                meta["text_muted"] = hex_to_rgb(muted_hex, TEXT_MUTED)
                found_colors.add("muted")

            dim_hex = parsed_colors.get("tertiary_text") or parsed_colors.get("text_dim") or parsed_colors.get("dim")
            if dim_hex and "dim" not in found_colors:
                meta["text_dim"] = hex_to_rgb(dim_hex, TEXT_DIM)
                found_colors.add("dim")
        except Exception:
            pass

    # 如果有 notes/01_cover.md，尝试提取首句与标题
    cover_note = project_dir / "notes" / "01_cover.md"
    if cover_note.exists():
        try:
            txt = cover_note.read_text(encoding="utf-8")
            m_cover = re.search(r"只说一句话[：:]\s*(.+)", txt)
            if m_cover:
                meta["headline"] = m_cover.group(1).strip()
            if not found_spec_title:
                for line in txt.splitlines():
                    line = line.strip()
                    if line.startswith("#"):
                        t_cand = line.lstrip("#").strip()
                        if t_cand and len(t_cand) <= 30:
                            meta["title"] = t_cand
                            found_spec_title = True
                            break
        except Exception:
            pass

    # 兜底：若标题未显式指定且目录包含 agentflow
    if not found_spec_title and "agentflow" in project_dir.name.lower():
        meta["title"] = "智流 OS"

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
        if str(script_dir) not in sys.path:
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
    surface_color = meta.get("surface_color", SURFACE_COLOR)
    rule_color = meta.get("rule_color", RULE_COLOR)
    text_main = meta.get("text_main", TEXT_MAIN)
    text_muted = meta.get("text_muted", TEXT_MUTED)
    text_dim = meta.get("text_dim", TEXT_DIM)

    img = Image.new("RGB", (width, header_h), bg_color)
    draw = ImageDraw.Draw(img)

    # 顶部装饰线与品牌条
    draw.rectangle([(0, 0), (width, 8)], fill=accent_color)

    # Kicker
    font_kicker = find_font(28)
    draw.text((80, 70), "LONG FORMAT · EXCLUSIVE DECK", fill=text_muted, font=font_kicker)

    # 页数标签
    chip_text = f"共 {card_count} 页精选"
    draw.rounded_rectangle([(width - 240, 60), (width - 80, 110)], radius=25, fill=surface_color, outline=rule_color)
    draw.text((width - 210, 72), chip_text, fill=accent_color, font=find_font(24))

    # 主标题
    title = meta.get("headline", meta["title"])
    if len(title) > 20:
        title = title[:20] + "…"
    font_title = find_font(68, bold=True)
    draw.text((80, 130), title, fill=text_main, font=font_title)

    # 副标 / 核心主张
    font_sub = find_font(34)
    core_msg = meta.get("core_message", "")
    draw.text((80, 240), core_msg, fill=text_muted, font=font_sub)

    # 底部分割线
    draw.line([(80, 370), (width - 80, 370)], fill=rule_color, width=2)
    draw.text((80, 385), "下滑浏览完整篇章", fill=text_dim, font=find_font(24))
    draw.text((width - 80, 385), "PPT-STUDIO 流水线", fill=text_dim, font=find_font(24), anchor="ra")

    return img


def build_footer_image(width: int, meta: dict[str, any]) -> Image.Image:
    """构建底部 Footer 区域。"""
    footer_h = 320
    bg_color = meta.get("bg_color", BG_COLOR)
    accent_color = meta.get("accent_color", ACCENT_COLOR)
    rule_color = meta.get("rule_color", RULE_COLOR)
    text_main = meta.get("text_main", TEXT_MAIN)
    text_muted = meta.get("text_muted", TEXT_MUTED)
    text_dim = meta.get("text_dim", TEXT_DIM)

    img = Image.new("RGB", (width, footer_h), bg_color)
    draw = ImageDraw.Draw(img)

    # 顶部分割线
    draw.line([(80, 40), (width - 80, 40)], fill=rule_color, width=2)

    # 品牌 LOGO / 签名
    font_logo = find_font(44, bold=True)
    draw.text((80, 80), "PPT-STUDIO", fill=text_main, font=font_logo)

    font_desc = find_font(28)
    draw.text((80, 150), "内容到多形态物料的可验证流水线 · 画布为唯一真源", fill=text_muted, font=font_desc)
    draw.text((80, 200), "PPTX · HTML · 传播卡片 · 长图模式 · 视频+配音", fill=text_dim, font=font_desc)

    # 底部版权与行动指引
    draw.text((width - 80, 150), "申请试点 / 了解详情", fill=accent_color, font=find_font(30, bold=True), anchor="ra")
    draw.text((width - 80, 200), "END OF PRESENTATION", fill=text_dim, font=find_font(24), anchor="ra")

    # 底部装饰条
    draw.rectangle([(0, footer_h - 8), (width, footer_h)], fill=accent_color)

    return img


def resolve_project_dir(
    project_arg: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> Path:
    """自适应探测包含卡片 cards/*.svg 的项目目录。

    1. 若显式指定 project_arg（非空且非 '.'）：
       - 转换为绝对路径（若为相对路径则基于 base_dir 或当前工作目录解析）；
       - 校验存在性，若不存在抛出 FileNotFoundError；
       - 若目标目录直接包含 cards/ 且有 *.svg，返回 target；
       - 若目标目录本身名为 cards 且有 *.svg，返回 target.parent；
       - 若目标目录下有 projects/ 目录或自身名为 projects，从中安全发现包含 cards/*.svg 的子项目；
       - 若目标目录本身包含 *.svg（可能就是卡片根目录），返回 target；
       - 否则抛出 FileNotFoundError。
    2. 若未显式指定 project_arg 或为 '.'：
       - 探测 base_dir（默认当前工作目录）：
         * 若 (base / "cards").is_dir() 且包含 *.svg，返回 base；
         * 若 base.name == "cards" 且包含 *.svg，返回 base.parent；
       - 从 base/projects 或仓库根目录 projects/ 探测：
         * 收集所有包含 cards/ 且有 *.svg 的子项目；
         * 若唯一匹配，返回唯一项目；
         * 若有多个匹配，抛出 ValueError（避免歧义导致规则误用）；
         * 若未发现匹配，抛出 FileNotFoundError。
    """
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    is_default = (project_arg is None or str(project_arg).strip() in ("", "."))

    if not is_default:
        p = Path(project_arg)
        if not p.is_absolute():
            p = (base / p).resolve()
        else:
            p = p.resolve()

        if not p.exists():
            raise FileNotFoundError(f"指定的项目目录不存在: {project_arg}")

        if (p / "cards").is_dir() and list((p / "cards").glob("*.svg")):
            return p.resolve()

        if p.is_dir() and p.name == "cards" and list(p.glob("*.svg")):
            return p.parent.resolve()

        candidate_projects_dirs: list[Path] = []
        if (p / "projects").is_dir():
            candidate_projects_dirs.append(p / "projects")
        elif p.is_dir() and p.name == "projects":
            candidate_projects_dirs.append(p)

        matches: list[Path] = []
        for s_dir in candidate_projects_dirs:
            for sub in sorted(s_dir.iterdir()):
                if sub.is_dir() and (sub / "cards").is_dir() and list((sub / "cards").glob("*.svg")):
                    matches.append(sub.resolve())

        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            names = ", ".join(m.name for m in matches)
            raise ValueError(f"发现多个包含 cards/ 的项目 ({names})，无法安全确定，请显式指定 project 参数")

        if p.is_dir() and list(p.glob("*.svg")):
            return p.resolve()

        raise FileNotFoundError(f"在目录 {project_arg} 下未找到有效卡片或 cards/ 子目录")

    # 默认/自适应探测
    if (base / "cards").is_dir() and list((base / "cards").glob("*.svg")):
        return base.resolve()
    if base.is_dir() and base.name == "cards" and list(base.glob("*.svg")):
        return base.parent.resolve()

    candidate_projects_dirs = []
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
        for sub in sorted(p_dir.iterdir()):
            if sub.is_dir() and (sub / "cards").is_dir() and list((sub / "cards").glob("*.svg")):
                r = sub.resolve()
                if r not in seen:
                    seen.add(r)
                    found_projects.append(r)
        if found_projects:
            break

    if len(found_projects) == 1:
        return found_projects[0]
    elif len(found_projects) > 1:
        names = ", ".join(m.name for m in found_projects)
        raise ValueError(f"发现多个包含 cards/ 的项目 ({names})，无法安全确定，请显式指定 project 参数")

    raise FileNotFoundError("在当前目录或 projects/ 下未找到包含 cards/ 的有效项目")


def make_long_card(
    project_dir: Path,
    out_path: Path | None = None,
    gap: int = 16,
    include_header: bool = True,
    include_footer: bool = True,
    check: bool = False,
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
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, staged_name = tempfile.mkstemp(prefix=f".{out_path.name}.", dir=out_path.parent)
    os.close(fd)
    staged_path = Path(staged_name)

    try:
        long_canvas.save(staged_path, format="PNG", optimize=True)
    except Exception:
        staged_path.unlink(missing_ok=True)
        raise
    finally:
        for c in card_images:
            try:
                c.close()
            except Exception:
                pass
        try:
            long_canvas.close()
        except Exception:
            pass

    print(f"✓ 长图已准备: {out_path} ({staged_path.stat().st_size // 1024} KB)")
    print(f"[i] 建议质检: python3 scripts/qa_long_card.py {out_path}")

    if check:
        if run_qa_long_card is not None:
            ok = run_qa_long_card(
                staged_path,
                project_dir=project_dir,
                require_header=include_header,
                require_footer=include_footer,
            )
            if not ok:
                staged_path.unlink(missing_ok=True)
                raise RuntimeError(f"长图客观质量门禁未通过: {out_path}")
            print("  [门禁] ✓ 长图客观质量门禁通过")
        else:
            print("  [warn] 未导入 run_qa_long_card，跳过门禁检查")

    try:
        os.replace(staged_path, out_path)
    except Exception:
        staged_path.unlink(missing_ok=True)
        raise
    print(f"✓ 长图原子提交完成: {out_path}")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="多卡片纵向缝合为单张长图")
    parser.add_argument("project", nargs="?", default=".", help="项目根目录，例如 projects/agentflow-os-launch（默认当前目录自发现）")
    parser.add_argument("--out", help="输出图片路径，默认输出至 <project>/output/<name>_长图.png")
    parser.add_argument("--gap", type=int, default=16, help="卡片之间的纵向缝隙像素，默认 16")
    parser.add_argument("--no-header", action="store_true", help="不包含顶部 Header")
    parser.add_argument("--no-footer", action="store_true", help="不包含底部 Footer")
    parser.add_argument("--check", action="store_true", help="构建完成后执行长图客观质量门禁校验 (qa_long_card.py)")
    args = parser.parse_args(argv)

    try:
        proj_dir = resolve_project_dir(args.project)
    except (FileNotFoundError, ValueError) as err:
        print(f"[err] {err}", file=sys.stderr)
        return 1

    out_p = Path(args.out).resolve() if args.out else None

    try:
        make_long_card(
            project_dir=proj_dir,
            out_path=out_p,
            gap=args.gap,
            include_header=not args.no_header,
            include_footer=not args.no_footer,
            check=args.check,
        )
        return 0
    except (FileNotFoundError, ValueError, RuntimeError) as err:
        print(f"[err] 制作长图失败: {err}", file=sys.stderr)
        return 1
    except Exception as err:
        print(f"[err] 制作长图失败: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
