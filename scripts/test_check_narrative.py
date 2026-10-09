#!/usr/bin/env python3
"""test_check_narrative.py — 17 项。"""
import json, os, sys, tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import check_narrative as CN

PASS = FAIL = 0
def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {name}   {detail}")
    else:
        FAIL += 1; print(f"  FAIL  {name}   {detail}")

def plan_with(**overrides):
    pg = {"index": 1, "role": "claim", "assertion": "核心论点需要证据支撑",
          "evidence": [{"kind": "text", "text": "改写的证据内容",
                        "baseline": None, "source": ""}],
          "so_what": "因此需要行动", "visual_protagonist": "对比柱",
          "image_intent": "panel", "scope_note": "备注"}
    pg.update(overrides)
    return {"pages": [pg]}

print("[A] check_narrative 写作门禁")

# W-01: 名词短语标题
b, _ = CN.check(plan_with(assertion="项目背景"))
ok("W-01 名词标题", any("[W-01]" in x for x in b))

# W-02: 双论点
b, _ = CN.check(plan_with(assertion="方案A以及方案B对比"))
ok("W-02 双论点", any("[W-02]" in x for x in b))

# W-05: fluff 词
b, _ = CN.check(plan_with(assertion="打造赋能闭环新打法"))
ok("W-05 fluff", any("[W-05]" in x for x in b))

# W-06: 标题过长
b, _ = CN.check(plan_with(assertion="这是一个非常非常长的标题超过了四十字限制验证检查是否生效的测试用例需要更多文字才行"))
ok("W-06 过长", any("[W-06]" in x for x in b))

# W-06: 标题过短
b, _ = CN.check(plan_with(assertion="短"))
ok("W-06 过短", any("[W-06]" in x for x in b))

# W-07: 缺 evidence
b, _ = CN.check(plan_with(evidence=[]))
ok("W-07 缺 evidence", any("[W-07]" in x for x in b))

# W-12: 数字证据缺 baseline
b, _ = CN.check(plan_with(evidence=[{"kind": "number", "text": "100人", "baseline": None, "source": "a.md#L1"}]))
ok("W-12 数字缺 baseline", any("[W-12]" in x for x in b))

# W-18: 照抄率
src = "这是原始文本内容用于检测照抄率是否超过阈值百分之四十的限制"
b, _ = CN.check(plan_with(evidence=[{"kind": "text", "text": src, "baseline": None, "source": ""}]),
                src_text=src)
ok("W-18 照抄率", any("[W-18]" in x for x in b))

# W-19: 缺 source
b, _ = CN.check(plan_with(evidence=[{"kind": "text", "text": "内容", "baseline": None, "source": ""}]))
ok("W-19 缺 source", any("[W-19]" in x for x in b))

# W-24: 缺 so_what
b, _ = CN.check(plan_with(so_what=""))
ok("W-24 缺 so_what", any("[W-24]" in x for x in b))

# W-24: 含糊词
b, _ = CN.check(plan_with(so_what="可能需要适当调整"))
ok("W-24 含糊词", any("[W-24]" in x for x in b))

# W-27: 有 image_intent 但缺 visual_protagonist
b, _ = CN.check(plan_with(visual_protagonist="", image_intent="hero"))
ok("W-27 缺 visual_protagonist", any("[W-27]" in x for x in b))

# W-28: 非法 image_intent
b, _ = CN.check(plan_with(image_intent="invalid"))
ok("W-28 非法 image_intent", any("[W-28]" in x for x in b))

# W-29: 缺 scope_note（warn）
_, h = CN.check(plan_with(scope_note=""))
ok("W-29 缺 scope_note", any("[W-29]" in x for x in h))

# 13. 全合规 → blocking 为空
tmpf13 = tempfile.NamedTemporaryFile(suffix=".md", delete=False, dir=".", mode="w", encoding="utf-8")
tmpf13.write("# 标题\n第三行内容\n"); tmpf13.close()
fname13 = os.path.basename(tmpf13.name)
good = plan_with(
    assertion="核心论点需要充分证据支撑才能成立",
    evidence=[{"kind": "text", "text": "改写的证据内容完全不同", "baseline": None,
               "source": f"{fname13}#L2"}],
    so_what="因此需要立即行动", visual_protagonist="对比柱",
    image_intent="panel", scope_note="备注")
b, _ = CN.check(good, base_dir=Path("."))
ok("13. 全合规 blocking 空", len(b) == 0, f"blocking={b}")
os.unlink(tmpf13.name)

# 14. resolve_source
tmpf = tempfile.NamedTemporaryFile(suffix=".md", delete=False, dir=".")
tmpf.write(b"line1\nline2\nline3\n"); tmpf.close()
fname = os.path.basename(tmpf.name)
r = CN.resolve_source(f"{fname}#L3", Path("."))
ok("14a. resolve_source 命中", r is not None and r[1] == 3)
ok("14b. resolve_source 坏格式", CN.resolve_source(f"{fname}#X3", Path(".")) is None)
ok("14c. resolve_source 缺文件", CN.resolve_source("missing.md#L3", Path(".")) is None)
os.unlink(tmpf.name)

# 15. copy_ratio
ok("15a. 完全照抄 1.0", CN.copy_ratio("abcdefgh", "abcdefgh") == 1.0)
ok("15b. 全改写 < 0.2", CN.copy_ratio("你好世界测试", "完全不同的内容") < 0.2)

# 16. human_read 含 W-03/W-04/W-09
_, h = CN.check(plan_with())
ok("16. 已知盲区登记", all(any(f"[W-{n}]" in x for x in h) for n in ("03", "04", "09")))

# 17. 消息全带 [W- 前缀
b, h = CN.check(plan_with(assertion="项目背景", so_what="", evidence=[], image_intent="bad"))
all_msgs = b + h
ok("17. 全带 [W- 前缀", all("[W-" in m for m in all_msgs), f"msgs={len(all_msgs)}")

print(f"\n{'='*56}")
print(f"通过 {PASS} / 失败 {FAIL}")
sys.exit(1 if FAIL else 0)
