#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内容页 v2 spike：把调研出的量化规则落成两页，与 v1 的 A_10_table / A_08_bullets 同内容对照。
用到的规则（编号见 skill 草案）：
  G1 12 栏栅格：margin 76 / col 72 / gutter 24，坐标全部落 8px 步进
  G2 尺度跳跃 ≥2.5×：页标 44 vs 正文 16 = 2.75×；一屏只有一个 L1
  G3 三线表：0 竖线 / 0 外框 / 0 斑马纹；顶底线 2px、栏目线 1px；行高 40
  G4 数字右对齐 + 等宽（Menlo）；单位进表头；强调 ≤2 处且只用一种手段
  G5 断言式标题：完整判断句 ≤24 字，禁名词短语
  G6 机制页：主链 3px / 普通 1.5px / 辅助 1px 虚线；节点 ≤6；圆徽 24px/13px
  G7 留白率 ≥40%（脚本按墨量盒估算并打印）
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_covers import (W, H, M, SONG, HEI, MONO, NAVY, PAPER, tx, ln, rect, img, page,
                        cjk, esc, lum, ratio, comp, check, CHECKS, BANDS)

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/bkspike/projD/svg_output"
c = NAVY
COL, GUT = 72, 24                                   # 12 栏：76 + 12*72 + 11*24 + 76 = 1280
X0 = M
assert X0 + 12 * COL + 11 * GUT + M == W, "栅格不闭合"


def colx(i):                                        # 第 i 栏左边界（0 起）
    return X0 + i * (COL + GUT)


def colw(n, i=0):                                   # 跨 n 栏的宽
    return n * COL + (n - 1) * GUT


def header(kicker, sheet, title, sowhat):
    g = [rect(0, 0, W, H, fill=c["FIELD"])]
    g.append(tx(X0, 96, kicker, 13, c["SUB"], MONO, ls="3"))
    g.append(tx(W - M, 96, sheet, 13, c["FOCUS"], MONO, anchor="end", ls="2"))
    g.append(ln(X0, 116, W - M, 116, c["STRUCT"], 1, op="0.5"))
    g.append(tx(X0, 168, title, 44, c["INK"], HEI, weight="600"))
    g.append(tx(X0, 204, sowhat, 20, c["SUB"]))
    check("页头 kicker", c["SUB"], c["FIELD"], 13)
    check("页头 页标", c["FOCUS"], c["FIELD"], 13)
    check("页头 主张", c["INK"], c["FIELD"], 44)
    check("页头 说明", c["SUB"], c["FIELD"], 20)
    assert cjk(title) * 44 <= W - 2 * M, "页标越出版心"
    assert cjk(sowhat) * 20 <= W - 2 * M, "说明行越出版心"
    return g


def footer(g, src, page_no):
    g.append(ln(X0, H - 76, W - M, H - 76, c["STRUCT"], 1, op="0.5"))
    g.append(tx(X0, H - 46, src, 13, c["SUB"]))
    g.append(tx(W - M, H - 46, page_no, 13, c["SUB"], MONO, anchor="end"))
    check("页脚 来源", c["SUB"], c["FIELD"], 13)
    assert cjk(src) * 13 <= (W - 2 * M) * 0.72, "来源行过长"


def whitespace_ratio(boxes):
    """墨量盒面积 / 版心面积，用于打印留白率（越高越空）。"""
    area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in boxes)
    return 100.0 * (1 - area / float((W - 2 * M) * (H - 2 * M)))


# ---------------------------------------------------------------- 10 数据表页
ROWS = [
    ("字号", "所有文本字号落在锁定档位内", "9 档 + poster", ""),
    ("底图", "最大 image 面积 / 画布面积", "≥ 90%", ""),
    ("重影", "同一源图不在一页出现两次", "href 去重 1 次", ""),
    ("溢出", "文本不越出画布安全区", "边界 0 px", ""),
    ("压行", "相邻文本行盒不相交", "交集 0 px", ""),
    ("面板", "面板区域墨量", "≥ 6%", ""),
    ("对比", "WCAG 文本对比度", "≥ 4.5 : 1", "warn"),
    ("标题", "每页根节点带 <title>", "18 → 0 条", "hit"),
]


