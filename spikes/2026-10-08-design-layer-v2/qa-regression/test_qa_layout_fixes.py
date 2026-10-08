#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_layout.py 三处误判修正的自检（不依赖真机渲染，纯合成用例）。
跑法：python3 test_qa_layout_fixes.py [qa_layout.py 路径]
退出码 0 = 全部通过。"""
import io
import os
import sys
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                                    else os.path.join(HERE, "qa_layout.py")))
import qa_layout as Q  # noqa: E402

FAIL = []


def ok(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (("   " + detail) if detail else ""))
    if not cond:
        FAIL.append(name)


def svg(s):
    return ET.fromstring(s)


# ---------------------------------------------------------------- A. 压行
print("[A] check_line_collisions 解析 text-anchor")
# 1) 徽标圆内 middle 数字 + 右侧 start 节点名：x 只差 24，旧版误报；渲染盒不相交 → 新版必须干净
s1 = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" '
      'viewBox="0 0 1280 720" font-size="16">'
      '<text x="132" y="300" text-anchor="middle" font-size="13">1</text>'
      '<text x="156" y="300" font-size="16">需求分析</text>'
      '</svg>')
ok("middle 徽标 + start 节点名不再误报", Q.check_line_collisions(svg(s1)) == [],
   str(Q.check_line_collisions(svg(s1))))

# 2) 真压行：同列同基线，两行 y 只差 6px
s2 = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" '
      'viewBox="0 0 1280 720" font-size="16">'
      '<text x="100" y="300" font-size="16">第一行文字</text>'
      '<text x="100" y="306" font-size="16">第二行文字</text>'
      '</svg>')
ok("真压行仍然抓得到", len(Q.check_line_collisions(svg(s2))) == 1,
   str(Q.check_line_collisions(svg(s2))))

# 3) 旧版漏判的场景：x 属性差 80（>24 被当成不同列），但第一段是 end 锚点、
#    渲染盒是 [356,500]，正好压到第二段 [420,452] 头上
s3 = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" '
      'viewBox="0 0 1280 720" font-size="16">'
      '<text x="500" y="300" text-anchor="end" font-size="16">很长的前段文字内容</text>'
      '<text x="420" y="304" font-size="16">后段</text>'
      '</svg>')
ok("x 差 >24 但渲染盒重叠 → 新版补抓", len(Q.check_line_collisions(svg(s3))) == 1,
   str(Q.check_line_collisions(svg(s3))))

# 4) 正常多行正文（行距 1.6×）不得误报
rows = "".join('<text x="100" y="%d" font-size="20">第 %d 行正文内容</text>' % (300 + i * 32, i)
               for i in range(4))
s4 = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" '
      'viewBox="0 0 1280 720">' + rows + '</svg>')
ok("1.6 倍行距正文不误报", Q.check_line_collisions(svg(s4)) == [],
   str(Q.check_line_collisions(svg(s4))))

# 5) 行内并排（项目符号 + 正文，同基线）：渲染盒估出来重叠 5.4px，
#    但测宽是启发式、几像素误差不该算撞 → 同基线要求 ≥8px
s4b = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" '
       'viewBox="0 0 1280 720" font-size="22">'
       '<text x="80" y="398" font-size="22">•</text>'
       '<text x="86" y="398" font-size="22">正文首字</text>'
       '</svg>')
ok("同基线行内并排不误报", Q.check_line_collisions(svg(s4b)) == [],
   str(Q.check_line_collisions(svg(s4b))))

# 6) 完全相同的坐标，只把第二段挪到另一行（Δbaseline 8px > 0.30×22）
#    → 同一处 5.4px 重叠就成真压行，必须报（证明差异只来自 same-line 判据）
s4c = s4b.replace('x="86" y="398"', 'x="86" y="406"')
ok("跨基线重叠 5px 仍算压行", len(Q.check_line_collisions(svg(s4c))) == 1,
   str(Q.check_line_collisions(svg(s4c))))

# ---------------------------------------------------------------- B. 面板
print("\n[B] panels_of 支持 <path>/<polygon> 裁切")
sb = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">'
      '<defs><clipPath id="cP"><path d="M690 0 H1280 V720 H690 Z"/></clipPath></defs>'
      '<image href="a.png" x="0" y="0" width="1280" height="720" clip-path="url(#cP)"/>'
      '</svg>')
p = Q.panels_of(svg(sb))
ok("<path> 直角裁切被识别为面板", len(p) == 1, str(p))
ok("面板几何 = 690,0,590,720", bool(p) and tuple(int(v) for v in p[0][1:]) == (690, 0, 590, 720),
   str(p[0][1:]) if p else "-")

sp_ = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">'
       '<defs><clipPath id="cQ"><polygon points="100,80 500,80 500,400 100,400"/></clipPath></defs>'
       '<image href="b.png" x="0" y="0" width="1280" height="720" clip-path="url(#cQ)"/>'
       '</svg>')
p2 = Q.panels_of(svg(sp_))
ok("<polygon> 裁切也被识别", len(p2) == 1 and tuple(int(v) for v in p2[0][1:]) == (100, 80, 400, 320),
   str(p2))

sr = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">'
      '<defs><clipPath id="cR"><rect x="40" y="50" width="300" height="200"/></clipPath></defs>'
      '<image href="c.png" x="0" y="0" width="1280" height="720" clip-path="url(#cR)"/>'
      '</svg>')
p3 = Q.panels_of(svg(sr))
ok("<rect> 老写法不回退", len(p3) == 1 and tuple(int(v) for v in p3[0][1:]) == (40, 50, 300, 200),
   str(p3))

# 裁切盒越出 image 矩形时要收敛回可见区
so = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">'
      '<defs><clipPath id="cO"><path d="M0 0 H2000 V2000 H0 Z"/></clipPath></defs>'
      '<image href="d.png" x="0" y="0" width="1280" height="720" clip-path="url(#cO)"/>'
      '</svg>')
p4 = Q.panels_of(svg(so))
ok("裁切盒与 image 求交（不外溢）", len(p4) == 1 and tuple(int(v) for v in p4[0][1:]) == (0, 0, 1280, 720),
   str(p4))

# ---------------------------------------------------------------- C. 对比度
print("\n[C] check_contrast 用 Otsu 定背景/笔画")
W, H = 1280, 720


def render(bg_rgb, ink_boxes, ink_rgb):
    a = np.zeros((H, W, 3), dtype=np.float64)
    a[:, :] = np.array(bg_rgb, dtype=np.float64)
    for (x0, y0, x1, y1) in ink_boxes:
        a[y0:y1, x0:x1] = np.array(ink_rgb, dtype=np.float64)
    return Image.fromarray(a.astype("uint8"), "RGB")


def boxes_of_text(left, baseline, size, n_glyph, stroke_frac):
    """合成"大字号细笔画"：每个字只画几根竖笔，墨量占比 ~stroke_frac。"""
    cell = size
    bw = max(1, int(cell * stroke_frac / 4))
    out = []
    for i in range(n_glyph):
        gx = int(left + i * cell)
        for k in range(4):
            out.append((gx + k * (cell // 4), int(baseline - size * 0.75),
                        gx + k * (cell // 4) + bw, int(baseline)))
    return out


# 用例 1：亮底 #F7F4EC(247,244,236) + 暗字 #1B1A17(27,26,23)，96px 五个字，墨量 ~4%
# 真实对比度 = WCAG(#1B1A17, #F7F4EC) ≈ 15.9:1；旧分位法在这里判 ~1.4:1
ink = boxes_of_text(76, 300, 96, 5, 0.04)
img1 = render((247, 244, 236), ink, (27, 26, 23))
s5 = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" '
      'viewBox="0 0 1280 720" font-size="16">'
      '<text x="76" y="300" font-size="96">不等于设计</text></svg>')
r1 = Q.check_contrast(img1, svg(s5))
ok("大字细笔画不再误判为低对比", bool(r1) and r1[0][0] > 8.0,
   ("测得 %.1f:1" % r1[0][0]) if r1 else "无结果")

# 用例 2：真正不达标的组合必须仍然抓出来 —— #C9BFA6 笔画压在 #EDE6D6 底上
ink2 = boxes_of_text(76, 300, 20, 8, 0.30)
img2 = render((237, 230, 214), ink2, (201, 191, 166))
s6 = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" '
      'viewBox="0 0 1280 720" font-size="16">'
      '<text x="76" y="300" font-size="20">来源与口径说明</text></svg>')
r2 = Q.check_contrast(img2, svg(s6))
ok("真低对比仍然报（不放水）", bool(r2) and r2[0][0] < 4.5,
   ("测得 %.2f:1" % r2[0][0]) if r2 else "无结果")

# 用例 3：暗底亮字（NAVY 页）方向不能反
ink3 = boxes_of_text(76, 300, 20, 8, 0.30)
img3 = render((15, 28, 43), ink3, (230, 237, 245))
r3 = Q.check_contrast(img3, svg(s6))
ok("暗底亮字方向正确", bool(r3) and r3[0][0] > 10.0,
   ("测得 %.1f:1" % r3[0][0]) if r3 else "无结果")

# 用例 4：单色区域（没字）应当跳过而不是崩
img4 = render((247, 244, 236), [], (27, 26, 23))
r4 = Q.check_contrast(img4, svg(s6))
ok("无字的区域跳过而非崩", r4 == [], str(r4))

# ---------------------------------------------------------------- 汇总
print("\n" + "=" * 56)
if FAIL:
    print("自检失败 %d 项: %s" % (len(FAIL), " | ".join(FAIL)))
    sys.exit(1)
print("自检全部通过 ✅")
