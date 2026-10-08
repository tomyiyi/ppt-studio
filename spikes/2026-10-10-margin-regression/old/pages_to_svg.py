#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分页计划 -> SVG（内容驱动生成的渲染器）

输入 md_to_pages.py 产出的 pages.json，输出 1280x720 SVG 到 svg_output/。
四种版式：cover / bullets / compare / steps，全部遵循：
- 60px 安全边距，字号只用阶梯档 {11,13,16,20,24,32,44,96}
- 深色科技风配色（#08090C / #F7F7F9 / #8E8F9A / #6E7BFF）
- data-pptx-* 属性供 svg_to_pptx 转换；每页带 <title>

用法：
    python3 scripts/pages_to_svg.py --pages <pages.json> --out <project>/svg_output
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cover_archetypes import title_font_size

W, H, MARGIN = 1280, 720, 60
RAMP = {11, 13, 16, 20, 24, 32, 44, 96}
BG, FG, MUTED, ACCENT, DIV, CARD = "#08090C", "#F7F7F9", "#8E8F9A", "#6E7BFF", "#23242E", "#12131A"
NL = chr(10)


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def snap(px: int) -> int:
    return min(RAMP, key=lambda r: abs(r - px))


def wrap(text: str, px: int, max_w: int) -> list:
    lines, cur, cur_w = [], "", 0.0
    for ch in text:
        cw = px if ord(ch) > 0x2E7F else px * 0.55
        if cur_w + cw > max_w and cur:
            lines.append(cur)
            cur, cur_w = "", 0.0
        cur += ch
        cur_w += cw
    if cur:
        lines.append(cur)
    return lines or [""]


def disp_estimate(text: str, px: int) -> float:
    """粗略估算文本显示宽度（中英混排），用于字号自适应。"""
    w = 0.0
    for ch in text:
        w += px if ord(ch) > 0x2E7F else px * 0.55
    return w


def t(x, y, s, px, fill=None, weight=None, ls=None):
    fill = fill or FG
    a = ' x="%d" y="%d" font-size="%d" fill="%s"' % (x, y, px, fill)
    if weight:
        a += ' font-weight="%s"' % weight
    if ls:
        a += ' letter-spacing="%s"' % ls
    return "<text%s>%s</text>" % (a, esc(s))


def page_frame(title, kicker, inner, bg_file=None):
    parts = []
    parts.append('<svg data-pptx-page-role="content" xmlns="http://www.w3.org/2000/svg"')
    parts.append(' viewBox="0 0 1280 720" width="1280" height="720"')
    parts.append(' font-family="Microsoft YaHei, PingFang SC, Arial, sans-serif">')
    parts.append("<title>" + esc(title) + "</title>" + NL)
    parts.append('<rect width="1280" height="720" fill="' + BG + '"/>' + NL)
    if bg_file:
        parts.append('<defs><linearGradient id="scrim" x1="0" y1="0" x2="1" y2="0">'
                     '<stop offset="0" stop-color="#08090C" stop-opacity="0.92"/>'
                     '<stop offset="0.55" stop-color="#08090C" stop-opacity="0.55"/>'
                     '<stop offset="1" stop-color="#08090C" stop-opacity="0.25"/>'
                     '</linearGradient></defs>' + NL)
        parts.append('<image href="../images/' + bg_file + '" x="0" y="0" '
                     'width="1280" height="720" preserveAspectRatio="xMidYMid slice"/>' + NL)
        parts.append('<rect width="1280" height="720" fill="url(#scrim)"/>' + NL)
    parts.append('<g id="kicker" data-pptx-bounds="60 80 1160 30" data-pptx-role="decoration">'
                 + t(MARGIN, 100, kicker, 11, MUTED, ls="4") + "</g>" + NL)
    parts.append('<g id="content" data-pptx-bounds="60 120 1160 500">' + NL + inner + NL + "</g>" + NL)
    parts.append('<g id="footer" data-pptx-bounds="60 640 1160 20" data-pptx-role="decoration">'
                 + '<line x1="60" y1="648" x2="1220" y2="648"')
    parts.append(' stroke="' + DIV + '" stroke-width="1"/></g>' + NL)
    parts.append("</svg>")
    return "".join(parts)


def layout_cover(pg, kicker):
    title = pg["title"]
    px = snap(title_font_size(title, 44))
    lines = wrap(title, px, W - 2 * MARGIN)
    y = 300 - (len(lines) - 1) * int(px * 0.7)
    inner = ""
    for i, ln in enumerate(lines):
        inner += t(MARGIN, y + i * int(px * 1.35), ln, px, weight="bold") + NL
    sub = pg["bullets"][0] if pg["bullets"] else ""
    for j, sl in enumerate(wrap(sub, 20, W - 2 * MARGIN)[:2]):
        inner += t(MARGIN, y + len(lines) * int(px * 1.35) + 40 + j * 32, sl, 20, MUTED) + NL
    inner += '<rect x="%d" y="%d" width="64" height="4" fill="%s"/>' % (MARGIN, y - 70, ACCENT) + NL
    return page_frame(title, kicker, inner, pg.get("image_file"))


