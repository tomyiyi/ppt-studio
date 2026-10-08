#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""封面 v2 spike：三套「有视觉主角」的封面。
V1 纯排版（标题即设计，poster 160 档，尺度跳跃 5×）
V2 agnes hero 图单边局部出血 + 左文字区
V3 全幅图单色压平 + 文字落在图内净空区（遮罩只在图字交界渐隐）
规则依据：单一主角占版面 60-65%、标题行高 1.08-1.12、中文标题零字距、
单强调色面积 ≤5%、大字对比 ≥3:1 / 小字 ≥4.5:1。
产出不是留存代码，仅用于审美裁决。"""
import os, sys

W, H = 1280, 720
M = 76                                    # 安全边距 = 画布宽 6%
DEFAULT_SANS = "Noto Sans SC, sans-serif"
SONG = "Songti SC, STSong, serif"          # 衬线大字（印刷感，投幕有糊笔画风险）
HEI = "Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif"   # 黑体（OFL 优先）
# 2026-10-08 换栈（用户裁决「换成可内嵌的 OFL 字体」）：
# 原写 "STHeiti Light" —— 既不在 vendor PPT_SAFE_FONTS 白名单（POSTFLIGHT WARNING
# unsafe_exported_font_faces=1 的唯一来源），也不在 FONT_FALLBACK_WIN 里，导出后
# PowerPoint 拿到的是一个需要自行安装的 face 名。
# 新栈首站 Noto Sans SC（SIL OFL 1.1，黑苹果已装 Real）；导出时 vendor 会把
# Noto Sans SC / PingFang SC 统一映射成 Microsoft YaHei —— 与本项目
# spec_lock.md 第 34 行锁定的 `font_family: Microsoft YaHei, Arial` 契约一致。
MONO = "Menlo, monospace"
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/bkspike/C"
BANDS = (11, 13, 16, 20, 24, 32, 44, 56, 96, 160)   # 160 = 本次提案的 poster 档

PAPER = dict(FIELD="#F7F4EC", SURF="#EDE6D6", INK="#1B1A17", MUTED="#4A4536",
             RULE="#C9BFA6", ACCENT="#C2410C")
NAVY = dict(FIELD="#0F1C2B", SURF="#16283C", INK="#E6EDF5", SUB="#A9C0D8",
            SUB2="#C6D8E8", STRUCT="#4A7BA7", FOCUS="#4FC9E8", CAUTION="#E8A54F")


def lum(hexs):
    h = hexs.lstrip("#")
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def comp(fg, bg, a):
    """fg 以 alpha=a 叠在 bg 上。"""
    return "#%02X%02X%02X" % tuple(
        round(int(fg.lstrip("#")[i:i + 2], 16) * a + int(bg.lstrip("#")[i:i + 2], 16) * (1 - a))
        for i in (0, 2, 4))


def ramp(t, stops):
    """按渐变 offset 插值 alpha；t∈[0,1]。"""
    t = min(1.0, max(0.0, t))
    prev, nxt = stops[0], stops[-1]
    for i in range(len(stops) - 1):
        if stops[i][0] <= t <= stops[i + 1][0]:
            prev, nxt = stops[i], stops[i + 1]
            break
    span = (nxt[0] - prev[0]) or 1.0
    return prev[1] + (t - prev[0]) / span * (nxt[1] - prev[1])


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tx(x, y, s, size=16, fill="#000", fam=None, anchor="start", weight=None, ls=None):
    a = ' font-family="%s"' % fam if (fam and fam != DEFAULT_SANS) else ""
    a += ' font-size="%d" fill="%s"' % (size, fill)
    if weight: a += ' font-weight="%s"' % weight
    if anchor != "start": a += ' text-anchor="%s"' % anchor
    if ls: a += ' letter-spacing="%s"' % ls
    return '<text x="%d" y="%d"%s>%s</text>' % (x, y, a, esc(s))


def cjk(s):                                # 中文行宽估算：CJK 1.0 字宽，ASCII 0.55
    return sum(1.0 if ord(ch) > 0x2E80 else 0.55 for ch in s)


def rect(x, y, w, h, fill=None, stroke=None, sw=1, fill_op=None, rx=0, op=None):
    a = ' x="%d" y="%d" width="%d" height="%d"' % (x, y, w, h)
    if rx: a += ' rx="%d"' % rx
    a += ' fill="%s"' % (fill or "none")
    if fill_op is not None: a += ' fill-opacity="%s"' % fill_op
    if stroke: a += ' stroke="%s" stroke-width="%s"' % (stroke[0], stroke[1] or sw)
    if op is not None: a += ' opacity="%s"' % op
    return '<rect%s/>' % a


def ln(x1, y1, x2, y2, c, w=1, dash=None, op=None):
    a = ' stroke="%s" stroke-width="%s"' % (c, w)
    if dash: a += ' stroke-dasharray="%s"' % dash
    if op is not None: a += ' opacity="%s"' % op
    return '<line x1="%d" y1="%d" x2="%d" y2="%d"%s/>' % (x1, y1, x2, y2, a)


def grad(gid, stops, x1, y1, x2, y2):
    body = "".join('<stop offset="%s" stop-color="%s" stop-opacity="%s"/>' % s for s in stops)
    return ('<linearGradient id="%s" x1="%s" y1="%s" x2="%s" y2="%s">%s</linearGradient>'
            % (gid, x1, y1, x2, y2, body))


def img(href, x, y, w, h, par="none"):
    return ('<image href="%s" x="%d" y="%d" width="%d" height="%d" '
            'preserveAspectRatio="%s"/>' % (href, x, y, w, h, par))


def page(name, body):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" '
            'viewBox="0 0 %d %d" font-family="%s"><title>%s</title>%s</svg>'
            % (W, H, DEFAULT_SANS, esc(name), "".join(body)))


CHECKS = []


def check(tag, fg, bg, size):
    big = size >= 32                        # WCAG：大字 3:1，小字 4.5:1
    need = 3.0 if big else 4.5
    r = ratio(fg, bg)
    CHECKS.append((tag, fg, bg, size, round(r, 2), "≥%.1f" % need, r >= need))
    assert r >= need, "%s 对比度 %.2f < %.1f (%s on %s)" % (tag, r, need, fg, bg)
    assert size in BANDS, size


# ---------------------------------------------------------------- V1 纯排版
def v1():
    c = PAPER
    t1, t2 = "文字进槽", "不等于设计"
    g = [rect(0, 0, W, H, fill=c["FIELD"])]
    g.append(tx(M, 102, "DESIGN LAYER · 2026-10-08", 13, c["INK"], MONO, ls="3"))
    g.append(tx(W - M, 102, "方案一 / 纯排版", 13, c["MUTED"], anchor="end"))
    g.append(ln(M, 128, W - M, 128, c["RULE"], 1))
    # 主角：poster 160，行高 1.10，中文零字距，越大越细（黑体细字，投幕安全）
    g.append(tx(M, 330, t1, 160, c["INK"], HEI, weight="300"))
    g.append(tx(M, 330 + 176, t2, 160, c["INK"], HEI, weight="300"))
    g.append(rect(M, 556, 64, 4, fill=c["ACCENT"]))            # 唯一强调色，面积 0.03%
    g.append(tx(M, 610, "每页要有主张、有证据、有视觉主角", 32, c["INK"]))
    g.append(tx(M, 648, "封面不是一张氛围图压一行小字", 16, c["MUTED"]))
    # 右栏信息锚：压住右半空场，同时给观众目录预期（13px，右对齐）
    for i, s in enumerate(["01  现状 · 三个硬伤", "02  方法 · 契约 + 尺度 + 证据", "03  结果 · 可编辑 pptx"]):
        g.append(tx(W - M, 306 + i * 34, s, 13, c["MUTED"], anchor="end"))
    g.append(ln(W - 380, 274, W - M, 274, c["RULE"], 1))
    g.append(ln(W - 380, 414, W - M, 414, c["RULE"], 1))
    g.append(ln(M, 676, W - M, 676, c["RULE"], 1))
    g.append(tx(M, 702, "ppt-master · editorial 尺度系统 · spike 样张", 13, c["MUTED"]))
    g.append(tx(W - M, 702, "01 / 03", 13, c["MUTED"], MONO, anchor="end"))
    for s, w in ((t1, 4), (t2, 5)):
        assert cjk(s) * 160 <= W * 0.66, "%s 占宽 %.0f%%" % (s, cjk(s) * 160 / W * 100)
    check("V1 主标题", c["INK"], c["FIELD"], 160)
    check("V1 主张行", c["INK"], c["FIELD"], 32)
    check("V1 说明", c["MUTED"], c["FIELD"], 16)
    check("V1 页脚", c["MUTED"], c["FIELD"], 13)
    return page("V1 纯排版封面：标题即设计", g)


# ---------------------------------------------------------------- V2 单边局部出血
def v2():
    c = PAPER
    PW = 690                                       # 文字区 53.9%；可见图区 590×720 = 画布 46%
    # 门禁要求：局部/偏移裁切必须用 path 或 polygon，不能用 rect（rect 只允许整幅预设）
    g = ['<defs><clipPath id="v2-panel"><path d="M%d 0 H%d V%d H%d Z"/></clipPath></defs>'
         % (PW, W, H, PW)]
    # 图按 1280×720 满幅铺（保住 16:9 比例不拉伸），再用 clipPath 只露右半
    g.append(img("../images/hero_blueprint.png", 0, 0, W, H)
             .replace("/>", ' clip-path="url(#v2-panel)"/>'))
    g.append(rect(0, 0, PW, H, fill=c["FIELD"]))
    g.append(ln(PW, 0, PW, H, c["RULE"], 1))
    t1, t2 = "文字进槽", "不等于设计"
    g.append(tx(M, 132, "PPT STUDIO · 设计层", 13, c["INK"], ls="3"))
    g.append(tx(M, 268, t1, 96, c["INK"], SONG, weight="300"))
    g.append(tx(M, 268 + 106, t2, 96, c["INK"], SONG, weight="300"))
    g.append(rect(M, 424, 64, 4, fill=c["ACCENT"]))
    for i, s in enumerate(["每页要有主张、有证据、", "有视觉主角；底图只承担信息，", "不做氛围糊图"]):
        g.append(tx(M, 476 + i * 34, s, 20, c["INK"]))
        assert cjk(s) * 20 <= PW - 2 * M, s
    g.append(ln(M, H - 76, PW - M, H - 76, c["RULE"], 1))
    g.append(tx(M, 596, "汇报  PPT STUDIO 设计层", 13, c["MUTED"]))
    g.append(tx(M, 620, "2026-10-08 · spike v2", 13, c["MUTED"], MONO))
    g.append(tx(M, H - 46, "方案二 / 局部出血", 13, c["MUTED"]))
    g.append(tx(PW - M, H - 46, "02 / 03", 13, c["MUTED"], MONO, anchor="end"))
    check("V2 主标题", c["INK"], c["FIELD"], 96)
    check("V2 主张行", c["INK"], c["FIELD"], 20)
    check("V2 页脚", c["MUTED"], c["FIELD"], 13)
    return page("V2 封面：hero 图单边局部出血 + 左文字区", g)


# ---------------------------------------------------------------- V3 全幅压平 + 净空区
FLAT_A = 0.34                                      # 单色压平，只统一调性
SCRIM_STOPS = [(0.0, 0.86), (0.42, 0.58), (0.68, 0.16), (1.0, 0.0)]


def v3_bg(x_from, x_to):
    """文字落在图上时，取该文字块右端（遮罩最薄处）算最坏底色；底图像素保守取纯白。"""
    a = ramp(x_to / float(W), SCRIM_STOPS)
    return comp("#0B1622", comp(NAVY["FIELD"], "#FFFFFF", FLAT_A), a)


def v3():
    c = NAVY
    g = [img("../images/hero_duotone2.png", 0, 0, W, H)]
    g.append(rect(0, 0, W, H, fill=c["FIELD"], fill_op=str(FLAT_A)))
    g.append('<defs>%s</defs>' % grad(
        "v3-scrim", [(str(o), "#0B1622", str(a)) for o, a in SCRIM_STOPS], "0", "0", "1", "0"))
    g.append(rect(0, 0, W, H, fill="url(#v3-scrim)"))   # 只在图字交界一条渐隐
    t1, t2 = "文字进槽", "不等于设计"
    g.append(tx(M, 150, "PPT STUDIO · 2026 FALL", 11, c["CAUTION"], MONO, ls="4"))
    g.append(tx(M, 330, t1, 96, c["INK"], SONG, weight="300"))
    g.append(tx(M, 436, t2, 96, c["INK"], SONG, weight="300"))
    g.append(rect(M, 472, 64, 4, fill=c["CAUTION"]))
    lead = "每页要有主张、有证据、有视觉主角"
    g.append(tx(M, 526, lead, 32, c["INK"]))
    note = "全幅底图 · 单色压平 · 文字走图内左净空区"
    g.append(tx(M, 566, note, 16, c["SUB"]))
    g.append(ln(M, H - 96, W - M, H - 96, c["STRUCT"], 1, op="0.5"))
    src = "底图 agnes hero_duotone2.png · 遮罩 0.34 压平 + 0.86→0 横向渐隐"
    g.append(tx(M, H - 64, src, 13, c["SUB2"], MONO))
    g.append(tx(W - M, H - 64, "03 / 03", 13, c["SUB"], MONO, anchor="end"))
    for s, col, size in ((t1, c["INK"], 96), (t2, c["INK"], 96),
                         (lead, c["INK"], 32), (note, c["SUB"], 16), (src, c["SUB2"], 13)):
        check("V3 " + s[:6], col, v3_bg(M, M + cjk(s) * size), size)
    return page("V3 封面：全幅图压平 + 图内净空区层级", g)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, svg in (("00_v1_type_only", v1()), ("01_v2_split_bleed", v2()), ("02_v3_duotone", v3())):
        open(os.path.join(OUT, name + ".svg"), "w", encoding="utf-8").write(svg)
        print("wrote %-22s %6d bytes" % (name + ".svg", len(svg)))
    print("对比度自检（大字≥3:1 / 小字≥4.5:1）")
    for tag, fg, bg, size, r, need, ok in CHECKS:
        print("  %-14s %s on %s  size=%-3d  %5.2f  %s" % (tag, fg, bg, size, r, "PASS" if ok else "FAIL"))
