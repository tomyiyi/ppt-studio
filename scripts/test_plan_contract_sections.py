#!/usr/bin/env python3
"""test_plan_contract_sections.py — 5 项（Task 3）+ 3 项（Task 8 追加）。"""
import sys, os, json, tempfile, shutil
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import plan_contract as PC
import spec_tokens as ST

PASS = FAIL = 0
def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {name}   {detail}")
    else:
        FAIL += 1; print(f"  FAIL  {name}   {detail}")

ROOT = Path(__file__).resolve().parent.parent
TMPL = ROOT / "patterns" / "spec_lock.template.md"

print("[A] plan_contract sections + spec_parity")

# (a) 模板与 2 份副本节集合对账缺节为 0
wf = ROOT / "projects" / "workflow_full"
ao = ROOT / "projects" / "agentflow-os-launch"
miss_wf = [e for e in PC.check_spec_parity(wf, TMPL) if e.startswith("[blocking]")]
miss_ao = [e for e in PC.check_spec_parity(ao, TMPL) if e.startswith("[blocking]")]
ok("a. workflow_full 与模板无缺节", len(miss_wf) == 0, f"blocking={miss_wf}")
ok("a'. agentflow-os-launch 与模板无缺节", len(miss_ao) == 0, f"blocking={miss_ao}")

# (b) 故意删一份副本的 ## grid → 出 1 条 blocking
with tempfile.TemporaryDirectory() as td:
    proj = Path(td)
    spec = TMPL.read_text(encoding="utf-8")
    spec_no_grid = "\n".join(l for l in spec.split("\n") if not l.startswith("## grid") and l != "# 版心/栅格真相源。margin 取 L-01（画布宽 6%）；自检 76+12×72+11×24+76==1280" and not l.startswith("- margin:") and not l.startswith("- cols:") and not l.startswith("- col:") and not l.startswith("- gut:") and not l.startswith("- bands:") and not l.startswith("- baseline_step:"))
    # 更简洁的方法：直接去掉 ## grid 到下一个 ## 之间的内容
    lines = spec.split("\n")
    out_lines = []
    skip = False
    for l in lines:
        if l.strip() == "## grid":
            skip = True; continue
        if skip and l.startswith("## "):
            skip = False
        if not skip:
            out_lines.append(l)
    (proj / "spec_lock.md").write_text("\n".join(out_lines), encoding="utf-8")
    errs = [e for e in PC.check_spec_parity(proj, TMPL) if e.startswith("[blocking]")]
    ok("b. 删 ## grid → 1 条 blocking", len(errs) == 1 and "grid" in errs[0], f"errs={errs}")

# (c) 故意多 ## foo → 只出提示不出 blocking
with tempfile.TemporaryDirectory() as td:
    proj = Path(td)
    spec = TMPL.read_text(encoding="utf-8") + "\n## foo\n- bar: 1\n"
    (proj / "spec_lock.md").write_text(spec, encoding="utf-8")
    all_msgs = PC.check_spec_parity(proj, TMPL)
    blocking = [e for e in all_msgs if e.startswith("[blocking]")]
    hints = [e for e in all_msgs if e.startswith("[提示]")]
    ok("c. 多 ## foo → 只提示不 blocking", len(blocking) == 0 and len(hints) >= 1, f"blocking={blocking} hints={hints}")

# (d) REQUIRED_SPEC_SECTIONS 含 ## grid
ok("d. REQUIRED_SPEC_SECTIONS 含 ## grid", "## grid" in PC.REQUIRED_SPEC_SECTIONS, f"sections={PC.REQUIRED_SPEC_SECTIONS}")

# (e) md_to_pptx.py 源码里不再出现 agentflow-os-launch/spec_lock.md 的复制路径
src = (ROOT / "scripts" / "md_to_pptx.py").read_text(encoding="utf-8")
ok("e. md_to_pptx 不再复制工程实例", "agentflow-os-launch/spec_lock" not in src)

# --- Task 8 追加：叙事落点校验 ---
print("\n[B] check_narrative_landing")

# (f) 无 narrative.json → 返回 [] 且打印 [兼容]
with tempfile.TemporaryDirectory() as td:
    proj = Path(td)
    svg_dir = proj / "svg_output"
    svg_dir.mkdir()
    errs = PC.check_narrative_landing(proj, svg_dir)
    ok("f. 无 narrative.json → []", len(errs) == 0, f"errs={errs}")

# (g) narrative 有断言、SVG 里确实含该断言前 8 字 → []
with tempfile.TemporaryDirectory() as td:
    proj = Path(td)
    svg_dir = proj / "svg_output"
    svg_dir.mkdir()
    svg_content = '<svg><text>核心论点需要充分证据支撑才能成立</text></svg>'
    (svg_dir / "01_claim.svg").write_text(svg_content, encoding="utf-8")
    nar = {"pages": [{"index": 1, "role": "claim", "assertion": "核心论点需要充分证据支撑才能成立",
                       "evidence": [], "so_what": ""}]}
    (proj / "narrative.json").write_text(json.dumps(nar, ensure_ascii=False), encoding="utf-8")
    errs = PC.check_narrative_landing(proj, svg_dir)
    ok("g. 断言落入 SVG → []", len(errs) == 0, f"errs={errs}")

# (h) 断言在 SVG 里不存在 → 出 1 条 blocking
with tempfile.TemporaryDirectory() as td:
    proj = Path(td)
    svg_dir = proj / "svg_output"
    svg_dir.mkdir()
    svg_content = '<svg><text>完全不相关的内容</text></svg>'
    (svg_dir / "01_claim.svg").write_text(svg_content, encoding="utf-8")
    nar = {"pages": [{"index": 1, "role": "claim", "assertion": "核心论点需要充分证据支撑才能成立",
                       "evidence": [], "so_what": ""}]}
    (proj / "narrative.json").write_text(json.dumps(nar, ensure_ascii=False), encoding="utf-8")
    errs = PC.check_narrative_landing(proj, svg_dir)
    blocking = [e for e in errs if e.startswith("[blocking]")]
    ok("h. 断言未落入 SVG → blocking", len(blocking) == 1 and "01" in blocking[0],
       f"blocking={blocking}")

print(f"\n{'='*56}")
print(f"通过 {PASS} / 失败 {FAIL}")
sys.exit(1 if FAIL else 0)
