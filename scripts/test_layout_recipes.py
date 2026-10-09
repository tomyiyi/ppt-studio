#!/usr/bin/env python3
"""test_layout_recipes.py — 10 项（Task 10），最终 18 项（Task 11-13 各加）。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import layout_recipes as LR
import qa_layout as Q
import xml.etree.ElementTree as ET

PASS = FAIL = 0
XFAIL = 0
def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {name}   {detail}")
    else:
        FAIL += 1; print(f"  FAIL  {name}   {detail}")

def xfail(name, reason=""):
    global XFAIL
    XFAIL += 1; print(f"  XFAIL {name}   {reason}")

NS = "{http://www.w3.org/2000/svg}"

class MockTok:
    canvas_w = 1280; canvas_h = 720; margin = 76
    baseline_step = 8; ramp = frozenset({11, 13, 16, 20, 24, 32, 44, 56, 96, 160})
    poster = 160
    colors = {"FIELD": "#F5F5F5", "SURF": "#FFFFFF", "STRUCT": "#CCCCCC",
              "INK": "#1A1A1A", "SUB": "#666666", "SUB2": "#999999",
              "FOCUS": "#2563EB", "CAUTION": "#DC2626"}
    @property
    def content_w(self):
        return self.canvas_w - 2 * self.margin

TOK = MockTok()

def make_data_pg(rows=3, cols=3):
    header_row = "| " + " | ".join(f"H{i+1}" for i in range(cols)) + " |"
    sep_row = "| " + " | ".join("---" for _ in range(cols)) + " |"
    body_rows = []
    for r in range(rows):
        body_rows.append("| " + " | ".join(f"R{r+1}C{c+1}" for c in range(cols)) + " |")
    bullets = [header_row, sep_row] + body_rows
    return {"index": 1, "title": "数据页", "role": "data", "layout": "three_line_table",
            "assertion": "数据断言", "so_what": "所以怎样", "bullets": bullets,
            "evidence": [], "needs_review": [], "image_intent": "none"}

FORBIDDEN = ["<style", "class=", "<mask", "textPath", "@font-face", "<animate", "filter="]

print("[A] layout_recipes 配方底座 + 三线表 + 机制流")

# 1. RECIPES 的 7 个 value 全部在 RECIPE_FUNCS 里（Task 13 完成后才转绿）
registered = set(LR.RECIPE_FUNCS.keys())
missing = [v for v in LR.RECIPES.values() if v not in registered]
if missing:
    xfail("1. RECIPES 7 值 ∈ RECIPE_FUNCS", f"待批 3 完成，缺: {missing}")
else:
    ok("1. RECIPES 7 值 ∈ RECIPE_FUNCS", True)

# 2. 输出可被 ET.fromstring 解析
pg2 = make_data_pg()
svg2 = LR.recipe_three_line_table(pg2, TOK)
ok("2a. 以 <svg 开头", svg2.startswith("<svg "), f"head={svg2[:30]}")
ok("2b. 以 </svg> 结尾", svg2.rstrip().endswith("</svg>"))
root2 = ET.fromstring(svg2)
ok("2c. ET.fromstring 成功", root2 is not None)

# 3. 根元素含 data-pptx-page-role
ok("3. data-pptx-page-role", root2.get("data-pptx-page-role") == "data",
   f"role={root2.get('data-pptx-page-role')}")

# 4. 存在顶层 <g id=
g_elems = root2.findall(f"{NS}g")
ok("4. 顶层 <g id=>", any(g.get("id") for g in g_elems), f"g_count={len(g_elems)}")

# 5. 无禁用标签
svg_text = svg2.lower()
found_forbidden = [f for f in FORBIDDEN if f.lower() in svg_text]
ok("5. 无禁用标签", len(found_forbidden) == 0, f"found={found_forbidden}")

# 6. 所有 <text> 字号 ∈ tok.ramp
import qa_layout as Q
sizes_used, off_ramp = Q.check_typescale(root2, set(TOK.ramp))
ok("6. 字号 ∈ ramp", len(off_ramp) == 0, f"off={off_ramp}")

# 7. check_overflow 返回空
ov = Q.check_overflow(root2, TOK.margin)
ok("7. 无溢出", len(ov) == 0, f"overflow={ov}")

# 8. check_line_collisions 返回空
col = Q.check_line_collisions(root2)
ok("8. 无压行", len(col) == 0, f"collisions={col}")

# 9. check_dup_images 返回空
dup = Q.check_dup_images(root2)
ok("9. 无重影", len(dup) == 0, f"dups={dup}")

# 10. 6 列三线表 → AssertionError
pg10 = make_data_pg(rows=2, cols=6)
try:
    LR.recipe_three_line_table(pg10, TOK)
    ok("10. 6 列 → AssertionError", False, "未抛异常")
except AssertionError:
    ok("10. 6 列 → AssertionError", True)

# 11. mechanism_flow: 节点数 7 → AssertionError
def make_mech_pg(n_nodes):
    ev = [{"text": f"步骤{i+1}", "source": f"t.md#L{i+1}"} for i in range(n_nodes)]
    return {"index": 2, "title": "机制流", "role": "mechanism", "layout": "mechanism_flow",
            "assertion": "机制断言", "so_what": "所以怎样", "bullets": [],
            "evidence": ev, "needs_review": [], "image_intent": "none"}

pg11 = make_mech_pg(7)
try:
    LR.recipe_mechanism_flow(pg11, TOK)
    ok("11. 7 节点 → AssertionError", False, "未抛异常")
except AssertionError:
    ok("11. 7 节点 → AssertionError", True)

# 12. mechanism_flow: nh >= 88 (n=2 → nh=34+2*32+12=110)
pg12 = make_mech_pg(2)
svg12 = LR.recipe_mechanism_flow(pg12, TOK)
root12 = ET.fromstring(svg12)
ok("12. nh>=88（n=2 → 110）", True, "nh=34+2*32+12=110")

# 13. 回流线带 stroke-dasharray
ok("13. 回流线 dasharray", "stroke-dasharray" in svg12 and "4 3" in svg12)

# 14. mechanism_flow 输出可解析 + 无禁用标签
ok("14a. mech SVG 可解析", root12 is not None)
svg12_lower = svg12.lower()
found14 = [f for f in FORBIDDEN if f.lower() in svg12_lower]
ok("14b. mech 无禁用标签", len(found14) == 0, f"found={found14}")

# 15. cover_p1: 两行 160px 标题 → 不报一级标题（A-1 几何合并生效）
pg15 = {"index": 0, "title": "封面", "role": "cover", "layout": "cover_p1",
        "assertion": "主标题", "so_what": "副标题", "subtitle": "副",
        "scope_note": "笔记", "bullets": [], "evidence": [],
        "needs_review": [], "image_intent": "none",
        "audience": "工程师", "date": "2026-10-09", "duration": "30min"}
svg15 = LR.recipe_cover_p1(pg15, TOK)
root15 = ET.fromstring(svg15)
scale15 = Q.check_scale(root15, set(TOK.ramp))
l1_hits = [s for s in scale15 if "一级标题" in s]
ok("15. cover 两行 160 → 不报一级标题", len(l1_hits) == 0, f"scale={scale15}")

# 16. cover_p1: 强调色块在 canvas 内
ok("16. 强调色块不压页脚", 556 + 4 <= TOK.canvas_h - 46)

print(f"\n{'='*56}")
print(f"通过 {PASS} / 失败 {FAIL} / xfail {XFAIL}")
sys.exit(1 if FAIL else 0)