def table_page():
    title = "九档字号收紧后，同一角色不再忽大忽小"
    assert len(title) <= 24
    g = header("WORKFLOW_FULL / QA GATES", "v2 / 三线表", title,
               "八项判据全部脚本化，交付前不再靠肉眼判断")
    ty, rh, hh = 252, 40, 32                         # 表顶 y / 行高 / 表头高
    g.append(ln(X0, ty, W - M, ty, c["INK"], 2))     # 顶线 2px
    g.append(ln(X0, ty + hh, W - M, ty + hh, c["STRUCT"], 1))   # 栏目线 1px
    for x, hd, anc in [(X0 + 4, "判据", "start"), (colx(2) + 4, "含义", "start"),
                       (W - M - 4, "阈值 / 实测", "end")]:
        g.append(tx(x, ty + 22, hd, 16, c["FOCUS"], weight="600", anchor=anc))
    y = ty + hh
    for k, (name, mean, val, flag) in enumerate(ROWS):
        y += rh
        if flag == "warn":                           # 强调只用一种手段：底色 10%
            g.append(rect(X0, y - rh + 6, W - 2 * M, rh - 4, fill=c["CAUTION"], fill_op="0.10"))
        g.append(tx(X0 + 4, y - 14, name, 16, c["INK"], weight="600"))
        g.append(tx(colx(2) + 4, y - 14, mean, 16, c["SUB"]))
        g.append(tx(W - M - 4, y - 14, val, 16, c["FOCUS"] if flag == "hit" else c["INK"],
                    MONO, anchor="end"))
        assert cjk(mean) * 16 <= colw(5) - 8, "含义列溢出"
        assert cjk(val) * 16 <= colw(5) - 8, "阈值列溢出"
        if k < len(ROWS) - 1:
            g.append(ln(X0, y, W - M, y, c["STRUCT"], 1, op="0.18"))   # 行间浅线（非斑马纹）
    g.append(ln(X0, y, W - M, y, c["INK"], 2))       # 底线 2px
    assert y + 8 <= H - 76, "表格压到页脚"
    footer(g, "数据来源  workflow_full/spec_lock.md · qa_layout.py 实测（2026-10-08）· 统计口径  全 18 页", "10 / 18")
    for tag, col in (("判据", c["INK"]), ("含义", c["SUB"]), ("阈值", c["FOCUS"])):
        check("T9 " + tag, col, c["FIELD"], 16)
    boxes = [(X0, 80, W - M, 212), (X0, ty, W - M, y)]
    return page("10 数据表页 v2：八项门禁", g), whitespace_ratio(boxes)


# ---------------------------------------------------------------- 08 机制页
GROUPS = [("生成", [("S1", "md_to_pages", "文字 → 页型"), ("S2", "agnes_bridge", "按页意图生图"),
                    ("S3", "template_renderer", "版式落位")]),
          ("门禁", [("S4", "plan_contract", "结构契约"), ("S5", "qa_score", "内容完整"),
                    ("S6", "quality_checker", "SVG 规范")]),
          ("交付", [("S7", "svg_to_pptx", "导出可编辑 pptx")])]


