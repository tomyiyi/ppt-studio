#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打分制质检 + 证据链（源自 ContentForge 低创作度预检模式）

qa_layout.py 是二值门禁（pass/fail 计 bad 数），这里升级为：
- 每个检查项输出 0-100 分 + evidence 证据列表
- 按权重汇总整页得分，低于阈值（默认 80）判需人工复核
- 输出 JSON 报告到 <project>/validation/qa_score.json

用法：
    python3 scripts/qa_score.py <project>/svg_output <project>/qa_render [--threshold 80]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_layout import (
    check_backdrop, check_contrast, check_dup_images, check_line_collisions,
    check_overflow, check_typescale, load_ramp, WCAG_MIN,
)

# 检查项权重（总和 100）
WEIGHTS = {
    "typescale": 20,    # 字号阶梯
    "backdrop": 15,     # 底图覆盖
    "dup_images": 15,   # 重影
    "overflow": 20,     # 溢出
    "collisions": 10,   # 压行
    "contrast": 20,     # 对比度
}
THRESHOLD_DEFAULT = 80


def clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def score_page(svg_path: Path, render_png: Path | None, ramp: set, margin: int = 76) -> dict:
    root = ET.parse(str(svg_path)).getroot()
    checks = []

    used, off = check_typescale(root, ramp)
    checks.append({"name": "typescale", "weight": WEIGHTS["typescale"],
                   "score": clamp(100 - 25 * len(off)),
                   "evidence": [f"越出阶梯: {s}px" for s in off] or [f"用 {len(used)} 档字号"]})

    cov = check_backdrop(root)
    if cov is None:
        checks.append({"name": "backdrop", "weight": WEIGHTS["backdrop"],
                       "score": 100.0, "evidence": ["无图片（N/A)"]})
    else:
        checks.append({"name": "backdrop", "weight": WEIGHTS["backdrop"],
                       "score": clamp(cov if cov < 90 else 100.0),
                       "evidence": [f"底图覆盖 {cov:.1f}%"]})

    dups = check_dup_images(root)
    checks.append({"name": "dup_images", "weight": WEIGHTS["dup_images"],
                   "score": clamp(100 - 50 * len(dups)),
                   "evidence": [f"重影: {d}" for d in dups] or ["无重影"]})

    ov = check_overflow(root, margin=margin)
    checks.append({"name": "overflow", "weight": WEIGHTS["overflow"],
                   "score": clamp(100 - 20 * len(ov)),
                   "evidence": ov[:6] or ["无溢出"]})

    col = check_line_collisions(root)
    checks.append({"name": "collisions", "weight": WEIGHTS["collisions"],
                   "score": clamp(100 - 15 * len(col)),
                   "evidence": col[:6] or ["无压行"]})

    if render_png and render_png.exists():
        from PIL import Image
        img = Image.open(render_png)
        rows = check_contrast(img, root)
        if not rows:
            checks.append({"name": "contrast", "weight": WEIGHTS["contrast"],
                           "score": 100.0, "evidence": ["无可测文本"]})
        else:
            fails = [r for r in rows if r[0] < WCAG_MIN]
            score = clamp(100.0 * (len(rows) - len(fails)) / len(rows))
            checks.append({"name": "contrast", "weight": WEIGHTS["contrast"],
                           "score": score,
                           "evidence": [f"{r[0]:.1f}:1 《{r[1][:20]}》" for r in fails[:6]]
                           or [f"最低 {min(r[0] for r in rows):.1f}:1，全过"]})
    else:
        checks.append({"name": "contrast", "weight": WEIGHTS["contrast"],
                       "score": 100.0, "evidence": ["无渲染 PNG，跳过"]})

    total = sum(c["score"] * c["weight"] for c in checks) / 100.0
    return {"page": svg_path.name, "score": round(total, 1), "checks": checks}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="打分制质检")
    ap.add_argument("svg_dir")
    ap.add_argument("render_dir", nargs="?")
    ap.add_argument("--threshold", type=float, default=THRESHOLD_DEFAULT)
    ap.add_argument("--emit", help="JSON 报告输出路径")
    args = ap.parse_args(argv)

    svg_dir = Path(args.svg_dir)
    project = svg_dir.parent
    ramp = load_ramp(str(project / "spec_lock.md"))

    # 尝试从 spec_tokens 读取 margin
    margin = 76  # 兜底
    try:
        import spec_tokens as ST
        tok = ST.load(project / "spec_lock.md")
        margin = tok.margin
        ramp = set(tok.ramp)
    except Exception:
        pass

    def find_png(stem):
        if not args.render_dir:
            return None
        for pat in (f"{stem}.png", f"{stem}/*.png", f"**/{stem}.png"):
            hit = [q for q in glob.glob(os.path.join(args.render_dir, pat), recursive=True)
                   if os.path.isfile(q)]
            if hit:
                return Path(hit[0])
        return None

    report = {"threshold": args.threshold, "pages": [], "review_required": []}
    for svg in sorted(svg_dir.glob("*.svg")):
        stem = svg.stem
        pg = score_page(svg, find_png(stem), ramp, margin=margin)
        pg["pass"] = pg["score"] >= args.threshold
        report["pages"].append(pg)
        mark = "OK " if pg["pass"] else "REVIEW"
        print(f"[{mark}] {stem}: {pg['score']:.0f}")
        if not pg["pass"]:
            report["review_required"].append(stem)
            for c in pg["checks"]:
                if c["score"] < 100:
                    print(f"    {c['name']}: {c['score']:.0f} | " + "; ".join(c["evidence"][:2]))

    if args.emit:
        Path(args.emit).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告 -> {args.emit}")

    n_fail = len(report["review_required"])
    print(f"\n{len(report['pages'])} 页，{n_fail} 页需复核（阈值 {args.threshold:.0f}）")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
