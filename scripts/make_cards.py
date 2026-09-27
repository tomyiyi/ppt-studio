#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_cards.py —— SVG 画布 → 竖版传播卡片
=========================================

把 1280×720 的横向画布重排成 1080×1350（3:4）的竖版卡片，
用于微信 / 小红书 / 社群传播。

为什么不是「拉伸 + 裁切」：
  16:9 拉成 3:4 会横向裁掉 55% 的画面（slice 的代价），
  而且横版的字号在手机上会小到读不清。
  所以卡片是**重排**：抽内容要素 + 换一套竖版字号阶梯 + 重定版式。

内容源是 SVG 本身（不是 notes/*.md），保证卡片和 PPT 说的是同一件事。

用法：
  python3 make_cards.py [project] [--out cards] [--ratio 3:4|9:16] [--only 02]
  （未传 project 时自动从当前目录或 projects/ 下发现唯一有效项目）

产物：
  <project>/<out>/NN_name.svg
"""

from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from scripts.qa_cards import run_qa_cards, qa_cards
except ImportError:
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from scripts.qa_cards import run_qa_cards, qa_cards
    except ImportError:
        run_qa_cards = None
        qa_cards = None

# ---------------------------------------------------------------- 画布常量
MARGIN = 80
SAFE = 64                      # 硬安全边距，质检按这条查
BAND_H = 640                   # 图片带高度：再高面板就装不下内容，再低图就没存在感
FOOTER_Y = 1250                # 基线。28px 字底 = 1257，离安全边 1286 还有余量

BG = "#0B0C12"
BG_TOP = "#12131B"
FG = "#F7F7F9"
MUTED = "#A8A9B4"
DIM = "#7F8090"
ACCENT = "#6E7BFF"
RULE = "#23242E"
FONT = '"PingFang SC", "Microsoft YaHei", "Hiragino Sans GB", Arial, sans-serif'
NUM_FONT = 'Arial, Helvetica, sans-serif'

# 卡片字号阶梯（唯一真源：card_spec.md）
CARD_RAMP = {28, 36, 44, 56, 72, 96, 132}

# 源画布字号 → 卡片角色
def role_of(fs: float) -> str:
    if fs >= 72:
        return "hero"
    if fs >= 44:
        return "big"
    if fs >= 32:
        return "title"
    if fs >= 24:
        return "subtitle"
    if fs >= 16:
        return "body"
    return "kicker"

CARD_SIZE = {
    "hero": 132, "statement": 72, "metric": 96, "title": 56,
    "subtitle": 44, "body": 36, "kicker": 28,
}

NUMERIC = re.compile(r"^[\s\d.,%+\-/xX×~]+[a-zA-Z]{0,3}$")
# ⚠️ badge 不在跳过列表里 —— 它要被单独抽出来当卡片右上角徽章，
#    加进来会让徽章永远抽不到（踩过）。
SKIP_GROUPS = {"background", "footer", "chart", "terminal",
               "axis", "legend", "capability-icon"}

# ---------------------------------------------------------------- 文本宽度
def char_w(ch: str, fs: float) -> float:
    """估算字宽。CJK 按 1.0em，拉丁按字形类别细分。"""
    o = ord(ch)
    if o > 0x2E80:                       # CJK / 全角
        return fs * 1.0
    if ch in "iljItf.,;:'|!()[]":
        return fs * 0.30
    if ch in "MW@%":
        return fs * 0.92
    if ch.isupper():
        return fs * 0.68
    if ch.isdigit():
        return fs * 0.56
    return fs * 0.55

def wrap_runs(runs, fs, max_w, ls=0.0, max_lines=99):
    """runs = [(text, fill)]，按字符折行，输出 [[(text, fill), ...], ...]。"""
    chars = []
    for t, fill in runs:
        for ch in t:
            chars.append((ch, fill))
    lines, cur, cur_w = [], [], 0.0
    last_space = -1
    for i, (ch, fill) in enumerate(chars):
        w = char_w(ch, fs) + ls
        if cur_w + w > max_w and cur:
            # 拉丁文本优先在空格断开
            cut = len(cur)
            if last_space > 0 and len(cur) - last_space < 12:
                cut = last_space
            lines.append(cur[:cut])
            cur = cur[cut:]
            cur_w = sum(char_w(c, fs) + ls for c, _ in cur)
            last_space = -1
        if ch == " ":
            last_space = len(cur)
        cur.append((ch, fill))
        cur_w += w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        el = lines[-1]
        flat = "".join(c for c, _ in el)[:-1] + "…"
        lines[-1] = [(flat, el[0][1])]
    return lines

def merge_runs(line):
    out = []
    for ch, fill in line:
        if out and out[-1][1] == fill:
            out[-1] = (out[-1][0] + ch, fill)
        else:
            out.append((ch, fill))
    return out

def runs_width(runs, fs, ls=0.0):
    return sum(char_w(c, fs) + ls for t, _ in runs for c in t)

# ---------------------------------------------------------------- 解析源 SVG
def iter_with_parents(root):
    """带祖先链遍历。font-size / font-weight / fill 常写在父 <g> 上。"""
    stack = [(root, [])]
    while stack:
        e, anc = stack.pop()
        yield e, anc
        for k in reversed(list(e)):
            stack.append((k, anc + [e]))

def inherit(e, anc, key, default=None):
    for a in reversed(anc):
        v = a.get(key)
        if v:
            return v
    return e.get(key, default)

def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

def text_runs(t):
    """把 <text>（含 <tspan>）摊平为 [(text, fill)]，保留高亮色。"""
    runs = []
    own_fill = t.get("fill")
    if t.text:
        runs.append((t.text, own_fill))
    for child in t:
        tag = child.tag.split("}")[-1]
        if tag == "tspan":
            runs.append((child.text or "", child.get("fill") or own_fill))
            if child.tail:
                runs.append((child.tail, own_fill))
        if child.tail and tag != "tspan":
            runs.append((child.tail, own_fill))
    return [(r[0], r[1]) for r in runs if r[0]]

def parse_page(svg_path):
    root = ET.parse(svg_path).getroot()
    texts, bg_img, badge = [], None, None

    badge_txt, badge_lab, chip_fill = None, None, "#4ADE80"
    for e, anc in iter_with_parents(root):
        tag = e.tag.split("}")[-1]
        gid_now = next((a.get("id", "") for a in anc if a.get("id")), "")
        # 徽章的底色在 <circle>/<rect> 上，数字才是徽章本体
        if gid_now == "badge" and tag in ("circle", "rect"):
            if e.get("fill"):
                chip_fill = e.get("fill")
            continue
        if tag == "image":
            href = e.get("href") or e.get("{http://www.w3.org/1999/xlink}href")
            if href and bg_img is None:
                bg_img = href
            continue
        if tag != "text":
            continue

        gid = next((a.get("id", "") for a in anc if a.get("id")), "")
        if gid in SKIP_GROUPS:
            continue

        fs = float(inherit(e, anc, "font-size", "16") or 16)
        runs = text_runs(e)
        flat = "".join(r[0] for r in runs).strip()
        if not flat:
            continue

        fill = inherit(e, anc, "fill", FG) or FG
        rec = {
            "text": flat,
            "runs": runs,
            "fs": fs,
            "role": role_of(fs),
            "fill": fill if fill.startswith("#") else FG,
            "x": float(e.get("x", 0)),
            "y": float(e.get("y", 0)),
            "gid": gid,
            "numeric": bool(NUMERIC.match(flat)) and any(c.isdigit() for c in flat),
            "weight": "bold" if (inherit(e, anc, "font-weight", "") == "bold") else "",
            "numfont": NUM_FONT in (inherit(e, anc, "font-family", "") or ""),
        }
        if gid == "badge":
            # 徽章组里通常有「数字 + 标签」两段文字：数字（y 小）= 徽章本体，
            # 标签（y 大）= 注解。只取数字当徽章，否则会把中文短语塞进小圆牌里。
            if badge_txt is None or rec["y"] < badge_txt["y"]:
                if badge_txt is not None:
                    badge_lab = badge_txt
                badge_txt = rec
            elif badge_lab is None or rec["y"] > badge_lab["y"]:
                badge_lab = rec
        else:
            texts.append(rec)

    if badge_txt:
        badge_txt["chip"] = chip_fill
        badge_txt["lab"] = badge_lab["text"] if badge_lab else ""
    texts.sort(key=lambda r: (r["y"], r["x"]))
    return texts, bg_img, badge_txt

def pick(texts, badge, focus):
    """从一页里挑出卡片要用的内容要素。"""
    hero = next((t for t in texts if t["role"] == "hero"), None)
    big = [t for t in texts if t["role"] == "big"]
    statement = [t for t in texts if t["role"] == "big" and not t["numeric"]]
    metrics = [t for t in texts if t["role"] == "big" and t["numeric"]]
    titles = [t for t in texts if t["role"] == "title"]
    subs = [t for t in texts if t["role"] == "subtitle"]
    bodies = [t for t in texts if t["role"] == "body" and not t["numeric"]]
    kickers = [t for t in texts if t["role"] == "kicker"]

    # 主句优先级：hero > statement > 人工指定的 focus > 最长 subtitle > 最长 body
    if hero:
        primary, primary_kind = hero, "hero"
    elif statement:
        primary, primary_kind = statement[0], "statement"
        if len(statement) > 1:
            # 两行主句合并：中文不插空格，英文才插
            a_txt, b_txt = statement[0]["text"], statement[1]["text"]
            glue = "" if (ord(b_txt[0]) > 0x2E80 or ord(a_txt[-1]) > 0x2E80) else " "
            primary = {"text": a_txt + glue + b_txt,
                       "runs": statement[0]["runs"] + ([(glue, None)] if glue else [])
                                + statement[1]["runs"]}
    elif focus:
        primary, primary_kind = {"text": focus, "runs": [(focus, None)]}, "statement"
    elif subs:
        primary, primary_kind = max(subs, key=lambda t: len(t["text"])), "statement"
    elif bodies:
        primary, primary_kind = max(bodies, key=lambda t: len(t["text"])), "body"
    else:
        primary, primary_kind = None, "none"

    # 主句若被 focus 覆盖，正文仍从 subtitle / body 里取，但要排除与主句重复的那条
    dup = primary["text"] if primary else ""
    support = [t for t in (subs + bodies) if t["text"] != dup and len(t["text"]) > 6]
    # 去重 + 按长度排序取前两条
    seen, sup2 = set(), []
    for t in sorted(support, key=lambda t: -len(t["text"])):
        if t["text"] in seen:
            continue
        seen.add(t["text"])
        sup2.append(t)
        if len(sup2) >= 2:
            break

    # 指标：source 里 44px 的数字 + 紧随其后的小字标签
    m_pairs = []
    for m in metrics:
        lab = min((t for t in texts if t["role"] == "kicker"
                   and abs(t["x"] - m["x"]) < 60 and t["y"] > m["y"]),
                  default=None, key=lambda t: t["y"] - m["y"])
        m_pairs.append((m, lab))
    # ⚠️ 不要把 badge 兜底塞进指标区 —— 它已经画在图片带右上角了，
    #    再来一遍就是重影。

    kicker = kickers[0]["text"] if kickers else ""
    foot = [t for t in texts if "footer" in t["gid"]]
    return dict(primary=primary, kind=primary_kind, support=sup2,
                metrics=m_pairs, kicker=kicker, badge=badge,
                title=titles[0] if titles else None, hero=hero)

# ---------------------------------------------------------------- 生成卡片
def card_svg(
    name: str,
    page: str,
    c: dict,
    bg_img: str | None,
    idx: int,
    total: int,
    W: int,
    H: int,
    colors: dict[str, str] | None = None,
    sizes: dict[str, int] | None = None,
) -> str:
    if colors is None:
        colors = {}
    if sizes is None:
        sizes = {}

    c_bg = colors.get("bg", BG)
    c_bg_top = colors.get("bg_top", BG_TOP)
    c_bg_bottom = colors.get("bg_bottom", colors.get("background", "#08090C"))
    c_fg = colors.get("fg", FG)
    c_muted = colors.get("muted", MUTED)
    c_dim = colors.get("dim", DIM)
    c_accent = colors.get("accent", ACCENT)
    c_rule = colors.get("rule", RULE)

    s_hero = sizes.get("hero", CARD_SIZE["hero"])
    s_statement = sizes.get("statement", CARD_SIZE["statement"])
    s_metric = sizes.get("metric", CARD_SIZE["metric"])
    s_title = sizes.get("title", CARD_SIZE["title"])
    s_subtitle = sizes.get("subtitle", CARD_SIZE["subtitle"])
    s_body = sizes.get("body", CARD_SIZE["body"])
    s_kicker = sizes.get("kicker", CARD_SIZE["kicker"])

    content_w = W - MARGIN - (MARGIN + 44)      # 左侧留主句竖线的位置
    text_x = MARGIN + 44
    o, a = [], None
    a = o.append

    # ===== 一、装配内容块
    # 折行只依赖画布宽度，与图片带高度无关 —— 所以先算内容，再决定图占多少。
    blocks_fixed = []    # 主句 / 副标 —— 永不砍
    support_blocks = []  # 副句 —— 空间不足时优先砍

    def text_block(runs, size, color, lh, ls, weight, max_lines, x, w):
        lines = wrap_runs(runs, size, w, ls, max_lines)
        h = len(lines) * size * lh
        def draw(y):
            out = []
            for i, ln in enumerate(lines):
                by = y + size * 0.80 + i * size * lh
                segs = "".join(
                    f'<tspan fill="{f or color}">{esc(t)}</tspan>' for t, f in merge_runs(ln))
                w8 = f' font-weight="bold"' if weight else ""
                lsx = f' letter-spacing="{ls}"' if ls else ""
                out.append(f'    <text x="{x}" y="{by:.0f}" font-size="{size}" '
                           f'fill="{color}"{w8}{lsx}>{segs}</text>')
            return out
        return h, draw, lines

    p = c["primary"]
    if p:
        size = s_hero if c["kind"] == "hero" else s_statement
        lh = 1.12 if c["kind"] == "hero" else 1.34
        maxl = 2 if c["kind"] == "hero" else 3
        h, draw, _ = text_block(p["runs"], size, c_fg, lh, 0.0, True, maxl, text_x, content_w)
        blocks_fixed.append(("primary", h, draw))

    if c["title"] and c["kind"] == "hero":
        h, draw, _ = text_block(c["title"]["runs"], s_title, c_accent, 1.25,
                                0.0, False, 1, text_x, content_w)
        blocks_fixed.append(("title", h, draw))

    for i, s in enumerate(c["support"]):
        h, draw, _ = text_block(s["runs"], s_body, c_muted, 1.50,
                                0.0, False, 2, text_x, content_w)
        support_blocks.append((f"support{i}", h, draw))

    def mk_metrics(n):
        def draw_m(y):
            out = []
            col_w = content_w / n
            for i, (m, lab) in enumerate(c["metrics"][:n]):
                cx = text_x + int(col_w * i)
                out.append(f'    <text x="{cx}" y="{y + 76:.0f}" font-size="{s_metric}" '
                           f'font-weight="bold" font-family=\'{NUM_FONT}\' '
                           f'fill="{c_accent}">{esc(m["text"])}</text>')
                if lab:
                    lt = lab["text"]
                    if len(lt) > 8:
                        lt = lt[:8] + "…"
                    out.append(f'    <text x="{cx}" y="{y + 120:.0f}" font-size="{s_kicker}" '
                               f'fill="{c_dim}">{esc(lt)}</text>')
            return out
        return ("metrics", 140, draw_m)

    def build(n_sup, n_met):
        bl = list(blocks_fixed)
        for i in range(n_sup):
            bl.append(support_blocks[i])
        if n_met:
            bl.append(mk_metrics(n_met))
        g = [0]
        for i in range(1, len(bl)):
            prev = bl[i - 1][0]
            g.append(40 if bl[i][0].startswith("support") and prev in ("primary", "title")
                     else 56)
        return bl, g

    def stack_h(bl, g):
        return sum(b[1] for b in bl) + sum(g)

    # ===== 二、自适应图片带
    # 固定 47% 会让「只有一句主句」的卡片下半屏空着（实测 04 面板墨量仅 2.96%）。
    # 内容少 → 图涨到 62%；内容多 → 图让位到 40%。
    avail_bottom = FOOTER_Y - 56
    n_sup, n_met = len(support_blocks), len(c["metrics"])
    blocks, gaps = build(n_sup, n_met)
    st = stack_h(blocks, gaps)
    band = int(H - (72 + st + (H - avail_bottom)))
    band = max(int(H * 0.40), min(int(H * 0.62), band))
    avail = avail_bottom - (band + 72)

    while st > avail:
        if n_sup > 0:
            n_sup -= 1                      # 先砍副句
        elif n_met > 1:
            n_met -= 1                      # 再减指标
        elif n_met == 1:
            n_met = 0
        else:
            break                           # 只剩主句，砍不动了
        blocks, gaps = build(n_sup, n_met)
        st = stack_h(blocks, gaps)

    dropped = (len(support_blocks) - n_sup, len(c["metrics"]) - n_met)
    if any(dropped):
        print(f"    [fit] {name}: 空间不足，砍掉 {dropped[0]} 条副句 / {dropped[1]} 个指标")

    band_h = panel_top = band
    y0 = (band + 72) + max(0, avail - st) * 0.32

    # ===== 三、出图
    a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
      f'width="{W}" height="{H}" font-family=\'{FONT}\'>')
    a("<defs>")
    a('  <linearGradient id="band-scrim" x1="0" y1="0" x2="0" y2="1">')
    # ⚠️ 遮罩别压太狠：第一版 0.88/0.42/0.08/0.30 把 P99≈60 的暗图压到
    #    全带墨量 0.7%，等于没图。现在只护住顶部眉标那一条。
    a(f'    <stop offset="0" stop-color="{c_bg_bottom}" stop-opacity="0.78"/>')
    a(f'    <stop offset="0.22" stop-color="{c_bg_bottom}" stop-opacity="0.28"/>')
    a(f'    <stop offset="0.58" stop-color="{c_bg_bottom}" stop-opacity="0.05"/>')
    a(f'    <stop offset="1" stop-color="{c_bg_bottom}" stop-opacity="0.16"/>')
    a("  </linearGradient>")
    a(f'  <linearGradient id="band-fade" x1="0" y1="0" x2="0" y2="1">')
    a(f'    <stop offset="0" stop-color="{c_bg}" stop-opacity="0"/>')
    a(f'    <stop offset="1" stop-color="{c_bg}" stop-opacity="0.96"/>')
    a("  </linearGradient>")
    a(f'  <linearGradient id="panel-grad" x1="0" y1="0" x2="0" y2="1">')
    a(f'    <stop offset="0" stop-color="{c_bg_top}" stop-opacity="1"/>')
    a(f'    <stop offset="1" stop-color="{c_bg_bottom}" stop-opacity="1"/>')
    a("  </linearGradient>")
    a("</defs>")

    # ---- 图片带
    a('<g id="card-image">')
    a(f'  <rect width="{W}" height="{band_h}" fill="{c_bg_bottom}"/>')
    if bg_img:
        a(f'  <image href="{esc(bg_img)}" x="0" y="0" width="{W}" height="{band_h}" '
          f'preserveAspectRatio="xMidYMid slice"/>')
    a(f'  <rect width="{W}" height="{band_h}" fill="url(#band-scrim)"/>')
    a(f'  <rect x="0" y="{band_h - 130}" width="{W}" height="130" fill="url(#band-fade)"/>')
    a("</g>")

    # ---- 眉标
    if c["kicker"]:
        a(f'  <text x="{MARGIN}" y="112" font-size="{s_kicker}" fill="{c_muted}" '
          f'letter-spacing="6">{esc(c["kicker"])}</text>')

    # ---- 徽章（右上角）：数字进圆牌，标签排在下面
    if c["badge"]:
        bt = c["badge"]["text"]
        chip = c["badge"].get("chip", "#4ADE80")
        cjk = any(ord(ch) > 0x2E80 for ch in bt)
        bf = FONT if cjk else NUM_FONT
        bw = max(88, int(runs_width([(bt, None)], 36, 1.0)) + 56)
        bx = W - MARGIN - bw
        a(f'  <rect x="{bx}" y="80" width="{bw}" height="60" rx="30" fill="{chip}"/>')
        a(f'  <text x="{bx + bw // 2}" y="121" text-anchor="middle" font-size="36" '
          f'font-weight="bold" font-family=\'{bf}\' fill="{c_bg_bottom}">{esc(bt)}</text>')
        if c["badge"].get("lab"):
            a(f'  <text x="{W - MARGIN}" y="168" text-anchor="end" font-size="{s_kicker}" '
              f'fill="{c_muted}">{esc(c["badge"]["lab"])}</text>')

    # ---- 内容面板
    a('<g id="card-panel">')
    a(f'  <rect x="0" y="{panel_top}" width="{W}" height="{H - panel_top}" '
      f'fill="url(#panel-grad)"/>')

    y = y0
    for (kind, h, draw), g in zip(blocks, gaps):
        y += g
        for line in draw(y):
            a("  " + line)
        y += h

    # 主句左侧竖线（卡片签名元素）
    if p is not None and blocks:
        ph = blocks[0][1]
        a(f'  <rect x="{MARGIN}" y="{y0 + 8:.0f}" width="6" height="{ph - 16:.0f}" '
          f'rx="3" fill="{c_accent}"/>')

    # ---- 页脚
    a(f'  <line x1="{MARGIN}" y1="{FOOTER_Y - 44}" x2="{W - MARGIN}" '
      f'y2="{FOOTER_Y - 44}" stroke="{c_rule}" stroke-width="1"/>')
    a(f'  <text x="{W - MARGIN}" y="{FOOTER_Y}" text-anchor="end" font-size="{s_kicker}" '
      f'fill="{c_dim}">{idx:02d} / {total:02d}</text>')
    a(f'  <text x="{MARGIN}" y="{FOOTER_Y}" font-size="{s_kicker}" fill="{c_dim}">'
      f'{esc(page)}</text>')
    a("</g>")
    a("</svg>")
    return "\n".join(o)

# ---------------------------------------------------------------- 比率
def ratio_wh(spec: str):
    # 图片带只是初值，实际高度由 card_svg 按内容量自适应（40%~62%）
    if spec == "3:4":
        return 1080, 1350, 640
    if spec == "9:16":
        return 1080, 1920, 900
    if spec == "1:1":
        return 1080, 1080, 520
    m = re.match(r"^(\d+):(\d+)$", spec)
    if not m:
        raise SystemExit(f"不支持的比率 {spec}")
    w, h = int(m.group(1)), int(m.group(2))
    W = 1080
    H = int(round(W * h / w / 10.0)) * 10
    return W, H, int(H * 0.52)

# ---------------------------------------------------------------- main
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
            # 检查是否有渐变终点颜色，如 bg #0B0C12 → #08090C
            m_arrow = re.search(r"(?:→|->)\s*\"?(#[0-9a-fA-F]{6})\"?", line)
            if m_arrow:
                colors[f"{key}_bottom"] = m_arrow.group(1).upper()

    if "accent" not in colors and "accent_color" not in colors:
        m = re.search(r"\baccent(?:_color)?\s*[:=\s]\s*\"?(#[0-9a-fA-F]{6})\"?", content)
        if m:
            colors["accent"] = m.group(1).upper()

    if "bg" not in colors and "background" not in colors and "bg_color" not in colors:
        m = re.search(r"\b(?:bg|background)(?:_color)?\s*[:=\s]\s*\"?(#[0-9a-fA-F]{6})\"?", content)
        if m:
            colors["bg"] = m.group(1).upper()

    return colors


def load_spec_colors(project_dir: str | Path | None) -> dict[str, str]:
    """从 card_spec.md 或 spec_lock.md 读取色彩配置，支持 YAML 列表、行内注释与双规范回退。"""
    colors = {
        "bg": BG,
        "bg_top": BG_TOP,
        "bg_bottom": "#08090C",
        "fg": FG,
        "muted": MUTED,
        "dim": DIM,
        "accent": ACCENT,
        "rule": RULE,
    }
    if not project_dir:
        return colors

    p = Path(project_dir).resolve()
    candidate_files: list[Path] = []
    if p.is_file():
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

    seen = set()
    for cand in candidate_files:
        if not cand.is_file():
            continue
        rcand = cand.resolve()
        if rcand in seen:
            continue
        seen.add(rcand)

        try:
            txt = rcand.read_text(encoding="utf-8")
            parsed = parse_colors_from_spec_text(txt)
            if "accent" in parsed:
                colors["accent"] = parsed["accent"]
            elif "accent_color" in parsed:
                colors["accent"] = parsed["accent_color"]

            if "bg" in parsed:
                colors["bg"] = parsed["bg"]
            elif "background" in parsed:
                colors["bg"] = parsed["background"]
            elif "bg_color" in parsed:
                colors["bg"] = parsed["bg_color"]

            if "bg_bottom" in parsed:
                colors["bg_bottom"] = parsed["bg_bottom"]
            elif "background" in parsed:
                colors["bg_bottom"] = parsed["background"]

            if "bg_top" in parsed:
                colors["bg_top"] = parsed["bg_top"]

            if "fg" in parsed:
                colors["fg"] = parsed["fg"]
            elif "text_main" in parsed:
                colors["fg"] = parsed["text_main"]

            if "muted" in parsed:
                colors["muted"] = parsed["muted"]
            elif "text_muted" in parsed:
                colors["muted"] = parsed["text_muted"]

            if "dim" in parsed:
                colors["dim"] = parsed["dim"]
            elif "text_dim" in parsed:
                colors["dim"] = parsed["text_dim"]

            if "rule" in parsed:
                colors["rule"] = parsed["rule"]
        except (OSError, UnicodeError):
            pass

    return colors


def load_spec_roles(project_dir: str | Path | None) -> dict[str, int]:
    """从 card_spec.md 读取字号角色映射 (statement, hero, metric, title, subtitle, body, kicker)。"""
    roles = dict(CARD_SIZE)
    if not project_dir:
        return roles

    p = Path(project_dir).resolve()
    candidate_files: list[Path] = []
    if p.is_file():
        candidate_files.append(p)
        candidate_files.append(p.parent / "card_spec.md")
    elif p.is_dir():
        candidate_files.append(p / "card_spec.md")

    repo_root = Path(__file__).resolve().parent.parent
    for base in [Path.cwd(), repo_root]:
        candidate_files.append(base / "card_spec.md")

    seen = set()
    for cand in candidate_files:
        if not cand.is_file():
            continue
        rcand = cand.resolve()
        if rcand in seen:
            continue
        seen.add(rcand)

        try:
            txt = rcand.read_text(encoding="utf-8")
            m = re.search(r"^##\s+typography\s*$(.*?)(?=^##\s|\Z)", txt, re.S | re.M)
            if m:
                for line in m.group(1).splitlines():
                    line = line.split("#")[0].strip()
                    if not line:
                        continue
                    # 支持 72 statement 或 - 72 statement
                    mm1 = re.match(r"^[-*]?\s*(\d+)\s+([a-zA-Z_]\w*)", line)
                    if mm1:
                        roles[mm1.group(2)] = int(mm1.group(1))
                        continue
                    # 支持 - statement: 72 或 statement: 72
                    mm2 = re.match(r"^[-*]?\s*([a-zA-Z_]\w*)\s*[:=]\s*(\d+)", line)
                    if mm2:
                        roles[mm2.group(1)] = int(mm2.group(2))
        except (OSError, UnicodeError):
            pass

    return roles


def load_deck_title(
    project_dir: str | Path | None,
    src_svg_files: list[Path] | None = None,
) -> str:
    """提取卡片页脚项目/演示标题。"""
    # 1. 尝试从封面 SVG (如 01_cover.svg) 提取大标题
    if src_svg_files:
        for f in src_svg_files:
            if "01" in f.name or "cover" in f.name:
                try:
                    texts, _, _ = parse_page(str(f))
                    heroes = [t for t in texts if t.get("fs", 0) >= 72 and t.get("text", "").strip()]
                    if heroes:
                        title_candidate = heroes[0]["text"].strip()
                        if title_candidate and len(title_candidate) <= 20:
                            return title_candidate
                except Exception:
                    pass

    if project_dir:
        p = Path(project_dir)
        proj_dir = p.parent if p.is_file() else p
        # 2. 尝试从 notes/01_cover.md 提取
        cover_note = proj_dir / "notes" / "01_cover.md"
        if cover_note.is_file():
            try:
                for line in cover_note.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("#"):
                        t = line.lstrip("#").strip()
                        if t:
                            return t
            except Exception:
                pass

        # 3. 尝试从 card_spec.md / spec_lock.md 提取 title
        for spec_f in [proj_dir / "card_spec.md", proj_dir / "spec_lock.md"]:
            if spec_f.is_file():
                try:
                    content = spec_f.read_text(encoding="utf-8")
                    m = re.search(r"-\s*title\s*[:=]\s*(.+)", content)
                    if m:
                        return m.group(1).strip()
                except Exception:
                    pass

        # 4. 根据项目目录名推断
        name = proj_dir.name
        if "agentflow" in name.lower():
            return "智流 OS"
        cleaned = name.replace("-", " ").replace("_", " ").title()
        if cleaned:
            return cleaned

    return "智流 OS"


def load_focus(project):
    """card_spec.md 的 ## focus 段：页码: 主句（源页没有 statement 档时人工指定）。"""
    p = Path(project) / "card_spec.md"
    if not p.is_file():
        return {}
    txt = p.read_text(encoding="utf-8")
    m = re.search(r"^##\s+focus\s*$(.*?)(?=^##\s|\Z)", txt, re.S | re.M)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^\s*(\d{2})\s*[:：]\s*(.+?)\s*$", line)
        if mm:
            out[mm.group(1)] = mm.group(2)
    return out

def resolve_project_dir(
    project_arg: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> Path:
    """自适应探测包含 svg_output/*.svg 的项目目录。

    保留显式 project 参数行为；
    未传时从当前目录或 projects/ 下安全发现唯一包含 svg_output/*.svg 的项目。
    """
    if project_arg is not None and str(project_arg).strip() != "":
        proj = Path(project_arg)
        if not proj.is_absolute() and base_dir is not None:
            proj = (Path(base_dir) / proj).resolve()
        else:
            proj = proj.resolve()
        if not proj.exists():
            raise FileNotFoundError(f"指定的项目目录不存在: {project_arg}")
        return proj

    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()

    def has_svg_output(p: Path) -> bool:
        svg_dir = p / "svg_output"
        return svg_dir.is_dir() and any(svg_dir.glob("*.svg"))

    # 1. 当前目录本身包含 svg_output/*.svg
    if has_svg_output(base):
        return base

    # 2. 从 projects/ 目录下安全发现
    candidate_projects_dirs: list[Path] = []
    if base.is_dir() and base.name == "projects":
        candidate_projects_dirs.append(base)
    elif (base / "projects").is_dir():
        candidate_projects_dirs.append(base / "projects")
    elif base_dir is None:
        for cand in [base.parent, base.parent.parent, Path(__file__).resolve().parent.parent]:
            try:
                p_cand = cand / "projects"
                if p_cand.is_dir() and p_cand.resolve() not in [d.resolve() for d in candidate_projects_dirs]:
                    candidate_projects_dirs.append(p_cand)
                    break
            except Exception:
                pass

    found: list[Path] = []
    seen: set[Path] = set()

    for p_dir in candidate_projects_dirs:
        for sub in sorted(p_dir.iterdir()):
            if sub.is_dir() and has_svg_output(sub):
                r_sub = sub.resolve()
                if r_sub not in seen:
                    seen.add(r_sub)
                    found.append(r_sub)
        if found:
            break

    if len(found) == 1:
        return found[0]
    elif len(found) == 0:
        raise FileNotFoundError(
            "未在当前目录或 projects/ 下发现包含 svg_output/*.svg 的项目，请显式指定 project 参数"
        )
    else:
        names = ", ".join(p.name for p in found)
        raise ValueError(
            f"发现多个包含 svg_output 的项目 ({names})，无法安全确定，请显式指定 project 参数"
        )


def make_cards(
    project_dir: str | Path | None = None,
    out_dir_name: str = "cards",
    ratio: str = "3:4",
    only: str | None = None,
    check: bool = False,
    spec_path: str | Path | None = None,
) -> list[Path]:
    """生成竖版传播卡片，支持指定比例、页面过滤与质量门禁校验。"""
    proj_dir = resolve_project_dir(project_dir)
    src_dir = proj_dir / "svg_output"
    out_dir = proj_dir / out_dir_name
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.", dir=proj_dir))
    backup: Path | None = None
    try:
        if only and out_dir.is_dir():
            for existing in out_dir.iterdir():
                target = staging_dir / existing.name
                if existing.is_dir():
                    shutil.copytree(existing, target)
                else:
                    shutil.copy2(existing, target)
        if not src_dir.is_dir():
            raise FileNotFoundError(f"项目缺少 svg_output 目录: {src_dir}")
        files = sorted(f for f in src_dir.iterdir() if f.suffix == ".svg")
        if only:
            files = [f for f in files if only in f.name]
        if not files:
            raise FileNotFoundError(f"未在 {src_dir} 找到任何待处理的 SVG 文件")

        W, H, band_h = ratio_wh(ratio)
        proj_str = str(proj_dir)
        focus = load_focus(proj_str)
        total = len(files)
        spec_target = spec_path if spec_path else proj_str
        colors = load_spec_colors(spec_target)
        sizes = load_spec_roles(spec_target)
        all_src_files = sorted(src_dir.glob("*.svg"))
        deck_title = load_deck_title(proj_str, all_src_files)

        generated: list[Path] = []
        for i, fpath in enumerate(files, 1):
            stem = fpath.stem
            page_no = stem[:2]
            texts, bg_img, badge = parse_page(str(fpath))
            c = pick(texts, badge, focus.get(page_no))
            if not c["primary"] and not c["metrics"]:
                print(f"  [skip] {fpath.name} 无可提取内容")
                continue
            svg = card_svg(stem, deck_title, c, bg_img, i, total, W, H, colors=colors, sizes=sizes)
            dst = staging_dir / f"{stem}.svg"
            dst.write_text(svg, encoding="utf-8")
            print(f"✓ {fpath.name} → {dst}  主句[{c['kind']}]  指标 {len(c['metrics'])}")
            generated.append(dst)

        print(f"完成 {len(generated)}/{len(files)}  ({W}×{H}, 图片带 {band_h}px)")
        if check and run_qa_cards is not None:
            if not run_qa_cards(staging_dir, spec_path=spec_path):
                raise RuntimeError(f"卡片客观质量门禁未通过: {out_dir}")
            print("  [门禁] ✓ 卡片客观质量门禁通过")
        elif check:
            print("  [warn] 未导入 run_qa_cards，跳过门禁检查")

        if out_dir.exists():
            backup = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.old.", dir=proj_dir))
            backup.rmdir()
            os.replace(out_dir, backup)
        try:
            os.replace(staging_dir, out_dir)
        except Exception:
            if backup is not None and not out_dir.exists():
                os.replace(backup, out_dir)
                backup = None
            raise
        staging_dir = None  # type: ignore[assignment]
        if backup is not None:
            shutil.rmtree(backup)
            backup = None
        return [out_dir / path.name for path in generated]
    except Exception:
        if staging_dir is not None and staging_dir.exists():
            shutil.rmtree(staging_dir)
        if backup is not None and backup.exists() and not out_dir.exists():
            os.replace(backup, out_dir)
        raise


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SVG 画布 → 竖版传播卡片")
    ap.add_argument(
        "project",
        nargs="?",
        default=None,
        help="项目根目录，例如 projects/agentflow-os-launch（默认自动发现）",
    )
    ap.add_argument("--out", default="cards", help="输出目录名称（默认: cards）")
    ap.add_argument("--ratio", default="3:4", help="卡片宽高比（默认: 3:4）")
    ap.add_argument("--only", help="只处理文件名包含该串的页")
    ap.add_argument("--spec", help="自定义卡片规格文件路径（例如 card_spec.md）")
    ap.add_argument("--check", action="store_true", help="构建完成后执行卡片客观质量门禁校验 (qa_cards.py)")
    args = ap.parse_args(argv)

    try:
        make_cards(
            project_dir=args.project,
            out_dir_name=args.out,
            ratio=args.ratio,
            only=args.only,
            check=args.check,
            spec_path=args.spec,
        )
        return 0
    except (FileNotFoundError, ValueError, RuntimeError) as err:
        print(f"[err] {err}", file=sys.stderr)
        return 1
    except Exception as err:
        print(f"[err] {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
