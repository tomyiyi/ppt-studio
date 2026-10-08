#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性 spike 脚本：用同一份真实内容出 A/B 两套设计层样张（各 3 页）。
A = ppt-master 设计层 · technical-deepdive + blueprint（工程示意图）
B = ppt-master 设计层 · workshop-teaching + sketch-notes（教学工作卡）
C = 现有管线产物（workflow_full），本脚本不生成，只做截图对照。
产出不是留存代码，仅用于审美裁决。"""
import os, sys

W, H = 1280, 720
DEFAULT_SANS = "Noto Sans SC, sans-serif"
BANDS = [11, 13, 16, 20, 24, 32, 44, 56, 96]          # spec_lock 九档，样张不越档
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/bkspike"

def lum(hexs):
    h = hexs.lstrip("#")
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

def ratio(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def tx(x, y, s, size=16, fill="#000", fam=None, anchor="start", weight=None, ls=None):
    # 规范化写法：根节点给唯一 font-family 默认值，文字节点只写真实覆盖
    if fam and fam != DEFAULT_SANS:
        a = ' font-family="%s"' % fam
    else:
        a = ""
    a += ' font-size="%d"' % size
    a += ' fill="%s"' % fill
    if weight: a += ' font-weight="%s"' % weight
    if anchor != "start": a += ' text-anchor="%s"' % anchor
    if ls: a += ' letter-spacing="%s"' % ls
    return '<text x="%d" y="%d"%s>%s</text>' % (x, y, a, esc(s))

def rect(x, y, w, h, fill=None, stroke=None, sw=1, op=None, fill_op=None, rx=0):
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

def wrap(text, size, maxchars):
    """按显示宽度近似折行（CJK 1 字 = size px，ASCII ~0.55 size）"""
    def wdt(s):
        return sum(size if ord(c) > 0x2E80 else size * 0.55 for c in s)
    lines, cur = [], ""
    for ch in text:
        if wdt(cur + ch) > maxchars * size and cur:
            lines.append(cur); cur = ch
        else:
            cur += ch
    if cur: lines.append(cur)
    return lines

def page(title, body):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" '
            'viewBox="0 0 %d %d" font-family="%s"><title>%s</title>%s</svg>'
            % (W, H, DEFAULT_SANS, esc(title), "".join(body)))

# ---------- 质检八项（源：pages.json p10/p11 + 本轮根 title 门禁） ----------
GATES = [
    ("字号", "所有文本字号落在 spec_lock 九档内", "9 档 11/13/16/20/24/32/44/56/96"),
    ("底图", "最大 image 面积 / 画布面积", "≥ 90%"),
    ("重影", "同一源图不在一页出现两次", "href 去重 = 每页 1 次"),
    ("溢出", "文本不超出画布", "按 text-anchor 算边界"),
    ("压行", "相邻文本行不碰撞", "行盒交集 = 0"),
    ("面板", "面板区域墨量", "≥ 6%"),
    ("对比", "WCAG 文本对比度", "≥ 4.5:1（底色取 20 分位）"),
    ("标题", "每页根节点带 title", "<title> 存在（18 条 WARN → 0）"),
]
STAGES = [("S1", "md_to_pages", "文字→页型"), ("S2", "agnes_bridge", "按页意图生图"),
          ("S3", "template_renderer", "版式落位"), ("S4", "plan_contract", "门禁·结构契约"),
          ("S5", "qa_score", "门禁·内容完整"), ("S6", "quality_checker", "门禁·SVG 规范"),
          ("S7", "svg_to_pptx", "导出可编辑 pptx")]
CONSTRAINTS = [
    ("scrim", "方向性渐变，别整幅糊", "0→0.92 / 0.45→0.80 / 0.62→0.30 / 1→0.04"),
    ("panel", "卡片让底图透出", 'fill-opacity="0.66"'),
    ("clip", "clip-path 挂 <image>", "挂外层 <g> → 门禁 blocking"),
]

# ======================= A · blueprint / technical-deepdive =======================
SANS = "Noto Sans SC, sans-serif"
MONO = "Menlo, monospace"
DISP = "Smiley Sans, Noto Sans SC, sans-serif"
A = dict(FIELD="#0F1C2B", SURF="#16283C", INK="#E6EDF5", SUB="#A9C0D8",
         STRUCT="#4A7BA7", FOCUS="#4FC9E8", CAUTION="#E8A54F")

def a_bg(p, sheet, name):
    c = A
    g = [rect(0, 0, W, H, fill=c["FIELD"])]
    for x in range(40, W, 40):                      # 图纸网格（结构线，非装饰）
        g.append(ln(x, 0, x, H, c["STRUCT"], 0.5, op="0.16"))
    for y in range(40, H, 40):
        g.append(ln(0, y, W, y, c["STRUCT"], 0.5, op="0.16"))
    g.append(ln(40, 92, 1240, 92, c["STRUCT"], 1))  # 图纸上框线
    g.append(tx(40, 68, "RUNHUA / PPT PIPELINE", 11, c["SUB"], MONO, ls="3"))
    g.append(tx(1240, 68, sheet, 11, c["FOCUS"], MONO, anchor="end", ls="2"))
    # 图签（drawing-sheet title block）
    g.append(rect(1010, 628, 230, 62, fill=c["SURF"], stroke=(c["STRUCT"], 1)))
    g.append(ln(1010, 649, 1240, 649, c["STRUCT"], 0.8))
    g.append(tx(1022, 644, "TITLE BLOCK", 11, c["SUB"], MONO, ls="2"))
    g.append(tx(1022, 668, name, 13, c["INK"]))
    g.append(tx(1022, 684, "16:9  ·  spike  ·  2026-10-08", 11, c["SUB"], MONO))
    return g

def a1():
    c = A
    g = a_bg(None, "BK-A1", "封面 · 图纸式管线示意")
    g.append(tx(40, 150, "把一篇文章，变成一份可编辑的 PPTX", 56, c["INK"], weight="700"))
    g.append(tx(40, 196, "七阶段管线 · 每阶段一道可机器判定的门禁 · 结论能回查到源", 20, c["SUB"]))
    # 管线示意：7 框横向链
    bw, gap, x0, y0 = 158, 14, 44, 300
    for i, (code, name, job) in enumerate(STAGES):
        x = x0 + i * (bw + gap)
        gate = code in ("S4", "S5", "S6")
        col = c["FOCUS"] if gate else c["STRUCT"]
        g.append(rect(x, y0, bw, 78, fill=c["SURF"], stroke=(col, 1.6 if gate else 1)))
        g.append(tx(x + 12, y0 + 22, code, 11, col, MONO, ls="2"))
        g.append(tx(x + 12, y0 + 44, name, 13, c["INK"], MONO))
        g.append(tx(x + 12, y0 + 66, job, 13, c["SUB"]))
        if i < 6:
            mx = x + bw + gap / 2
            g.append(ln(x + bw, y0 + 39, x + bw + gap, y0 + 39, c["STRUCT"], 1))
            g.append('<path d="M%d %d l6 0 -3 4 z" fill="%s"/>' % (mx, y0 + 37, c["STRUCT"]))
    # 尺寸线：只跨三道门禁 S4–S6
    gx1 = x0 + 3 * (bw + gap)                 # S4 左边
    gx2 = x0 + 5 * (bw + gap) + bw            # S6 右边
    g.append(ln(gx1, y0 + 96, gx1, y0 + 116, c["FOCUS"], 1))
    g.append(ln(gx2, y0 + 96, gx2, y0 + 116, c["FOCUS"], 1))
    g.append(ln(gx1, y0 + 106, gx2, y0 + 106, c["FOCUS"], 1))
    g.append(tx((gx1 + gx2) // 2, y0 + 128, "GATE x3 — 不靠肉眼判断", 13, c["FOCUS"], MONO, anchor="middle"))
    # 引线注释：从批注指向它说的那个阶段（S2 生图）
    s2x = x0 + 1 * (bw + gap) + bw // 2       # S2 水平中心
    g.append('<path d="M150 486 q60 -30 %d -104" fill="none" stroke="%s" stroke-width="1.4"/>'
             % (s2x - 150, c["CAUTION"]))
    g.append('<circle cx="%d" cy="382" r="3" fill="%s"/>' % (s2x, c["CAUTION"]))
    g.append(tx(70, 508, "生图不是装饰：按页意图出底图", 16, c["CAUTION"]))
    g.append(tx(40, 560, "证据  pages.json 18 页 · spec_lock.md · vendor svg_quality_checker.py", 13, c["SUB"], MONO))
    g.append(tx(40, 584, "边界  本页为 spike 样张，只为审美裁决，不进管线", 13, c["SUB"], MONO))
    return page("把一篇文章变成可编辑的 PPTX", g)

def a2():
    c = A
    g = a_bg(None, "BK-A2", "数据页 · 门禁参考卡")
    g.append(tx(40, 150, "八道门禁，每条都能机器判定", 44, c["INK"], weight="700"))
    g.append(tx(40, 182, "任一不过 → 不出片。判据写在锁里，不写在人的经验里。", 16, c["SUB"]))
    x, y = 44, 214
    cw = [110, 470, 340]
    g.append(rect(x, y, sum(cw), 30, fill=c["SURF"], stroke=(c["STRUCT"], 1)))
    for i, hd in enumerate(["代号", "判据", "阈值 / 算法"]):
        g.append(tx(x + sum(cw[:i]) + 12, y + 20, hd, 13, c["FOCUS"], MONO, ls="1"))
    rh = 46
    for r, (k, v, th) in enumerate(GATES):
        yy = y + 30 + r * rh
        g.append(ln(x, yy + rh, x + sum(cw), yy + rh, c["STRUCT"], 0.6, op="0.7"))
        g.append(tx(x + 12, yy + 29, k, 16, c["INK"], weight="700"))
        g.append(tx(x + cw[0] + 12, yy + 29, v, 16, c["SUB"]))
        g.append(tx(x + cw[0] + cw[1] + 12, yy + 29, th, 13, c["FOCUS"], MONO))
    tb = y + 30 + len(GATES) * rh
    for cx in [x + cw[0], x + cw[0] + cw[1]]:
        g.append(ln(cx, y, cx, tb, c["STRUCT"], 0.6, op="0.7"))
    g.append(ln(x, tb, x + sum(cw), tb, c["STRUCT"], 1))
    g.append(tx(x, tb + 26, "来源  workflow_full/spec_lock.md · typography 九档收紧记录（2026-09-23）", 13, c["SUB"], MONO))
    g.append(tx(x, tb + 48, "注意  「对比」一项在亮底上会把 #94A3B8（2.56:1）自动换成 #475569（6.99:1）", 13, c["CAUTION"]))
    return page("八道门禁，每条都能机器判定", g)

def a3():
    c = A
    g = a_bg(None, "BK-A3", "机制页 · 图位与遮罩")
    g.append(tx(40, 148, "一页只用一个图位", 56, c["INK"], weight="700"))
    g.append(tx(40, 180, "铺底 + 面板同图 = 重影；门禁按 href 去重判死。", 20, c["SUB"]))
    # 左：合规示意
    ox, oy, ow, oh = 44, 214, 470, 300
    g.append(rect(ox, oy, ow, oh, fill=c["SURF"], stroke=(c["FOCUS"], 1.4)))
    g.append(tx(ox, oy - 10, "COMPLIANT", 11, c["FOCUS"], MONO, ls="2"))
    g.append(rect(ox + 1, oy + 1, ow - 2, oh - 2, fill=c["STRUCT"], fill_op="0.25"))
    g.append(tx(ox + 16, oy + 26, "<image>  单图位  100% 铺底", 13, c["INK"], MONO))
    g.append(rect(ox + 24, oy + 150, ow - 48, 120, fill=c["FIELD"], fill_op="0.66",
                  stroke=(c["STRUCT"], 1)))
    g.append(tx(ox + 40, oy + 180, "panel  fill-opacity=0.66", 13, c["INK"], MONO))
    g.append(tx(ox + 40, oy + 204, "底图透得出来 → 不是第二块板", 16, c["SUB"]))
    # 右：违规详图
    px, py = 560, 214
    g.append(rect(px, py, 250, 180, fill=c["SURF"], stroke=(c["CAUTION"], 1.4)))
    g.append(rect(px + 20, py + 20, 210, 140, fill=c["STRUCT"], fill_op="0.3"))
    g.append(rect(px + 60, py + 56, 160, 100, fill=c["FIELD"], fill_op="0.6",
                  stroke=(c["CAUTION"], 1)))
    g.append('<path d="M%d %d l30 30 m0 -30 l-30 30" stroke="%s" stroke-width="2"/>' % (px + 130, py + 86, c["CAUTION"]))
    g.append(tx(px, py - 10, "BREACH", 11, c["CAUTION"], MONO, ls="2"))
    g.append(tx(px + 10, py + 200, "同一 href 出现两次 → blocking", 16, c["CAUTION"]))
    # 右：scrim 阶梯（实心台阶代替渐变；共基线，高度=遮罩强度，值标在台阶下方）
    sx, sy = 840, 214
    BY = sy + 150
    g.append(tx(sx, sy - 10, "SCRIM RAMP", 11, c["FOCUS"], MONO, ls="2"))
    for i, (off, a) in enumerate([(0, 0.92), (0.45, 0.80), (0.62, 0.30), (1, 0.04)]):
        h = 30 + int(a * 110)
        g.append(rect(sx + i * 96, BY - h, 84, h, fill=c["INK"], fill_op=str(a)))
        g.append(tx(sx + i * 96 + 4, BY + 20, "%.2f→%.2f" % (off, a), 11, c["SUB"], MONO))
    g.append(ln(sx, BY, sx + 3 * 96 + 84, BY, c["STRUCT"], 1))
    g.append(tx(sx, BY + 46, "文字侧压住 · 空侧几乎不遮", 16, c["SUB"]))
    # 底部三条约束（引线注释式）
    yy = 548
    for k, msg, val in CONSTRAINTS:
        g.append(ln(44, yy - 6, 1006, yy - 6, c["STRUCT"], 0.6, op="0.5"))
        g.append(tx(44, yy + 16, k, 13, c["FOCUS"], MONO, ls="1"))
        g.append(tx(150, yy + 16, msg, 16, c["INK"]))
        g.append(tx(600, yy + 16, val, 13, c["SUB"], MONO))
        yy += 40
    return page("一页只用一个图位", g)

# ======================= B · sketch-notes / workshop-teaching =======================
SANS = "Noto Sans SC, sans-serif"
B_ = dict(FIELD="#F7F4EC", SURF="#EDE6D6", INK="#2B2A26", MUTED="#5F5747",
          RULE="#C9BFA6", NEW="#245C9E", WRONG="#C2410C", MUST="#1B6B45")

def b_bg(sheet, name):
    c = B_
    g = [rect(0, 0, W, H, fill=c["FIELD"])]
    for y in range(96, H - 40, 34):                 # 笔记本行线（轻，不抢正文）
        g.append(ln(40, y, 1240, y, c["RULE"], 0.5, op="0.35"))
    g.append(ln(96, 40, 96, H - 40, c["WRONG"], 1, op="0.22"))   # 页边距红线：批注区
    g.append(tx(40, 66, name, 13, c["MUTED"]))
    g.append(tx(1240, 66, sheet, 11, c["MUTED"], MONO, anchor="end", ls="2"))
    g.append(ln(40, 80, 1240, 80, c["RULE"], 1))
    return g

def b_annot(x, y, s, col, size=13, target=None):
    """页边批注：手写体 + 引线，引线必须落到它说的那个对象上"""
    c = B_
    out = [tx(x, y, s, size, col, "ZCOOL KuaiLe, " + SANS)]
    if target:
        out.append('<path d="M%d %d q%d %d %d %d" fill="none" stroke="%s" '
                   'stroke-width="1.6" stroke-linecap="round"/>'
                   % (x + 4, y + 8, (target[0] - x) // 2, (target[1] - y - 8) // 2 + 14,
                      target[0] - x - 4, target[1] - y - 8, col))
        out.append('<circle cx="%d" cy="%d" r="3" fill="%s"/>' % (target[0], target[1], col))
    return out

def b1():
    c = B_
    g = b_bg("BK-B1", "封面 · 学习目标契约")
    g.append(tx(120, 150, "学完这份材料，你能独立跑通：", 32, c["MUTED"]))
    g.append(tx(120, 214, "Markdown → 可编辑 PPTX", 56, c["INK"], MONO, weight="700"))
    g.append('<path d="M120 232 q420 22 830 4" fill="none" stroke="%s" stroke-width="3" stroke-linecap="round"/>' % c["MUST"])
    g.append(tx(120, 290, "三个可检验的结果（不是「看完觉得会了」）", 20, c["INK"], weight="700"))
    yy = 336
    for k, v in [("出片", "给定一篇 md，跑出能在 PowerPoint 里改字改色的 .pptx"),
                 ("判合格", "知道八道门禁各判什么，能自己复跑并读出 JSON 摘要"),
                 ("查翻车", "图糊 / 图空 / 竖线三类现象，能说出真因和修法")]:
        g.append(tx(120, yy, "□", 24, c["MUST"], MONO))
        g.append(tx(160, yy, k, 20, c["INK"], weight="700"))
        g.append(tx(270, yy, v, 16, c["MUTED"]))
        yy += 46
    g += b_annot(1040, 150, "这一句就是契约", c["MUST"], target=(900, 234))
    # 前置检查卡
    g.append(rect(120, 512, 1060, 150, fill=c["SURF"], rx=6))
    g.append(tx(140, 546, "开始前的三个前提", 20, c["INK"], weight="700"))
    for i, s in enumerate(["机器上有 3TB 工程中心的 ppt-studio（代码只认这一处真相源）",
                           "生图通道可用（缺 key 只报变量名，不打印明文）",
                           "Chrome headless 能截图 —— 看图被拦截时靠 OCR 客观验收"]):
        g.append(tx(140, 578 + i * 26, "· " + s, 16, c["MUTED"]))
    g.append(tx(120, 692, "spike 样张 · 2026-10-08 · 版式来自 ppt-master workshop-teaching + sketch-notes", 13, c["MUTED"], MONO))
    return page("学完你能独立跑通：Markdown → 可编辑 PPTX", g)

def b2():
    c = B_
    g = b_bg("BK-B2", "参考卡 · 出片自检清单")
    g.append(tx(120, 148, "出片前必跑：八项自检", 44, c["INK"], weight="700"))
    g.append(tx(120, 180, "这一页允许密 —— 它是查表用的，不是读用的。", 16, c["MUTED"]))
    x, y = 120, 206
    cw = [120, 430, 330, 100]
    g.append(rect(x, y, sum(cw), 32, fill=c["SURF"], rx=4))
    for i, hd in enumerate(["查什么", "判据", "阈值 / 算法", "性质"]):
        gx = x + sum(cw[:i]) + 12
        g.append(tx(gx, y + 21, hd, 13, c["INK"], weight="700"))
    rh = 44
    kinds = ["必做", "必做", "易错", "必做", "必做", "必做", "易错", "新加"]
    for r, (k, v, th) in enumerate(GATES):
        yy = y + 32 + r * rh
        if r % 2:
            g.append(rect(x, yy, sum(cw), rh, fill=c["FIELD"], fill_op="0.6"))
        g.append(ln(x, yy + rh, x + sum(cw), yy + rh, c["RULE"], 0.8))
        g.append(tx(x + 12, yy + 28, k, 16, c["INK"], weight="700"))
        g.append(tx(x + cw[0] + 12, yy + 28, v, 16, c["MUTED"]))
        g.append(tx(x + cw[0] + cw[1] + 12, yy + 28, th, 13, c["INK"], MONO))
        kd = kinds[r]
        col = {"必做": c["MUST"], "易错": c["WRONG"], "新加": c["NEW"]}[kd]
        glyph = {"必做": "✓", "易错": "!", "新加": "+"}[kd]
        g.append(tx(x + sum(cw[:3]) + 34, yy + 28, glyph + " " + kd, 13, col, weight="700"))
    tb = y + 32 + len(GATES) * rh
    g.append(ln(x, tb, x + sum(cw), tb, c["RULE"], 1))
    for cx in [x + cw[0], x + cw[0] + cw[1], x + sum(cw[:3])]:
        g.append(ln(cx, y, cx, tb, c["RULE"], 0.8))
    g.append(rect(x, tb, 6, tb - y, fill=c["WRONG"]))   # 性质色带：不靠颜色单独承载（列里已有符号）
    g += b_annot(1090, tb + 30, "这两项最容易忘", c["WRONG"], target=(1046, tb - 66))
    g.append(tx(x, tb + 46, "✓ 必做   ! 易错   + 新加（本轮补的根 title 门禁）", 16, c["MUTED"]))
    g.append(tx(x, tb + 70, "版本  workflow_full · 2026-10-08 —— 阈值随版本变，用前先核对 spec_lock.md", 13, c["MUTED"], MONO))
    return page("出片前必跑：八项自检", g)

def b3():
    c = B_
    g = b_bg("BK-B3", "易错对照 · 图位与遮罩")
    g.append(tx(120, 146, "最容易翻车的一步：同一张图铺两遍", 44, c["INK"], weight="700"))
    g.append(tx(120, 176, "错面和对面并排摆 —— 只给正确答案，你会在下一次同样踩。", 16, c["MUTED"]))
    # 错
    bx, by = 120, 200
    g.append(rect(bx, by, 340, 230, fill=c["SURF"], rx=6, stroke=(c["WRONG"], 2)))
    g.append(tx(bx + 16, by + 32, "!  错", 20, c["WRONG"], weight="700"))
    g.append(rect(bx + 20, by + 48, 300, 150, fill=c["RULE"], fill_op="0.55", rx=2))
    g.append(rect(bx + 90, by + 110, 210, 78, fill=c["FIELD"], rx=2, stroke=(c["WRONG"], 1)))
    g.append(tx(bx + 20, by + 216, "铺底 + 面板都用它 → 重影", 16, c["WRONG"]))
    # 对
    ax = 500
    g.append(rect(ax, by, 340, 230, fill=c["SURF"], rx=6, stroke=(c["MUST"], 2)))
    g.append(tx(ax + 16, by + 32, "✓  对", 20, c["MUST"], weight="700"))
    g.append(rect(ax + 20, by + 48, 300, 150, fill=c["RULE"], fill_op="0.55", rx=2))
    g.append(rect(ax + 90, by + 110, 210, 78, fill=c["INK"], fill_op="0.34", rx=2))
    g.append(tx(ax + 20, by + 216, "一页只挂一个图位；卡片透底", 16, c["MUST"]))
    g.append('<path d="M%d %d q40 -18 70 2" fill="none" stroke="%s" stroke-width="2.4" stroke-linecap="round"/>' % (bx + 352, by + 120, c["MUST"]))
    # 右侧 scrim 台阶 + 批注（共基线，高度=强度，数值标在基线下）
    sx = 880
    BY = by + 150
    g.append(tx(sx, by + 24, "遮罩按方向给，别整幅糊", 20, c["INK"], weight="700"))
    for i, (off, a) in enumerate([(0, 0.92), (0.45, 0.80), (0.62, 0.30), (1, 0.04)]):
        h = 26 + int(a * 96)
        g.append(rect(sx + i * 92, BY - h, 82, h, fill=c["INK"], fill_op=str(a)))
        g.append(tx(sx + i * 92 + 4, BY + 20, "%.2f→%.2f" % (off, a), 11, c["MUTED"], MONO))
    g.append(ln(sx, BY, sx + 3 * 92 + 82, BY, c["RULE"], 1))
    g.append(tx(sx, BY + 44, "文字侧 0.92 · 空侧 0.04", 16, c["MUTED"]))
    g += b_annot(sx + 40, by + 236, "这就是「墨量」从哪来", c["NEW"], target=(sx + 41, BY - 60))
    # 底部：三条规则 + 各自性质
    yy = 486
    for (k, msg, val), kind in zip(CONSTRAINTS, ["新加", "必做", "必做"]):
        col = {"必做": c["MUST"], "新加": c["NEW"]}[kind]
        g.append(rect(120, yy - 24, 1060, 46, fill=c["SURF"], rx=4))
        g.append(tx(140, yy + 4, ("✓" if kind == "必做" else "+") + " " + k, 16, col, weight="700"))
        g.append(tx(300, yy + 4, msg, 16, c["INK"]))
        g.append(tx(700, yy + 4, val, 13, c["MUTED"], MONO))
        yy += 56
    g.append(tx(120, 656, "标为简化：这里的数值来自本项目 spec_lock 的实测收紧记录，不是通用标准；换项目要重定。", 13, c["MUTED"]))
    g.append(tx(120, 690, "版本  workflow_full · 2026-10-08", 13, c["MUTED"], MONO))
    return page("最容易翻车的一步：同一张图铺两遍", g)

def main():
    bad = []
    for tag, pal, keys in (("A", A, ["INK", "SUB", "FOCUS", "CAUTION"]),
                           ("B", B_, ["INK", "MUTED", "NEW", "WRONG", "MUST"])):
        field = pal["FIELD"]
        for k in keys:
            r = ratio(pal[k], field)
            if r < 4.5:
                bad.append("%s.%s on FIELD = %.2f:1" % (tag, k, r))
    print("对比自检:", "PASS 全部 ≥ 4.5:1" if not bad else "FAIL " + "; ".join(bad))
    for k, v in A.items():
        if k != "FIELD" and ratio(v, A["FIELD"]) < 4.5:
            print("   A %s 亮度检查 %.2f:1" % (k, ratio(v, A["FIELD"])))
    os.makedirs(OUT + "/A", exist_ok=True)
    os.makedirs(OUT + "/B", exist_ok=True)
    for fn, name in ((a1, "00_cover"), (a2, "10_table"), (a3, "08_bullets")):
        open("%s/A/%s.svg" % (OUT, name), "w").write(fn())
    for fn, name in ((b1, "00_cover"), (b2, "10_table"), (b3, "08_bullets")):
        open("%s/B/%s.svg" % (OUT, name), "w").write(fn())
    print("写出", len(os.listdir(OUT + "/A")) + len(os.listdir(OUT + "/B")), "个 SVG 到", OUT)

main()
