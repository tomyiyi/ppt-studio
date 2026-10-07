#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键：Markdown 文章 -> PPTX（内容驱动生成的完整闭环）

链路：
  md_to_pages.py（切页） -> pages_to_svg.py（渲染）
  -> plan_contract.py（合同校验） -> qa_score.py（打分质检）
  -> svg_quality_checker.py（vendor 门禁） -> svg_to_pptx.py（转 PPTX）

用法：
    python3 scripts/md_to_pptx.py --md <文章.md> --out <输出目录> [--name deck]

要求：vendor 转换链需 Python 3.10+（黑苹果上用 /usr/local/bin/python3.11）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
VENDOR = REPO / "vendor" / "ppt-master" / "scripts"

# 黑苹果上有 3.11；其他机器回退到 python3
PY311 = Path("/usr/local/bin/python3.11")
PY = str(PY311 if PY311.exists() else sys.executable)


def run(cmd, **kw):
    print("  $ " + " ".join(str(c) for c in cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print(r.stdout[-1500:])
        print(r.stderr[-1500:], file=sys.stderr)
        raise SystemExit(f"失败: {cmd[1] if len(cmd) > 1 else cmd[0]}")
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Markdown -> PPTX 一键")
    ap.add_argument("--md", type=Path, required=True, help="输入 Markdown 文章")
    ap.add_argument("--out", type=Path, required=True, help="输出目录（项目）")
    ap.add_argument("--name", default="deck", help="PPTX 文件名（不含扩展名）")
    ap.add_argument("--skip-qa", action="store_true", help="跳过质检（调试用）")
    args = ap.parse_args(argv)

    out = args.out
    svg_dir = out / "svg_output"
    (out / "images").mkdir(parents=True, exist_ok=True)

    # spec_lock：没有就从样例项目拷一份默认
    if not (out / "spec_lock.md").exists():
        sample = REPO / "projects" / "agentflow-os-launch" / "spec_lock.md"
        if sample.exists():
            shutil.copy(sample, out / "spec_lock.md")
            print("  [info] 使用默认 spec_lock.md")

    print("[1/6] 切页 md -> pages.json")
    run([sys.executable, str(SCRIPTS / "md_to_pages.py"),
         "--md", str(args.md), "--out", str(out / "pages.json")])

    print("[2/6] 渲染 pages -> SVG")
    run([sys.executable, str(SCRIPTS / "pages_to_svg.py"),
         "--pages", str(out / "pages.json"), "--out", str(svg_dir)])

    if not args.skip_qa:
        print("[3/6] planning 合同校验")
        run([sys.executable, str(SCRIPTS / "plan_contract.py"), "--project", str(out)])
        print("[4/6] 打分质检")
        run([sys.executable, str(SCRIPTS / "qa_score.py"), str(svg_dir)])
        print("[5/6] vendor SVG 质检门禁")
        run([PY, str(VENDOR / "svg_quality_checker.py"), str(out),
             "--canonical-authoring", "--stage", "final", "--json"])

    print("[6/6] SVG -> PPTX")
    pptx = out / (args.name + ".pptx")
    run([PY, str(VENDOR / "svg_to_pptx.py"), str(out), "-o", str(pptx)])

    n = len(json.loads((out / "pages.json").read_text(encoding="utf-8"))["pages"])
    print(f"\n✅ 完成：{n} 页 -> {pptx} ({pptx.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
