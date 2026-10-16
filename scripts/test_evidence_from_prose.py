#!/usr/bin/env python3
"""test_evidence_from_prose.py — S15-C 散文→evidence 抽取自检。

重点不是"抽到了多少"，而是"抽取没有把门禁喂成哑巴"：
  · 逐字性（不生成、不改写、不截断）
  · 回指正确（行号一定指向原文里真的含这句话的那一行）
  · baseline 只在原文字面含参照值时才填
  · 反向查：纯自指/套话段必须抽不出证据，[W-07] 必须仍然亮
  · 只收紧不放宽：≤3 条上限、非散文行不取
用法：python3 scripts/test_evidence_from_prose.py
退出码：0 = 全过。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import evidence_from_prose as EP      # noqa: E402
import plan_narrative as PN           # noqa: E402
import check_narrative as CN          # noqa: E402

ROOT = Path(HERE).parent
RUN2_ART = ROOT / "spikes/RUN-20261015/e2e/run2/article/article.md"

PASS = FAIL = 0
def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {name}   {detail}")
    else:
        FAIL += 1; print(f"  FAIL  {name}   {detail}")


def extract_from(md_text, heading, md_name="article.md"):
    """用 split_sections 自己的产出喂抽取器 —— 行号口径由存量函数保证，
    测试不手算偏移（上一版手算 off-by-one，把对的实现判成错的）。"""
    for sec in PN.split_sections(md_text):
        if sec["heading"] == heading:
            return EP.extract(sec["lines"], sec["start_line"], md_name,
                              PN.kind_of, PN.strip_md)
    raise AssertionError(f"夹具里没有节「{heading}」")


print("[A] 逐字性与回指")

MD_A = """## 是什么

受访的 42 个远程交付团队平均每周召开 4.5 小时同步会议，其中约三分之一没有形成任何可执行的决议。（example.com、example.org）
"""
ev = extract_from(MD_A, "是什么")
ok("A1 抽到 1 条", len(ev) == 1, f"ev={len(ev)}")
if ev:
    ok("A2 逐字：是原文的连续子串", ev[0]["text"] in MD_A, ev[0]["text"][:24])
    ok("A3 句末引用括号被剥掉且剥后仍逐字",
       "example.com" not in ev[0]["text"] and ev[0]["text"] in MD_A)
    ok("A4 回指行号指向真的含该句的那一行",
       ev[0]["source"] == "article.md#L3" and
       ev[0]["text"] in MD_A.split("\n")[2], ev[0]["source"])
    ok("A5 kind 沿用存量 kind_of（含阿拉伯数字→number）",
       ev[0]["kind"] == PN.kind_of(ev[0]["text"]) == "number", ev[0]["kind"])
    ok("A6 标 provenance", ev[0].get("provenance") == "prose")

# 多段：行号必须各自指对，不能全记到第一段
MD_B = """## 一

第一句证据内容在这里，讲的是甲事，与乙事无关。

## 二

第二句证据内容在这里，讲的是丙事，与丁事无关。
"""
lines_b = MD_B.split("\n")
ev_b = extract_from(MD_B, "二")
ok("B1 跨段各行号独立指对",
   len(ev_b) == 1 and ev_b[0]["source"] == "article.md#L7"
   and ev_b[0]["text"] in lines_b[6], ev_b and ev_b[0]["source"])

print("\n[C] baseline 只认原文字面存在的参照值")

ok("C1 「从 60 分钟改成 25 分钟」→ 填 60 分钟",
   EP.extract_baseline("把每周例会从 60 分钟改成 25 分钟之后，字数上升。") == "60 分钟")
ok("C2 「从 1.8 小时提高到 2.6 小时」→ 填 1.8 小时",
   EP.extract_baseline("连续编码时长中位数从 1.8 小时提高到 2.6 小时。") == "1.8 小时")
ok("C3 「翻倍」不编 baseline",
   EP.extract_baseline("两个月内交付事故数量翻倍，随后恢复周会。") is None)
ok("C4 「增加了约四成」不编 baseline",
   EP.extract_baseline("纪要平均字数增加了约四成。") is None)
ok("C5 「比上周更快」→ 填 上周",
   EP.extract_baseline("平均响应比上周更快一些。") == "上周")

MD_D = """## 数字无参照

