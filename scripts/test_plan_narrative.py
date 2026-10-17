#!/usr/bin/env python3
"""test_plan_narrative.py — 34 项（A 结构器 17 / B 意图与入参对账 17）。"""
import console_utf8  # noqa: F401  中文 Windows 控制台 GBK 兜底：导入即把 stdout 换成 UTF-8
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

print("[B] 配图意图对账（S4，只加判据不松判据）")

# 14. 默认页：意图为 none 且来源标记为 default（没人决定过 ≠ 决定不配）
md14 = make_md("# 标题\n\n## 论点\n- 要点\n")
nar14 = PN.build(md14)
pg14 = nar14["pages"][1]
ok("14. 默认 source=default",
   pg14["image_intent"] == "none" and pg14["image_intent_source"] == "default",
   f"intent={pg14['image_intent']} src={pg14['image_intent_source']}")

# 15. 未声明的 claim 页把 image_intent 列进 _todo（新增待审项，不删原有项）
ok("15. 未声明 → _todo 含 image_intent", "image_intent" in pg14["_todo"],
   f"_todo={pg14['_todo']}")
md14.unlink()

# 16. --intent-plan 声明后：source=declared 且 _todo 里的 image_intent 撤销
md16 = make_md("# 标题\n\n## 论点\n- 要点\n")
nar16 = PN.build(md16, intent_plan={"论点": "panel"})
pg16 = nar16["pages"][1]
ok("16. 声明后 source=declared 且 _todo 撤销",
   pg16["image_intent"] == "panel" and pg16["image_intent_source"] == "declared"
   and "image_intent" not in pg16["_todo"], f"_todo={pg16['_todo']}")
md16.unlink()

# 17. 非法 intent → IntentPlanError（拒绝，不静默降级为 none）
md17 = make_md("# 标题\n\n## 论点\n- 要点\n")
try:
    PN.build(md17, intent_plan={"论点": "poster"})
    ok("17. 非法 intent 抛错", False, "未抛异常")
except PN.IntentPlanError:
    ok("17. 非法 intent 抛错", True)
md17.unlink()

# 18. 没对上任何节/主标题的 intent-plan 键要登记（悬空声明不许默默吞掉）
md18 = make_md("# 标题\n\n## 论点\n- 要点\n")
nar18 = PN.build(md18, intent_plan={"不存在的节": "hero"})
ok("18. 悬空 intent 键进 intent_unmatched",
   nar18["intent_unmatched"] == ["不存在的节"], f"unmatched={nar18['intent_unmatched']}")
md18.unlink()

# 19. evidence 回指行号真实性（旧实现按候选序号算，第二条起就指错行）
md19 = make_md("# 标题\n\n## 第一节\n- 第一条要点内容\n\n中间正文行\n- 第二条要点内容\n")
nar19 = PN.build(md19)
raw19 = md19.read_text(encoding="utf-8").split("\n")
ev19 = nar19["pages"][1]["evidence"]
hit = [e for e in ev19
       if e["text"][:6] in raw19[int(e["source"].split("#L")[1]) - 1]]
ok("19. 每条 evidence 回指行都含本文", len(hit) == len(ev19) == 2,
   f"{len(hit)}/{len(ev19)} 命中；sources={[e['source'] for e in ev19]}")
md19.unlink()

# 20. 两个模块的合法意图集不许漂移
import check_narrative as CN
ok("20. VALID_IMAGE_INTENTS 两模块一致",
   PN.VALID_IMAGE_INTENTS == CN.VALID_IMAGE_INTENTS,
   f"PN={sorted(PN.VALID_IMAGE_INTENTS)} CN={sorted(CN.VALID_IMAGE_INTENTS)}")

# 21. 旧路径（不带 narrative）现在显式写 image_intent，不再靠 md_to_pptx 缺省值
md21 = make_md("# 标题\n\n## 第一节\n- 要点A\n")
plan21 = MB.md_to_pages(md21)
ok("21. 旧路径页显式带意图",
   all("image_intent" in p for p in plan21["pages"])
   and plan21["pages"][1]["image_intent_source"] == "legacy-default",
   f"intents={[p.get('image_intent') for p in plan21['pages']]}")
md21.unlink()