def layout_bullets(pg, kicker):
    title = pg["title"]
    px = snap(title_font_size(title, 44))
    tlines = wrap(title, px, W - 2 * MARGIN)[:2]
    inner = ""
    y = 170
    for i, ln in enumerate(tlines):
        inner += t(MARGIN, y + i * int(px * 1.3), ln, px, weight="bold") + NL
    y = y + len(tlines) * int(px * 1.3) + 40
    for b in pg["bullets"][:5]:
        inner += '<circle cx="%d" cy="%d" r="5" fill="%s"/>' % (MARGIN + 6, y - 7, ACCENT) + NL
        blines = wrap(b, 20, W - 2 * MARGIN - 40)[:2]
        for j, bl in enumerate(blines):
            inner += t(MARGIN + 28, y + j * 32, bl, 20) + NL
        y += len(blines) * 32 + 22
        if y > 600:
            break
    return page_frame(title, kicker, inner, pg.get("image_file"))


def layout_compare(pg, kicker):
    title = pg["title"]
    inner = t(MARGIN, 170, title[:30], 32, weight="bold") + NL
    bullets = pg["bullets"][:6]
    half = (len(bullets) + 1) // 2
    cols = [bullets[:half], bullets[half:]]
    col_w = (W - 2 * MARGIN - 40) // 2
    for ci, col in enumerate(cols):
        x = MARGIN + ci * (col_w + 40)
        inner += '<rect x="%d" y="210" width="%d" height="380" fill="%s" rx="8"/>' % (x, col_w, CARD) + NL
        y = 260
        for b in col:
            blines = wrap(b, 20, col_w - 40)[:3]
            for j, bl in enumerate(blines):
                inner += t(x + 20, y + j * 32, bl, 20) + NL
            y += len(blines) * 32 + 20
    return page_frame(title, kicker, inner, pg.get("image_file"))


def layout_steps(pg, kicker):
    title = pg["title"]
    inner = t(MARGIN, 170, title[:30], 32, weight="bold") + NL
    steps = pg["bullets"][:4]
    n = max(1, len(steps))
    col_w = (W - 2 * MARGIN - (n - 1) * 24) // n
    for i, s in enumerate(steps):
        x = MARGIN + i * (col_w + 24)
        inner += '<rect x="%d" y="210" width="%d" height="380" fill="%s" rx="8"/>' % (x, col_w, CARD) + NL
        inner += '<text x="%d" y="270" font-size="44" font-weight="bold" fill="%s">%02d</text>' % (x + 20, ACCENT, i + 1) + NL
        y = 320
        for j, bl in enumerate(wrap(s, 20, col_w - 40)[:5]):
            inner += t(x + 20, y + j * 32, bl, 20) + NL
    return page_frame(title, kicker, inner, pg.get("image_file"))


def layout_statement(pg, kicker):
    """金句页：大字观点，居中偏上，留白给情绪。"""
    title = pg["title"]
    px = snap(title_font_size(title, 44))
    lines = wrap(title, px, W - 2 * MARGIN - 120)[:4]
    inner = ""
    y = 300 - (len(lines) - 1) * int(px * 0.7)
    # 顶部一道强调线，视觉锚点
    inner += '<rect x="%d" y="%d" width="88" height="4" fill="%s"/>' % (MARGIN, y - 90, ACCENT) + NL
    for i, ln in enumerate(lines):
        inner += t(MARGIN, y + i * int(px * 1.35), ln, px, weight="bold") + NL
    # 副句压在下方，作为注解而非并列要点
    for b in pg["bullets"][:1]:
        for j, bl in enumerate(wrap(b, 20, W - 2 * MARGIN - 120)[:2]):
            inner += t(MARGIN, y + len(lines) * int(px * 1.35) + 60 + j * 32, bl, 20, MUTED) + NL
    return page_frame(title, kicker, inner, pg.get("image_file"))


