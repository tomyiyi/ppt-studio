#!/usr/bin/env python3
"""7 个参数化版式配方。每个 recipe(pg: dict, tok: Tokens) -> 完整 SVG 文档字符串。
SVG 约束（vendor 门禁 + 本项目实测）：只允许 <rect>/<line>/<path>/<text>/<image>/<g>/<clipPath>，
禁止 <style>、class、mask、textPath、@font-face、<animate>、filter。"""
from __future__ import annotations
import html
import re
import xml.etree.ElementTree as ET

try:
    from cover_v2 import split_cover_title
except ImportError:
    def split_cover_title(title: str, max_lines: int = 3) -> list[str]:
        parts = re.split(r"[：:]|——|—", title, maxsplit=1)
        return [p.strip() for p in parts if p.strip()][:max_lines]

W, H = 1280, 720
DEFAULT_SANS = "Noto Sans SC"
HEI, MONO = "Noto Sans SC", "Menlo"

_COLOR_ALIASES = {"MUTED": "SUB2", "RULE": "STRUCT"}


def _colors(tok) -> dict:
    c = dict(tok.colors) if hasattr(tok, "colors") else {}
    for alias, real in _COLOR_ALIASES.items():
        c.setdefault(alias, c.get(real, "#999999"))
    for k in ("FIELD", "SURF", "STRUCT", "INK", "SUB", "SUB2", "FOCUS", "CAUTION"):
        c.setdefault(k, "#888888")
    return c


def _bg(tok, c: dict) -> str:
    return rect(0, 0, tok.canvas_w, tok.canvas_h, fill=c.get("FIELD", "#ffffff"))


def cjk(s: str) -> int:
    return sum(1 if ord(c) > 0x2E7F else 0.55 for c in s)


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def tx(x, y, s, size, fill, *, weight="400", family=DEFAULT_SANS, anchor="start",
       ls=None, opacity=None) -> str:
    a = (f' x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}"'
         f' font-family="{family}" text-anchor="{anchor}"')
    if ls is not None:
        a += f' letter-spacing="{ls}"'
    if opacity is not None:
        a += f' fill-opacity="{opacity}"'
    return f"<text{a}>{esc(s)}</text>"


def ln(x1, y1, x2, y2, stroke, wdt=1, dash=None) -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{stroke}" stroke-width="{wdt}"{d}/>')


def rect(x, y, w, h, *, fill="none", rx=0, stroke=None, sw=1, fill_op=None, dash=None) -> str:
    s = f' x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"'
    if fill_op is not None:
        s += f' fill-opacity="{fill_op}"'
    if rx:
        s += f' rx="{rx}"'
    if stroke:
        s += f' stroke="{stroke}" stroke-width="{sw}"'
    if dash:
        s += f' stroke-dasharray="{dash}"'
    return f"<rect{s}/>"


def svg_doc(title: str, body: str, role: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="1280" height="720" viewBox="0 0 1280 720" '
            f'data-pptx-page-role="{role}">'
            f'<title>{esc(title)}</title>'
            f'<g id="{role}">{body}</g></svg>')


def page_doc(pg: dict, body: str, role: str) -> str:
    return svg_doc(pg.get("title", ""), body, role)


def header(tok, kicker, sheet, assertion, so_what, c) -> str:
    assert cjk(assertion) * 44 <= tok.content_w, "断言标题超版心：拆行，不缩字号"
    return "".join([
        tx(tok.margin, 96, kicker, 13, c["MUTED"], family=MONO, ls=3),
        tx(tok.canvas_w - tok.margin, 96, sheet, 13, c["FOCUS"], anchor="end"),
        ln(tok.margin, 116, tok.canvas_w - tok.margin, 116, c["RULE"], 1),
        tx(tok.margin, 168, assertion, 44, c["INK"], weight="600"),
        tx(tok.margin, 204, so_what, 20, c["SUB"]),
    ])


def footer(tok, source, page_no, c) -> str:
    return "".join([
        ln(tok.margin, tok.canvas_h - 76, tok.canvas_w - tok.margin, tok.canvas_h - 76,
           c["RULE"], 1),
        tx(tok.margin, tok.canvas_h - 46, source, 13, c["SUB"]),
        tx(tok.canvas_w - tok.margin, tok.canvas_h - 46, f"{page_no:02d}", 13, c["MUTED"],
           family=MONO, anchor="end"),
    ])


def strip_cells(s: str) -> str:
    return s.strip().strip("|").strip()


def sheet_title(pg: dict) -> str:
    return pg.get("title", "")[:24] or f"P{pg.get('index', 0):02d}"


