#!/usr/bin/env python3
"""spec_tokens 14 项合成用例。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import spec_tokens as S

PASS = FAIL = 0
def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {name}   {detail}")
    else:
        FAIL += 1; print(f"  FAIL  {name}   {detail}")

MINIMAL = """\
## canvas
- width: 1280
- height: 720

## grid
- margin: 76
- cols: 12
- col: 72
- gut: 24
- bands: 4 8 12 16 24 32 48 64
- baseline_step: 8

## typography
- kicker: 13
- body: 16
- sub: 20
- display: 24
- title: 32
- assertion: 44
- hero: 56
- section: 96
- poster: 160

## colors
- background: "#0D0D0D"
- surface: "#1A1A1A"
- divider: "#333333"
- primary_text: "#F5F5F5"
- secondary_text: "#B0B0B0"
- tertiary_text: "#808080"
- accent: "#FF6B35"
- improvement: "#FFB84D"
"""

print("[A] spec_tokens parse + load")

# 1. 最小合法 spec 不抛
try:
    S.parse(MINIMAL)
    ok("1. 最小合法 spec 不抛", True)
except Exception as e:
    ok("1. 最小合法 spec 不抛", False, str(e))

# 2. 缺 ## grid → TokensError 含 grid
try:
    S.parse(MINIMAL.replace("## grid", "## notgrid"))
    ok("2. 缺 ## grid → TokensError", False, "未抛")
except S.TokensError as e:
    ok("2. 缺 ## grid → TokensError 含 grid", "grid" in str(e), str(e))

# 3. ## grid 缺 gut → TokensError 含 gut
try:
    S.parse(MINIMAL.replace("- gut: 24\n", ""))
    ok("3. 缺 gut → TokensError", False, "未抛")
except S.TokensError as e:
    ok("3. 缺 gut → TokensError 含 gut", "gut" in str(e), str(e))

# 4. ## typography 缺 poster → TokensError 含 poster
try:
    S.parse(MINIMAL.replace("- poster: 160\n", ""))
    ok("4. 缺 poster → TokensError", False, "未抛")
except S.TokensError as e:
    ok("4. 缺 poster → TokensError 含 poster", "poster" in str(e), str(e))

# 5. 栅格不闭合
try:
    S.parse(MINIMAL.replace("- margin: 76", "- margin: 60"))
    ok("5. 栅格不闭合 → TokensError", False, "未抛")
except S.TokensError as e:
    ok("5. 栅格不闭合 → TokensError 含 '栅格不闭合'", "栅格不闭合" in str(e), str(e))

# 6. 色板缺 accent
try:
    S.parse(MINIMAL.replace("- accent:", "- _removed:"))
    ok("6. 缺 accent → TokensError", False, "未抛")
except S.TokensError as e:
    ok("6. 缺 accent → TokensError 含 '色板缺键'", "色板缺键" in str(e), str(e))

t = S.parse(MINIMAL)

# 7
ok("7a. colx(0)==margin", t.colx(0) == 76, f"colx(0)={t.colx(0)}")
ok("7b. colx(1)==margin+col+gut", t.colx(1) == 76 + 72 + 24, f"colx(1)={t.colx(1)}")

# 8
ok("8. colw(12)==content_w", t.colw(12) == t.content_w, f"colw(12)={t.colw(12)} content_w={t.content_w}")

# 9
ok("9. content_w == 1280-2*76 == 1128", t.content_w == 1128, f"content_w={t.content_w}")

# 10. 行内注释容忍
with_comment = MINIMAL.replace("- margin: 76", "- margin: 76          # 取 L-01")
tc = S.parse(with_comment)
ok("10. 行内注释容忍 margin==76", tc.margin == 76, f"margin={tc.margin}")

# 11. canvas 带 px 单位
with_px = MINIMAL.replace("- width: 1280", "- width: 1280px")
tp = S.parse(with_px)
ok("11. canvas 带 px 单位仍能取 1280", tp.canvas_w == 1280, f"canvas_w={tp.canvas_w}")

# 12. bands
ok("12a. bands 是 tuple", isinstance(t.bands, tuple))
ok("12b. bands 含 8", 8 in t.bands, f"bands={t.bands}")

# 13. has_size
ok("13a. has_size(56) 为真", t.has_size(56))
ok("13b. has_size(17) 为假", not t.has_size(17))

# 14. 代码块围栏里的假节不被当节名
fenced = MINIMAL + "\n```\n## 假节\n- fake: 1\n```\n"
names = S.section_names(fenced)
ok("14. 代码块围栏里的假节不被当节名", "假节" not in names, f"sections={names}")

print(f"\n{'='*56}")
print(f"通过 {PASS} / 失败 {FAIL}")
sys.exit(1 if FAIL else 0)