def flow_page():
    title = "三道门禁串行拦截，肉眼判断不参与交付"
    assert len(title) <= 24
    g = header("WORKFLOW_FULL / PIPELINE", "v2 / 主链三级线宽", title, "任一环节不过，就不产出 pptx")
    ny = 268                                         # 节点顶 y；卡高按节点数收，避免空格洞
    gw = colw(4)                                     # 每组 4 栏 = 360
    cy = ny + 56                                     # 主链连线走第一行高度
    heights = []
    for i, (grp, nodes) in enumerate(GROUPS):
        gx = X0 + i * (gw + GUT)
        nh = 34 + len(nodes) * 32 + 12               # 卡高随节点数收缩
        heights.append(nh)
        g.append(rect(gx, ny, gw, nh, stroke=(c["STRUCT"], 1), rx=8))
        g.append(tx(gx + 20, ny - 14, grp, 20, c["FOCUS"], weight="600"))
        for j, (code, name, desc) in enumerate(nodes):
            yy = ny + 34 + j * 32
            g.append(rect(gx + 20, yy - 12, 24, 24, fill=c["SURF"], stroke=(c["STRUCT"], 1), rx=12))
            g.append(tx(gx + 32, yy + 5, code[1], 13, c["FOCUS"], MONO, anchor="middle"))
            g.append(tx(gx + 64, yy + 4, name, 16, c["INK"], MONO))
            assert (gx + 64) - (gx + 32) > 24, "圆徽与节点名 x 间距 ≤24，会触发 qa_layout 压行误判"
            g.append(tx(gx + gw - 20, yy + 4, desc, 13, c["SUB"], anchor="end"))
        if i < len(GROUPS) - 1:                       # 主链 3px + 箭头
            ax = gx + gw
            g.append(ln(ax, cy, ax + GUT, cy, c["FOCUS"], 3))
            g.append('<path d="M%d %d l-10 -5 v10 z" fill="%s"/>' % (ax + GUT, cy, c["FOCUS"]))
        assert ny + 34 + (len(nodes) - 1) * 32 + 12 <= ny + nh, "节点溢出卡片"
    for tag, fg, bg, size in (("组标签", c["FOCUS"], c["FIELD"], 20),
                              ("节点名", c["INK"], c["FIELD"], 16),
                              ("节点序号", c["FOCUS"], c["SURF"], 13),
                              ("节点说明", c["SUB"], c["FIELD"], 13)):
        check(tag, fg, bg, size)
    # 反馈线：门禁不通过回到生成，走下方通道 + 1px 虚线，标签处断线
    fy = ny + max(heights) + 40
    x_out = X0 + gw // 2 + (gw + GUT)                # 门禁组底边中点
    x_in = X0 + gw // 2                              # 生成组底边中点
    g.append('<path d="M%d %d V%d H%d V%d" stroke="%s" stroke-width="1" '
             'stroke-dasharray="4 3" fill="none"/>' % (x_out, ny + heights[1], fy, x_in, ny + heights[0], c["CAUTION"]))
    g.append('<path d="M%d %d l-5 9 h10 z" fill="%s"/>' % (x_in, ny + heights[0] - 9, c["CAUTION"]))
    lbl = "不通过 → 退回上一环节重跑（不进人工兜底）"
    lw = int(cjk(lbl) * 13)
    lx = (x_in + x_out) // 2 - lw // 2
    g.append(rect(lx - 10, fy - 12, lw + 20, 24, fill=c["FIELD"]))
    g.append(tx(lx, fy + 5, lbl, 13, c["CAUTION"]))
    assert lx + lw <= x_out - 12 and lx >= x_in + 12, "反馈标签压到竖线"
    check("反馈标签", c["CAUTION"], c["FIELD"], 13)
    # 关键结论区：24px 断言句 + 3px 主链色条
    ky = fy + 56
    g.append(rect(X0, ky, 3, 44, fill=c["FOCUS"]))
    g.append(tx(X0 + 20, ky + 20, "门禁把「看起来对不对」换成「脚本判没判过」", 24, c["INK"]))
    g.append(tx(X0 + 20, ky + 44, "本轮三套样张门禁同为 errors 0，观感差距仍然巨大 → 门禁合格 ≠ 设计合格", 16, c["SUB"]))
    assert cjk("本轮三套样张门禁同为 errors 0，观感差距仍然巨大 → 门禁合格 ≠ 设计合格") * 16 <= W - M - (X0 + 20)
    check("结论主句", c["INK"], c["FIELD"], 24)
    check("结论副句", c["SUB"], c["FIELD"], 16)
    footer(g, "证据  pages.json 18 页 · spec_lock.md · vendor svg_quality_checker.py（完整版 13,114 文件）", "08 / 18")
    boxes = [(X0, 80, W - M, 212), (X0, ny, W - M, ky + 60)]
    return page("08 机制页 v2：七阶段三道门禁", g), whitespace_ratio(boxes)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, (svg, ws) in (("10_table_v2", table_page()), ("08_flow_v2", flow_page())):
        open(os.path.join(OUT, name + ".svg"), "w", encoding="utf-8").write(svg)
        print("wrote %-14s %6d bytes  留白率 %.1f%%" % (name + ".svg", len(svg), ws))