def source_line(pg: dict) -> str:
    ev = pg.get("evidence", [])
    if ev and isinstance(ev, list) and len(ev) > 0:
        src = ev[0].get("source", "") if isinstance(ev[0], dict) else ""
        if src:
            return src
    return pg.get("scope_note", "") or ""


def mechanism_nodes(pg: dict) -> list:
    """从 evidence 文本按 →/然后/再 切分成节点；切不出 ≥2 个时返回空。"""
    ev = pg.get("evidence", [])
    texts = [e.get("text", "") if isinstance(e, dict) else str(e) for e in ev]
    raw = " → ".join(t for t in texts if t)
    if not raw:
        return []
    parts = re.split(r"[→➜]|然后|再|接着", raw)
    nodes = []
    for p in parts:
        p = p.strip()
        if p:
            nodes.append({"label": p[:12], "note": p[12:30] if len(p) > 12 else ""})
    return nodes if len(nodes) >= 2 else []


RECIPE_FUNCS: dict[str, callable] = {}


def recipe(name):
    def deco(fn):
        RECIPE_FUNCS[name] = fn
        return fn
    return deco


RECIPES = {
    "cover": "cover_p1",
    "section": "section_anchor",
    "claim": "assertion_evidence",
    "data": "three_line_table",
    "mechanism": "mechanism_flow",
    "teaching": "teaching_pair",
    "closing": "action_list",
}
ROLE_TO_RECIPE = dict(RECIPES)


def render(page_dict, tok):
    lay = ROLE_TO_RECIPE.get(page_dict.get("role", ""))
    if lay is None:
        return None
    fn = RECIPE_FUNCS.get(lay)
    return fn(page_dict, tok) if fn else None


@recipe("three_line_table")
def recipe_three_line_table(pg, tok):
    c = _colors(tok)
    rows = pg.get("bullets", [])
    tbl = [r.split("|") for r in rows if r.strip().startswith("|")]
    tbl = [[strip_cells(x) for x in row if x.strip() != ""] for row in tbl]
    tbl = [r for r in tbl if r]
    sep = [i for i, r in enumerate(tbl) if set("".join(r)) <= set("-: ")]
    if sep:
        tbl = tbl[:sep[0]] + tbl[sep[0] + 1:]
    if not tbl:
        return page_doc(pg, "", "data")
    head, body = tbl[0], tbl[1:]
    assert len(head) <= 5, f"三线表列数 {len(head)} > 5，配方不适用（交人重排）"
    ty, hh, rh = 252, 32, 40
    assert ty + hh + len(body) * rh + 8 <= tok.canvas_h - 76, "表格压到页脚：拆页，不缩行高"
    x0, w = tok.margin, tok.content_w
    ncols = len(head)
    cw = w / ncols
    out = [_bg(tok, c)]
    out += list(header(tok, "DATA · " + str(pg["index"]).zfill(2),
                       sheet_title(pg), pg.get("assertion", ""),
                       pg.get("so_what", ""), c))
    out.append(rect(x0, ty, w, 2, fill=c["INK"]))
    for j, h in enumerate(head):
        right = j > 0 and any(ch.isdigit() for ch in h)
        out.append(tx(x0 + j * cw + (cw - 12 if right else 12), ty + hh - 10, h, 13, c["SUB"],
                      family=MONO if right else DEFAULT_SANS,
                      anchor="end" if right else "start"))
    out.append(ln(x0, ty + hh + 2, x0 + w, ty + hh + 2, c["STRUCT"], 1))
    for i, row in enumerate(body):
        y = ty + hh + 2 + i * rh
        out.append(ln(x0, y + rh, x0 + w, y + rh, c["STRUCT"], 1))
        for j, cell in enumerate(row):
            right = j > 0 and any(ch.isdigit() for ch in cell)
            out.append(tx(x0 + j * cw + (cw - 12 if right else 12), y + rh - 12, cell, 16,
                          c["INK"], family=MONO if right else DEFAULT_SANS,
                          anchor="end" if right else "start"))
    out.append(rect(x0, ty + hh + 2 + len(body) * rh, w, 2, fill=c["INK"]))
    out += footer(tok, pg.get("scope_note", "") or source_line(pg), pg["index"], c)
    return page_doc(pg, "".join(out), "data")


