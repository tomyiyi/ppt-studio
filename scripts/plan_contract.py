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
import html
import json
import re
import sys
from pathlib import Path

HREF_RE = re.compile(r'href="\.\./images/([^"]+)"')
TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)

# 内容完整性：条目文字在 SVG 里可能被换行/转义拆开，用"去空白后的前缀是否出现"判定
BULLET_PREFIX = 8
CELL_PREFIX = 6


def _flat(s: str) -> str:
    return re.sub(r"\s+", "", html.unescape(s or ""))


def check_content_loss(project: Path, svg_dir: Path) -> list:
    """pages.json 里的每条 bullet / 表格单元格，必须在对应 SVG 中真实画出。
    渲染器任何"放不下就不画"的分支都会在这里被抓成 blocking。"""
    errs = []
    pages_file = project / "pages.json"
    if not pages_file.exists():
        return ["缺 pages.json，无法校验内容完整性"]
    try:
        plan = json.loads(pages_file.read_text(encoding="utf-8"))
    except Exception as e:
        return ["pages.json 解析失败: %s" % e]
    for pg in plan.get("pages", []):
        bullets = pg.get("bullets") or []
        if not bullets:
            continue
        svg = svg_dir / ("%02d_%s.svg" % (pg.get("index", 0), pg.get("layout", "bullets")))
        if not svg.exists():
            errs.append("p%02d 缺 SVG: %s" % (pg.get("index", 0), svg.name))
            continue
        hay = _flat(svg.read_text(encoding="utf-8"))
        layout = pg.get("layout")
        for b in bullets:
            b = b.strip()
            if layout == "table" and b.startswith("|"):
                if set(b) <= set("|-: "):
                    continue
                for cell in (c.strip() for c in b.strip("|").split("|")):
                    n = _flat(cell)[:CELL_PREFIX]
                    if n and n not in hay:
                        errs.append("p%02d(table) 单元格未画出: '%s'" % (pg.get("index", 0), cell[:20]))
            else:
                n = _flat(b)[:BULLET_PREFIX]
                if n and n not in hay:
                    errs.append("p%02d(%s) 条目未画出: '%s'" % (pg.get("index", 0), layout, b[:24]))
    return errs

REQUIRED_SPEC_SECTIONS = ["## canvas", "## colors", "## typography", "## grid"]


def check_spec_parity(project: Path, template: Path) -> list[str]:
    """工程 spec_lock 与模板的节名集合对账：缺节 = blocking，多节 = 只提示。"""
    try:
        import spec_tokens as ST
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import spec_tokens as ST
    want = ST.section_names(template.read_text(encoding="utf-8"))
    got = ST.section_names((project / "spec_lock.md").read_text(encoding="utf-8"))
    want = {w.strip() for w in want}
    got = {g.strip() for g in got}
    missing = sorted(want - got)
    extra = sorted(got - want)
    out = [f"[blocking] 缺节 {m}（模板有、工程无）" for m in missing]
    out += [f"[提示] 工程多出节 {e}" for e in extra]
    return out


def check_narrative_landing(project: Path, svg_dir: Path) -> list[str]:
    """narrative.json 的每条断言必须真的落在对应 SVG 上。缺 narrative.json 走兼容分支。"""
    nar = project / "narrative.json"
    if not nar.exists():
        print("[兼容] 无 narrative.json，跳过落点校验（历史工程路径不变）")
        return []
    plan = json.loads(nar.read_text(encoding="utf-8"))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from check_narrative import resolve_source
    ROLES = ("cover", "section", "claim", "data", "mechanism", "teaching", "closing")
    out = []
    base_dir = project
    for pg in plan.get("pages", []):
        idx, role = pg["index"], pg.get("role", "")
        if role not in ROLES:
            out.append(f"[blocking] 页 {idx:02d} role 非法: {role}")
            continue
        hit = sorted(svg_dir.glob(f"{idx:02d}_{role}.svg")) or \
              sorted(svg_dir.glob(f"{idx:02d}_*.svg"))
        if not hit:
            out.append(f"[blocking] 页 {idx:02d} 无对应 SVG")
            continue
        text = _flat(hit[0].read_text(encoding="utf-8"))
        for f in ("assertion", "so_what"):
            v = (pg.get(f) or "").strip()
            if v and _flat(v)[:8] not in text:
                out.append(f"[blocking] 页 {idx:02d} {f} 未落进 {hit[0].name}: {v[:20]}")
        for ev in pg.get("evidence", []):
            if not resolve_source(ev.get("source", ""), base_dir):
                out.append(f"[blocking] 页 {idx:02d} evidence 回指解析失败: {ev.get('source')}")
    return out


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
        tmpl = Path(__file__).resolve().parent.parent / "patterns" / "spec_lock.template.md"
        if tmpl.exists():
            for e in check_spec_parity(project, tmpl):
                if e.startswith("[blocking]"):
                    plan["errors"].append(e)

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

    # 内容完整性（blocking）：静默丢条目比排版瑕疵严重得多
    for e in check_content_loss(project, svg_dir):
        plan["errors"].append(e)

    # 叙事落点校验（缺 narrative.json 走兼容分支）
    for e in check_narrative_landing(project, svg_dir):
        if e.startswith("[blocking]"):
            plan["errors"].append(e)
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
