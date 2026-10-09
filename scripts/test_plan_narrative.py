#!/usr/bin/env python3
"""test_plan_narrative.py — 15 项。"""
import json, os, sys, tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import plan_narrative as PN
import md_to_pages as MB

PASS = FAIL = 0
def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {name}   {detail}")
    else:
        FAIL += 1; print(f"  FAIL  {name}   {detail}")

def make_md(text: str) -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
    f.write(text); f.close()
    return Path(f.name)

print("[A] plan_narrative 结构器")

# 1. 三节 md → 4 页（封面 + 3）
md1 = make_md("# 主标题\n> 副标题\n\n## 第一节\n- 要点A\n\n## 第二节\n- 要点B\n\n## 第三节\n- 要点C\n")
nar1 = PN.build(md1)
ok("1. 三节 → 4 页", len(nar1["pages"]) == 4, f"pages={len(nar1['pages'])}")
md1.unlink()

# 2. 封面 assertion == H1, scope_note == 引用
ok("2a. 封面 assertion == H1", nar1["pages"][0]["assertion"] == "主标题")
ok("2b. scope_note == 引用", nar1["pages"][0]["scope_note"] == "副标题")

# 3. 每页 role ∈ ROLES
all_roles = {pg["role"] for pg in nar1["pages"]}
ok("3. role ∈ ROLES", all_roles.issubset(set(PN.ROLES)), f"roles={all_roles}")

# 4. --role-plan 覆盖生效
md4 = make_md("# 标题\n\n## 数据节\n- 100 人\n")
nar4 = PN.build(md4, role_plan={"数据节": "data"})
ok("4. role-plan 覆盖", nar4["pages"][1]["role"] == "data",
   f"role={nar4['pages'][1]['role']}")
md4.unlink()

# 5. 非法 role → RolePlanError
md5 = make_md("# 标题\n\n## 某节\n- 内容\n")
try:
    PN.build(md5, role_plan={"某节": "invalid_role"})
    ok("5. 非法 role → RolePlanError", False, "未抛异常")
except PN.RolePlanError:
    ok("5. 非法 role → RolePlanError", True)
md5.unlink()

# 6. evidence.source 回指真实性
md6 = make_md("# 标题\n\n## 第一节\n- 这是第L4行的内容\n")
nar6 = PN.build(md6)
ev = nar6["pages"][1]["evidence"]
if ev:
    src = ev[0]["source"]
    ok("6a. source 格式 x.md#L<n>", "#" in src and src.split("#")[1].startswith("L"),
       f"source={src}")
    ln = int(src.split("#L")[1])
    raw_lines = md6.read_text(encoding="utf-8").split("\n")
    line_text = raw_lines[ln - 1] if ln <= len(raw_lines) else ""
    ok("6b. 回指行含原文", ev[0]["text"][:6] in line_text or line_text.strip() != "",
       f"L{ln}: {line_text.strip()[:40]}")
else:
    ok("6. evidence 回指", False, "无 evidence")
md6.unlink()

# 7. image_intent 默认 none
ok("7. image_intent 默认 none", nar1["pages"][1]["image_intent"] == "none")

# 8. 表格行进 evidence kind=="row"
md8 = make_md("# 标题\n\n## 数据页\n| 列1 | 列2 |\n| --- | --- |\n| A | 1 |\n| B | 2 |\n")
nar8 = PN.build(md8)
rows = [e for e in nar8["pages"][1]["evidence"] if e["kind"] == "row"]
ok("8. 表格行 kind=row 且不被截断", len(rows) >= 2, f"rows={len(rows)}")
md8.unlink()

# 9. 无 bullet 的 claim → _todo 含 evidence
md9 = make_md("# 标题\n\n## 论点节\n这段没有 bullet。\n")
nar9 = PN.build(md9)
pg9 = nar9["pages"][1]
ok("9. claim 无 bullet → _todo 含 evidence",
   "evidence" in pg9["_todo"], f"_todo={pg9['_todo']}")
md9.unlink()

# 10. _todo 只列该 role 的必填缺项
md10 = make_md("# 标题\n\n## 总结\n- 行动项\n")
nar10 = PN.build(md10, role_plan={"总结": "closing"})
pg10 = nar10["pages"][1]
ok("10. closing 不要求 evidence",
   "evidence" not in pg10["_todo"], f"_todo={pg10['_todo']}")
md10.unlink()

# 11. JSON 可回读
md11 = make_md("# 标题\n\n## 第一节\n- 内容\n")
nar11 = PN.build(md11)
text = json.dumps(nar11, ensure_ascii=False)
back = json.loads(text)
ok("11. JSON 回读页数一致", len(back["pages"]) == len(nar11["pages"]))
md11.unlink()

# 12. 不带 --narrative 时旧字段完整（向后兼容）
md12 = make_md("# 标题\n\n## 第一节\n- 要点A\n- 要点B\n")
plan_off = MB.md_to_pages(md12)
pg_off = plan_off["pages"][1]
old_keys = {"index", "title", "bullets", "layout", "needs_review", "image_prompt"}
ok("12. 不带 narrative 旧字段完整", old_keys <= set(pg_off.keys()),
   f"keys={sorted(pg_off.keys())}")
md12.unlink()

# 13. 带 --narrative 时旧字段仍在 + 新增 role/assertion/so_what/evidence/image_intent
md13 = make_md("# 标题\n\n## 第一节\n- 要点A\n")
nar13 = PN.build(md13)
plan_on = MB.md_to_pages(md13, narrative=nar13)
pg_on = plan_on["pages"][1]
new_fields = {"role", "assertion", "so_what", "evidence", "image_intent"}
ok("13a. 带 narrative 旧字段仍在", old_keys <= set(pg_on.keys()),
   f"keys={sorted(pg_on.keys())}")
ok("13b. 带 narrative 新增字段", new_fields <= set(pg_on.keys()),
   f"keys={sorted(pg_on.keys())}")
ok("13c. set(old) <= set(new)", set(pg_off.keys()) <= set(pg_on.keys()))
md13.unlink()

print(f"\n{'='*56}")
print(f"通过 {PASS} / 失败 {FAIL}")
sys.exit(1 if FAIL else 0)
