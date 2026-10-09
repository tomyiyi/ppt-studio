#!/usr/bin/env python3
"""test_qa_scale_and_contrast.py — 12 项。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import qa_layout as Q
import qa_score as QS
from PIL import Image
import io

PASS = FAIL = 0
def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {name}   {detail}")
    else:
        FAIL += 1; print(f"  FAIL  {name}   {detail}")

def svg(body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">{body}</svg>'

def parse(s):
    import xml.etree.ElementTree as ET
    return ET.fromstring(s)

print("[A] qa_score 权重配平 + WCAG 分档 + 尺度/网格检查")

# 1. WEIGHTS 和 = 100
ok("1. sum(WEIGHTS) == 100", sum(QS.WEIGHTS.values()) == 100, f"sum={sum(QS.WEIGHTS.values())}")

# 2. wcag_need 正文 4.5
ok("2. wcag_need(16, 400, '正文') == 4.5", Q.wcag_need(16, 400, "正文") == 4.5)

# 3. wcag_need 大字 3.0
ok("3. wcag_need(44, 600, '断言') == 3.0", Q.wcag_need(44, 600, "断言标题") == 3.0)

# 4. wcag_need 24px bold vs normal
ok("4a. wcag_need(24, 700, '强调') == 3.0", Q.wcag_need(24, 700, "强调") == 3.0)
ok("4b. wcag_need(24, 400, '强调') == 4.5", Q.wcag_need(24, 400, "强调") == 4.5)

# 5. wcag_need 单字符装饰 3.0
ok("5. wcag_need(13, 400, '✓') == 3.0", Q.wcag_need(13, 400, "✓") == 3.0)

# 6. check_scale 合规：44→20→16
s6 = svg('<text x="100" y="100" font-size="44">A</text>'
         '<text x="100" y="200" font-size="20">B</text>'
         '<text x="100" y="300" font-size="16">C</text>')
r6 = Q.check_scale(parse(s6), {16, 20, 44})
ok("6. 44→20→16 合规", len(r6) == 0, f"bad={r6}")

# 7. check_scale 违规：44→32→24
s7 = svg('<text x="100" y="100" font-size="44">A</text>'
         '<text x="100" y="200" font-size="32">B</text>'
         '<text x="100" y="300" font-size="24">C</text>')
r7 = Q.check_scale(parse(s7), {24, 32, 44})
ok("7. 44→32→24 违规", len(r7) > 0 and "未跨 2 档" in r7[0], f"bad={r7}")

# 8. check_scale 两个 44px 同屏
s8 = svg('<text x="100" y="100" font-size="44">A</text>'
         '<text x="100" y="200" font-size="44">B</text>')
r8 = Q.check_scale(parse(s8), {44})
ok("8. 两个 44px → 一级标题", any("一级标题" in x for x in r8), f"bad={r8}")

# 9. check_scale 字号越出 ramp 不双报
s9 = svg('<text x="100" y="100" font-size="44">A</text>'
         '<text x="100" y="200" font-size="17">B</text>')  # 17 不在 ramp
r9 = Q.check_scale(parse(s9), {16, 44})
ok("9. 17px 越出 ramp 不双报", len(r9) == 0, f"bad={r9}")

# 10. check_grid_step
s10 = svg('<text x="100" y="168" font-size="16">A</text>'
          '<text x="100" y="171" font-size="16">B</text>')
r10 = Q.check_grid_step(parse(s10), step=8, tol=1)
ok("10. y=168 不报、y=171 报", len(r10) == 1 and "171" in r10[0], f"bad={r10}")

# 11. check_contrast 返回 4 元组（需实际绘制文字像素，Otsu 才能取样）
from PIL import ImageDraw, ImageFont
img11 = Image.new("RGB", (600, 200), (255, 255, 255))
d11 = ImageDraw.Draw(img11)
try:
    _fnt = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 32)
except Exception:
    _fnt = ImageFont.load_default()
d11.text((50, 90), "正文测试文字足够宽", fill=(0, 0, 0), font=_fnt)
s11 = svg('<text x="50" y="120" font-size="32" fill="#000000">正文测试文字足够宽</text>')
rows11 = Q.check_contrast(img11, parse(s11))
if rows11:
    r = rows11[0]
    ok("11a. check_contrast 返回 4 元组", len(r) == 4, f"len={len(r)}")
    ok("11b. r[0] 是 ratio", isinstance(r[0], (int, float)))
    ok("11c. r[1] 是文本", isinstance(r[1], str))
else:
    ok("11. check_contrast 返回 4 元组", False, "无可测文本")

# 12. 暗底亮字大标题在 3:1~4.5:1 之间 → 旧口径 fail、新口径 pass
img12 = Image.new("RGB", (600, 200), (25, 25, 25))
d12 = ImageDraw.Draw(img12)
try:
    _fnt2 = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 44)
except Exception:
    _fnt2 = ImageFont.load_default()
d12.text((50, 76), "大标题测试文字足够宽", fill=(130, 130, 130), font=_fnt2)
s12 = svg('<text x="50" y="120" font-size="44" fill="#828282">大标题测试文字足够宽</text>')
rows12 = Q.check_contrast(img12, parse(s12))
if rows12:
    r = rows12[0]
    ratio, need = r[0], r[3] if len(r) > 3 else Q.WCAG_MIN
    old_fail = ratio < Q.WCAG_MIN  # 4.5
    new_pass = ratio >= need  # 3.0 for large text
    ok("12. 大字 3:1 分档生效", old_fail and new_pass,
       f"ratio={ratio:.2f} need={need} old_fail={old_fail} new_pass={new_pass}")
else:
    ok("12. 大字 3:1 分档生效", False, "无可测文本")

print(f"\n{'='*56}")
print(f"通过 {PASS} / 失败 {FAIL}")
sys.exit(1 if FAIL else 0)