def layout_fact(pg, kicker):
    """大数字页：数字是绝对主角，说明文字退居次要。

    取数优先级：标题里的数字 > 要点里的数字。
    旧实现用 max(len) 选最长字符串，会选中正文里的样本量（如"1200"）
    而错过标题里的核心指标（如"41%"）。
    """
    import re as _re
    title = pg["title"]
    num_re = r"\d+(?:\.\d+)?\s*[%％倍万千百亿]?"

    big = None
    m = _re.search(num_re, title)
    if m:
        big = m.group(0)
    else:
        for b in pg["bullets"]:
            m = _re.search(num_re, b)
            if m:
                big = m.group(0)
                break

    inner = ""
    if big:
        # 数字放大到 96 档，字宽适配容器
        n_px = 96
        while n_px > 44 and disp_estimate(big, n_px) > W - 2 * MARGIN - 160:
            n_px -= 4
        inner += t(MARGIN, 360, big, n_px, weight="bold", fill=ACCENT) + NL
        # 标题去掉数字后作为说明
        rest = title.replace(big, "").strip("：: 的")[:40]
        if rest:
            for i, ln in enumerate(wrap(rest, 32, W - 2 * MARGIN - 160)[:2]):
                inner += t(MARGIN, 420 + i * 44, ln, 32) + NL
    else:
        # 没数字就不硬造，退回 statement 版式
        return layout_statement(pg, kicker)

    # 补充说明：只取不含该数字的要点，避免重复
    for b in pg["bullets"]:
        if len(pg["bullets"]) > 1 and big and big in b:
            for k, bl in enumerate(wrap(b.replace(big, "").strip("：: 的，,")[:40],
                                          20, W - 2 * MARGIN - 160)[:2]):
                inner += t(MARGIN, 520 + k * 32, bl, 20, MUTED) + NL
            break
    return page_frame(title, kicker, inner, pg.get("image_file"))


def layout_quote(pg, kicker):
    """引用页：竖向强调条 + 斜体感引文 + 出处。"""
    title = pg["title"]
    quote = pg["bullets"][0] if pg["bullets"] else title
    inner = '<rect x="%d" y="180" width="6" height="300" fill="%s"/>' % (MARGIN, ACCENT) + NL
    x = MARGIN + 44
    inner += t(MARGIN, 150, title[:30], 20, MUTED, ls="2") + NL
    y = 250
    for ln in wrap(quote, 32, W - 2 * MARGIN - 120)[:5]:
        inner += t(x, y, ln, 32, weight="bold") + NL
        y += 48
    if len(pg["bullets"]) > 1:
        inner += t(x, y + 24, "—— " + pg["bullets"][1][:30], 20, MUTED) + NL
    return page_frame(title, kicker, inner, pg.get("image_file"))


def layout_section(pg, kicker):
    """章节页：大号序号 + 章节名，横向分割线。"""
    title = pg["title"]
    index = str(pg.get("index", 0) + 1).zfill(2)
    inner = t(MARGIN, 260, index, 44, weight="bold", fill=ACCENT) + NL
    inner += '<rect x="%d" y="300" width="%d" height="1" fill="%s"/>' % (MARGIN, W - 2 * MARGIN, DIV) + NL
    y = 380
    for ln in wrap(title, 44, W - 2 * MARGIN)[:2]:
        inner += t(MARGIN, y, ln, 44, weight="bold") + NL
        y += 62
    if pg["bullets"]:
        for j, bl in enumerate(wrap(pg["bullets"][0], 20, W - 2 * MARGIN)[:1]):
            inner += t(MARGIN, y + 20 + j * 32, bl, 20, MUTED) + NL
    return page_frame(title, kicker, inner, pg.get("image_file"))


def layout_closing(pg, kicker):
    """收束页：居中大字 + 底部横线，给"结束感"。"""
    title = pg["title"]
    px = snap(title_font_size(title, 44))
    lines = wrap(title, px, W - 2 * MARGIN - 200)[:3]
    total_h = len(lines) * int(px * 1.35)
    y = (H - total_h) // 2
    inner = ""
    for i, ln in enumerate(lines):
        inner += t(MARGIN, y + i * int(px * 1.35), ln, px, weight="bold") + NL
    for b in pg["bullets"][:2]:
        y2 = y + total_h + 40
        for j, bl in enumerate(wrap(b, 20, W - 2 * MARGIN - 200)[:1]):
            inner += t(MARGIN, y2 + j * 32, bl, 20, MUTED) + NL
            y2 += 32
    inner += '<rect x="%d" y="%d" width="120" height="3" fill="%s"/>' % (W // 2 - 60, y + total_h + 70, ACCENT) + NL
    return page_frame(title, kicker, inner, pg.get("image_file"))


# 9 种版式全部实现。旧版只实现 4 种，statement/fact/quote/section/closing
# 全部 fallback 到 bullets——这是「内容驱动」输出难看的直接原因。
LAYOUTS = {"cover": layout_cover, "bullets": layout_bullets,
           "compare": layout_compare, "steps": layout_steps,
           "statement": layout_statement, "fact": layout_fact,
           "quote": layout_quote, "section": layout_section,
           "closing": layout_closing}


def main(argv=None):
    ap = argparse.ArgumentParser(description="分页计划 -> SVG")
    ap.add_argument("--pages", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    plan = json.loads(args.pages.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    total = len(plan["pages"])
    for pg in plan["pages"]:
        fn = LAYOUTS.get(pg.get("layout", "bullets"), layout_bullets)
        kicker = "%s · %02d/%02d" % (plan["title"][:18], pg["index"] + 1, total)
        svg = fn(pg, kicker)
        (args.out / ("%02d_%s.svg" % (pg["index"], pg["layout"]))).write_text(svg, encoding="utf-8")
    print("%d 页 SVG -> %s" % (total, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
