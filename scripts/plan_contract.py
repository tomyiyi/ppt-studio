#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Planning 合同前置校验（源自 PPT Agent V4 的 JSON planning 合同模式）

在 SVG 渲染/PPTX 导出之前，先生成机器可读的 plan.json 并校验：
- 每页 SVG 引用的 images/ 资源必须存在
- spec_lock.md 必须存在且含 canvas/colors/typography 三节
- 每页必须有 <title> 或可识别的标题文本

用法：
    python3 scripts/plan_contract.py --project projects/agentflow-os-launch
    python3 scripts/plan_contract.py --project <dir> --emit  # 写出 plan.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HREF_RE = re.compile(r'href="\.\./images/([^"]+)"')
TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)

REQUIRED_SPEC_SECTIONS = ["## canvas", "## colors", "## typography"]


def build_plan(project: Path) -> dict:
    svg_dir = project / "svg_output"
    images_dir = project / "images"
    plan = {"project": project.name, "pages": [], "errors": []}

    spec = project / "spec_lock.md"
    if not spec.exists():
        plan["errors"].append("缺 spec_lock.md")
    else:
        txt = spec.read_text(encoding="utf-8")
        for sec in REQUIRED_SPEC_SECTIONS:
            if sec not in txt:
                plan["errors"].append(f"spec_lock.md 缺章节 {sec}")

    if not svg_dir.is_dir():
        plan["errors"].append("缺 svg_output/ 目录")
        return plan

    for svg in sorted(svg_dir.glob("*.svg")):
        content = svg.read_text(encoding="utf-8")
        hrefs = HREF_RE.findall(content)
        missing = [h for h in hrefs if not (images_dir / h).exists()]
        tm = TITLE_RE.search(content)
        page = {
            "svg": svg.name,
            "title": tm.group(1).strip() if tm else "",
            "images": hrefs,
            "missing_images": missing,
        }
        plan["pages"].append(page)
        for m in missing:
            plan["errors"].append(f"{svg.name} 引用缺失: images/{m}")
        if not page["title"]:
            plan.setdefault("warnings", []).append(f"{svg.name} 缺 <title>（建议补）")
    return plan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Planning 合同前置校验")
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--emit", action="store_true", help="写出 plan.json")
    args = ap.parse_args(argv)

    plan = build_plan(args.project)
    plan["ok"] = not plan["errors"]
    if args.emit:
        out = args.project / "plan.json"
        out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"plan.json -> {out}")

    print(f"页面 {len(plan['pages'])}，错误 {len(plan['errors'])}，警告 {len(plan.get('warnings', []))}")
    for e in plan["errors"]:
        print(f"  [ERR] {e}")
    for w in plan.get("warnings", []):
        print(f"  [WARN] {w}")
    print("PASS" if plan["ok"] else "FAIL")
    return 0 if plan["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
