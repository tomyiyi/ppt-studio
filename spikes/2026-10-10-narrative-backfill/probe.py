#!/usr/bin/env python3
"""probe.py — 批 2 闸门探针：历史 18 页反向构造跑 check_narrative。"""
import json, os, sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import check_narrative as CN

PROJ = Path(__file__).resolve().parent.parent.parent / "projects" / "workflow_full"
pages_json = PROJ / "pages.json"
if not pages_json.exists():
    print(f"找不到 {pages_json}"); sys.exit(1)

pages = json.loads(pages_json.read_text(encoding="utf-8"))["pages"]

plan_pages = []
for pg in pages:
    idx = pg.get("index", 0)
    title = pg.get("title", "")
    bullets = pg.get("bullets", [])
    evidence = []
    for j, b in enumerate(bullets):
        evidence.append({"kind": "text", "text": b, "baseline": None,
                         "source": f"README.md#L{j + 1}"})
    plan_pages.append({
        "index": idx, "role": "claim", "assertion": title,
        "evidence": evidence, "so_what": "",
        "visual_protagonist": "", "image_intent": "none", "scope_note": "",
    })

plan = {"pages": plan_pages}
blocking, human_read = CN.check(plan)

wxx_counts = Counter()
for b in blocking:
    for tag in ("[W-01]", "[W-02]", "[W-05]", "[W-06]", "[W-07]", "[W-12]",
                "[W-18]", "[W-19]", "[W-24]", "[W-27]", "[W-28]"):
        if tag in b:
            wxx_counts[tag] += 1

report = Path(__file__).resolve().parent / "probe_report.md"
lines = ["# 探针报告：历史 18 页反向构造跑 check_narrative\n"]
lines.append(f"**页数**: {len(plan_pages)}")
lines.append(f"**blocking 总数**: {len(blocking)}\n")
lines.append("## W-xx 命中分布\n")
lines.append("| 编号 | 命中数 |")
lines.append("|---|---|")
for tag in sorted(wxx_counts):
    lines.append(f"| {tag} | {wxx_counts[tag]} |")
if not wxx_counts:
    lines.append("| (无命中) | 0 |")
lines.append(f"\n**需人读**: {len(human_read)} 条（W-03/W-04/W-09 固定登记）")
lines.append("\n## 结论\n")
if wxx_counts:
    lines.append("门禁接得住历史页——大面积命中是预期的（历史页在旧规则下制作，未遵守新 W-xx）。")
else:
    lines.append("**警告**: 门禁几乎零命中，可能形同虚设，需检查规则覆盖。")
report.write_text("\n".join(lines), encoding="utf-8")
print(f"探针报告写入 {report}")
print(f"blocking {len(blocking)} 条，W-xx 分布: {dict(wxx_counts)}")