受访的 42 个团队平均每周召开 4.5 小时同步会议，没有形成可执行决议的比例约三分之一。
"""
ev_d = extract_from(MD_D, "数字无参照")
ok("C6 无字面参照的数字证据 baseline 仍为 None（宁可让 W-12 判红）",
   len(ev_d) == 1 and ev_d[0]["baseline"] is None and ev_d[0]["kind"] == "number")

print("\n[E] 反向查：抽取没有把门禁喂成哑巴")

MD_META = """## 写在最后

本篇基于 5 条双源验证的结论写成，覆盖 5 个方面。更多未经验证的发现见附录。
"""
ok("E1 纯自指段抽不出任何证据", extract_from(MD_META, "写在最后") == [],
   "W-07 在这一页必须仍然亮")

MD_SHORT = """## 空话

是的。继续。
"""
ok("E2 过碎片段不算证据", extract_from(MD_SHORT, "空话") == [])

MD_LIST = """## 只有列表

- 这条本来就由存量 bullet 路径负责
- 这条也是
"""
ok("E3 列表/标题/引用/表格行不走 prose 路径",
   extract_from(MD_LIST, "只有列表") == [])

ok("E4 ≤3 条上限（只收紧不放宽，与写作 skill 的 evidence_points≤3 同数）",
   len(EP.extract(["第一句证据内容在这里，讲的是甲事，与乙事无关。",
                   "第二句证据内容在这里，讲的是丙事，与丁事无关。",
                   "第三句证据内容在这里，讲的是丁事，与戊事无关。",
                   "第四句证据内容在这里，讲的是戊事，与己事无关。"],
                  1, "article.md", PN.kind_of, PN.strip_md)) == 3)

print("\n[F] 接进 plan_narrative + check_narrative 的端到端（run2 真实夹具）")

if not RUN2_ART.exists():
    ok("F0 run2 夹具在盘", False, str(RUN2_ART))
else:
    tmp = Path(tempfile.mkdtemp(prefix="s15c_"))
    nar = PN.build(RUN2_ART)
    w07 = lambda n: [x for x in CN.check(n, "", RUN2_ART.parent)[0] if "[W-07]" in x]
    # 关掉 prose 抽取，拿同一份夹具做前后对照（只动开关，判据一字未改）
    orig = PN.prose_extract
    PN.prose_extract = lambda *a, **k: []
    before = w07(PN.build(RUN2_ART))
    PN.prose_extract = orig
    after = w07(nar)
    ok("F1 同一夹具：开抽取前 W-07 条数 = 6", len(before) == 6, f"{len(before)} 条")
    ok("F2 开抽取后 W-07 只剩 1 条，且剩的是纯自指的「写在最后」页",
       len(after) == 1 and "页 06" in after[0], after)
    ok("F3 消解的 5 条各自有可回指、逐字可查的证据",
       all(nar["pages"][i]["evidence"] and
           all(e["text"] in RUN2_ART.read_text(encoding="utf-8")
               and CN.resolve_source(e["source"], RUN2_ART.parent)
               for e in nar["pages"][i]["evidence"]) for i in (1, 2, 3, 4, 5)))
    b_all = CN.check(nar, "", RUN2_ART.parent)[0]
    w12 = [x for x in b_all if "[W-12]" in x]
    ok("F4 新增的 blocking 是 W-12（数字证据无字面 baseline），不是被绕开",
       len(w12) == 3, f"{len(w12)} 条")
    ok("F5 W-19 零命中：所有 prose source 都能 resolve_source 解析",
       not [x for x in b_all if "[W-19]" in x])
    ok("F6 W-24（待决项 B，本轮未批）条数未变",
       len([x for x in b_all if "[W-24]" in x]) == 8)
    ok("F7 判据常量零改动",
       CN.COPY_MAX == 0.40 and CN.REQUIRED["claim"] ==
       ["assertion", "evidence", "so_what", "visual_protagonist", "image_intent"])
    # 落盘一次，供报告与人工复核
    (tmp / "narrative.json").write_text(json.dumps(nar, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    print(f"  （narrative 样本留在 {tmp}/narrative.json）")

print("\n[G] 确定性")
r1 = json.dumps(extract_from(RUN2_ART.read_text(encoding="utf-8"), "是什么"),
                ensure_ascii=False, sort_keys=True)
r2 = json.dumps(extract_from(RUN2_ART.read_text(encoding="utf-8"), "是什么"),
                ensure_ascii=False, sort_keys=True)
ok("G1 同输入两次输出逐字节一致", r1 == r2 and r1 != "[]", f"{len(r1)} 字符")

print(f"\n通过 {PASS} / 失败 {FAIL}")
sys.exit(1 if FAIL else 0)