@recipe("mechanism_flow")
def recipe_mechanism_flow(pg, tok):
    c = _colors(tok)
    nodes = mechanism_nodes(pg)
    assert len(nodes) <= 6, f"节点 {len(nodes)} > 6，交人拆图"
    n = len(nodes)
    if n < 2:
        print(f"[退化] mechanism_flow 节点不足 2 个，退化为 claim 页")
        return page_doc(pg, "", "mechanism")
    ny = 268
    cy = ny + 56
    nh = 34 + n * 32 + 12
    total_w = tok.content_w
    nw = min(320, (total_w - (n - 1) * 24) // n)
    gap = (total_w - n * nw) // max(n - 1, 1)
    out = [_bg(tok, c)]
    out += list(header(tok, "MECHANISM · " + str(pg["index"]).zfill(2),
                       sheet_title(pg), pg.get("assertion", ""),
                       pg.get("so_what", ""), c))
    for i, nd in enumerate(nodes):
        x = tok.margin + i * (nw + gap)
        out.append(rect(x, ny, nw, nh, fill=c["SURF"], rx=6))
        out.append(tx(x + 44, cy + 5, nd["label"], 16, c["INK"], weight="600"))
        cx0 = x + 24
        assert cx0 + 12 < x + 44, "圆徽与文本重叠"
        out.append(f'<circle cx="{cx0}" cy="{cy}" r="12" fill="{c["FOCUS"]}"/>')
        out.append(tx(cx0, cy + 5, str(i + 1), 13, c["FIELD"], anchor="middle", weight="700"))
        out.append(tx(x + 44, cy + 28, nd.get("note", ""), 13, c["SUB"]))
        if i:
            out.append(ln(x - gap + 4, cy, x - 6, cy, c["INK"], 3))
            out.append(f'<path d="M{x - 6} {cy} l-8 -4 v8 z" fill="{c["INK"]}"/>')
    top_bottom = ny + nh
    out.append(ln(tok.margin, top_bottom + 40, tok.canvas_w - tok.margin, top_bottom + 40,
                  c["SUB2"], 1, dash="4 3"))
    out += footer(tok, source_line(pg), pg["index"], c)
    return page_doc(pg, "".join(out), "mechanism")


def meta_line(pg: dict, i: int) -> str:
    keys = ["audience", "date", "duration"]
    if i >= len(keys):
        return ""
    return pg.get(keys[i], "")


@recipe("cover_p1")
def recipe_cover_p1(pg, tok):
    c = _colors(tok)
    lines = split_cover_title(pg.get("assertion", pg.get("title", "")))
    for ln_ in lines:
        assert cjk(ln_) * tok.poster <= tok.canvas_w * 0.66, \
            f"封面行 {ln_!r} 超 0.66 画布宽：再拆行，禁止缩字号"
    out = [_bg(tok, c)]
    out.append(tx(tok.margin, 102, pg.get("scope_note", "")[:40], 13, c["MUTED"],
                  family=MONO, ls=3))
    out.append(ln(tok.margin, 128, tok.canvas_w - tok.margin, 128, c["RULE"], 1))
    y = 330
    for l in lines[:2]:
        out.append(tx(tok.margin, y, l, tok.poster, c["INK"], weight="300", ls=0))
        y += 176
    if len(lines) > 2:
        print(f"[警告] 封面三行以上，交人重断句")
    out.append(rect(tok.margin, 556, 64, 4, fill=c["FOCUS"]))
    out.append(tx(tok.margin, 610, pg.get("so_what") or pg.get("subtitle", ""), 32, c["SUB"]))
    out.append(tx(tok.margin, 648, pg.get("subtitle", ""), 16, c["SUB2"]))
    for i in range(3):
        ml = meta_line(pg, i)
        if ml:
            out.append(tx(tok.canvas_w - tok.margin, 306 + i * 34, ml, 13,
                          c["SUB"], family=MONO, anchor="end"))
    out.append(ln(tok.canvas_w - 300, 274, tok.canvas_w - tok.margin, 274, c["RULE"], 1))
    out.append(ln(tok.canvas_w - 300, 414, tok.canvas_w - tok.margin, 414, c["RULE"], 1))
    out.append(tx(tok.margin, 676, pg.get("audience", ""), 13, c["MUTED"]))
    out.append(tx(tok.margin, 702, pg.get("date", ""), 13, c["MUTED"], family=MONO))
    assert 556 + 4 <= tok.canvas_h - 46, "强调色块压到页脚"
    return page_doc(pg, "".join(out), "cover")


@recipe("assertion_evidence")
def recipe_assertion_evidence(pg, tok):
    c = _colors(tok)
    ev = pg.get("evidence", [])
    y0 = 252
    out = [_bg(tok, c)]
    out += list(header(tok, "CLAIM · " + str(pg["index"]).zfill(2),
                       sheet_title(pg), pg.get("assertion", ""),
                       pg.get("so_what", ""), c))
    for i, e in enumerate(ev):
        txt = e.get("text", "") if isinstance(e, dict) else str(e)
        kind = e.get("kind", "text") if isinstance(e, dict) else "text"
        bar_color = {"number": c["FOCUS"], "image": c["SUB2"]}.get(kind, c["STRUCT"])
        y = y0 + i * 48
        out.append(rect(tok.margin, y, tok.content_w, 40, fill=c["SURF"], rx=4))
        out.append(rect(tok.margin, y, 3, 40, fill=bar_color))
        out.append(tx(tok.margin + 16, y + 28, txt[:60], 20, c["INK"]))
    so_y = y0 + len(ev) * 48 + 16
    if pg.get("so_what"):
        out.append(tx(tok.margin, so_y, pg["so_what"], 24, c["INK"], weight="700"))
    out += footer(tok, source_line(pg), pg["index"], c)
    return page_doc(pg, "".join(out), "claim")


@recipe("teaching_pair")
def recipe_teaching_pair(pg, tok):
    c = _colors(tok)
    ev = pg.get("evidence", [])
    left = ev[0].get("text", "错") if ev else "错"
    right = ev[1].get("text", "对") if len(ev) > 1 else "对"
    col_w = 340
    gap = (tok.content_w - 2 * col_w) // 3
    x1 = tok.margin + gap
    x2 = x1 + col_w + gap
    out = [_bg(tok, c)]
    out += list(header(tok, "TEACHING · " + str(pg["index"]).zfill(2),
                       sheet_title(pg), pg.get("assertion", ""),
                       pg.get("so_what", ""), c))
    for x, label, txt, color in [(x1, "✗ 错", left, c["CAUTION"]),
                                  (x2, "✓ 对", right, c["FOCUS"])]:
        out.append(rect(x, 200, col_w, 230, fill=c["SURF"], rx=6, stroke=color, sw=2))
        out.append(tx(x + 20, 240, label, 20, color, weight="700"))
        out.append(rect(x + 20, 260, col_w - 40, 150, fill=c["FIELD"], rx=4))
        out.append(tx(x + 20, 420, txt[:40], 16, c["INK"]))
    out += footer(tok, source_line(pg), pg["index"], c)
    return page_doc(pg, "".join(out), "teaching")


@recipe("section_anchor")
def recipe_section_anchor(pg, tok):
    # 新几何：无 spike 实测依据，仅靠 qa 门禁 + 人读确认
    c = _colors(tok)
    out = [_bg(tok, c)]
    out.append(tx(tok.margin, 96, pg.get("scope_note", "")[:40], 13, c["MUTED"],
                  family=MONO, ls=3))
    out.append(ln(tok.margin, 116, tok.canvas_w - tok.margin, 116, c["RULE"], 1))
    out.append(tx(tok.margin, 360, pg.get("assertion", pg.get("title", "")),
                  56, c["INK"], weight="600"))
    out.append(rect(tok.margin, 380, 80, 4, fill=c["FOCUS"]))
    out.append(tx(tok.margin, 430, pg.get("so_what", ""), 20, c["SUB"]))
    out += footer(tok, source_line(pg), pg["index"], c)
    return page_doc(pg, "".join(out), "section")


@recipe("action_list")
def recipe_action_list(pg, tok):
    c = _colors(tok)
    ev = pg.get("evidence", [])
    y0 = 252
    out = [_bg(tok, c)]
    out += list(header(tok, "ACTION · " + str(pg["index"]).zfill(2),
                       sheet_title(pg), pg.get("assertion", ""),
                       pg.get("so_what", ""), c))
    for i, e in enumerate(ev[:5]):
        txt = e.get("text", "") if isinstance(e, dict) else str(e)
        y = y0 + i * 56
        cx0 = tok.margin + 24
        out.append(rect(tok.margin, y, tok.content_w, 48, fill=c["SURF"], rx=6))
        out.append(f'<circle cx="{cx0}" cy="{y + 24}" r="12" fill="{c["FOCUS"]}"/>')
        out.append(tx(cx0, y + 29, str(i + 1), 13, c["FIELD"], anchor="middle", weight="700"))
        out.append(tx(tok.margin + 52, y + 32, txt[:50], 24, c["INK"]))
    out += footer(tok, source_line(pg), pg["index"], c)
    return page_doc(pg, "".join(out), "closing")