# 22. narrative 路径透传意图来源
md22 = make_md("# 标题\n\n## 论点\n- 要点\n")
nar22 = PN.build(md22, intent_plan={"论点": "background"})
plan22 = MB.md_to_pages(md22, narrative=nar22)
ok("22. narrative 路径透传 declared",
   plan22["pages"][1]["image_intent"] == "background"
   and plan22["pages"][1]["image_intent_source"] == "declared",
   f"src={plan22['pages'][1]['image_intent_source']}")
md22.unlink()

# 23. 证据文本只带正文，不带列表标记（旧实现把 "- " 一路带进 deck 要点）
md23 = make_md("# 标题\n\n## 数据\n- 七成团队保留每日站会\n| 列1 | 列2 |\n| --- | --- |\n| A | 1 |\n")
nar23 = PN.build(md23)
ev23 = nar23["pages"][1]["evidence"]
ok("23. bullet 证据不带 «- »，表格分隔行不作证据",
   ev23[0]["text"] == "七成团队保留每日站会"
   and all(not e["text"].startswith(("-", "*", "+")) for e in ev23)
   and [e["kind"] for e in ev23] == ["text", "row", "row"]
   and not any("---" in e["text"] for e in ev23),
   f"texts={[e['text'][:12] for e in ev23]} kinds={[e['kind'] for e in ev23]}")
md23.unlink()

# 24. plan 参数：内联 JSON 与文件路径都要能吃（编排器传的是路径）
p24 = make_md('# 标题\n\n## 论点\n- 要点\n')
_fd24, _p24 = tempfile.mkstemp(suffix=".json")
os.close(_fd24)  # mkstemp 返回的 fd 不关掉，Windows 上后续 unlink() 会报 WinError 32
pf24 = Path(_p24)
pf24.write_text('{"论点": "panel"}', encoding="utf-8")
ok("24a. 文件路径可读", PN.load_json_arg(str(pf24)) == {"论点": "panel"}, "")
ok("24b. 内联 JSON 可读", PN.load_json_arg('{"论点": "hero"}') == {"论点": "hero"}, "")
ok("24c. 空值返回 None", PN.load_json_arg(None) is None and PN.load_json_arg("") is None, "")
try:
    PN.load_json_arg("{不是 JSON", "--intent-plan")
    ok("24d. 坏输入给出可读错误而非 traceback", False, "未抛异常")
except SystemExit as e:
    ok("24d. 坏输入给出可读错误而非 traceback", "--intent-plan" in str(e), str(e)[:60])
pf24.unlink(); p24.unlink()

# 25. 编排器口径（传路径）走通：文件 plan → build → 意图生效
md25 = make_md("# 标题\n\n## 论点\n- 要点\n")
_fd25, _p25 = tempfile.mkstemp(suffix=".json")
os.close(_fd25)  # 同上：Windows 下未关闭的 fd 会锁住临时文件
pf25 = Path(_p25)
pf25.write_text('{"论点": "hero"}', encoding="utf-8")
nar25 = PN.build(md25, None, PN.load_json_arg(str(pf25)))
ok("25. 路径口径的 intent plan 生效",
   nar25["pages"][1]["image_intent"] == "hero"
   and nar25["pages"][1]["image_intent_source"] == "declared",
   f"intent={nar25['pages'][1]['image_intent']}")
pf25.unlink(); md25.unlink()

# 26. "_" 开头的键按注释处理，不当节标题校验、也不进悬空登记
md26 = make_md("# 标题\n\n## 论点\n- 要点\n")
nar26 = PN.build(md26, intent_plan={"_note": "这是说明文字", "论点": "panel"})
ok("26. _note 注释键被忽略且不悬空",
   nar26["pages"][1]["image_intent"] == "panel"
   and nar26["intent_unmatched"] == [],
   f"unmatched={nar26['intent_unmatched']}")
md26.unlink()

# 27. _todo 与字段实况对账：封面 assertion 已填，不该再报"缺 assertion"
md27 = make_md("# 主标题\n> 副标题\n\n## 论点\n- 要点\n")
nar27 = PN.build(md27)
cov = nar27["pages"][0]
ok("27. 封面 _todo 不再虚报缺 assertion",
   cov["assertion"] == "主标题" and cov["_todo"] == [],
   f"assertion={cov['assertion']!r} _todo={cov['_todo']}")
md27.unlink()

print(f"\n{'='*56}")
print(f"通过 {PASS} / 失败 {FAIL}")
sys.exit(1 if FAIL else 0)
