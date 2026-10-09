#!/usr/bin/env python3
"""N1 叙事结构器：markdown -> narrative.json 骨架。只筛不写。"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

ROLES = ("cover", "section", "claim", "data", "mechanism", "teaching", "closing")

REQUIRED = {
    "cover":     ["assertion"],
    "section":   ["assertion"],
    "claim":     ["assertion", "evidence", "so_what", "visual_protagonist", "image_intent"],
    "data":      ["assertion", "evidence", "so_what", "image_intent"],
    "mechanism": ["assertion", "evidence", "so_what", "visual_protagonist", "image_intent"],
    "teaching":  ["assertion", "evidence", "so_what", "image_intent"],
    "closing":   ["assertion", "so_what"],
}

class RolePlanError(Exception):
    pass

H1_RE = re.compile(r"^#\s+(.+)$", re.M)
H2_RE = re.compile(r"^##\s+(.+)$", re.M)
QUOTE_RE = re.compile(r"^>\s*(.+)$", re.M)
BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
TABLE_RE = re.compile(r"^\s*\|")

def guess_role(sec: dict) -> str:
    """启发式候选 role（仅候选，N2 会校验，人可读 _todo 覆盖）。"""
    h = sec["heading"]
    if re.search(r"表|数据|对比", h):
        return "data"
    if re.search(r"流程|机制|链路|步骤", h):
        return "mechanism"
    if re.search(r"错|对|容易|注意|对照", h):
        return "teaching"
    if re.search(r"总结|下一步|行动|落地", h):
        return "closing"
    return "claim"

def kind_of(text: str) -> str:
    if text.lstrip().startswith("|"):
        return "row"
    if re.search(r"\d", text):
        return "number"
    if re.search(r"截图|图|照片", text):
        return "image"
    return "text"

def strip_md(text: str) -> str:
    return re.sub(r"[*_`\[\]]", "", text).strip()

def split_sections(md_text: str) -> list[dict]:
    """按 ## 切节，每节带原文起始行号（回指用），不改写任何文字。"""
    lines = md_text.split("\n")
    hits = [(i, H2_RE.match(l)) for i, l in enumerate(lines) if H2_RE.match(l)]
    out = []
    for k, (ln, m) in enumerate(hits):
        end = hits[k + 1][0] if k + 1 < len(hits) else len(lines)
        out.append({"heading": m.group(1).strip(), "start_line": ln + 1,
                    "lines": lines[ln + 1:end]})
    return out

def blank_page(i: int, role: str) -> dict:
    p = {"index": i, "role": role, "assertion": "", "evidence": [], "so_what": "",
         "visual_protagonist": "", "image_intent": "none", "scope_note": ""}
    p["_todo"] = [k for k in REQUIRED[role]
                  if not p.get(k) and k != "evidence"]
    return p

def build(md_path: Path, role_plan: dict | None = None) -> dict:
    """role_plan: {section_heading: role} —— 由人/LLM 给的意图标注。"""
    raw = md_path.read_text(encoding="utf-8")
    m1 = H1_RE.search(raw); title = m1.group(1).strip() if m1 else md_path.stem
    mq = QUOTE_RE.search(raw); sub = mq.group(1).strip() if mq else ""
    pages = []
    cover = blank_page(0, "cover")
    cover["assertion"] = title
    cover["scope_note"] = sub
    pages.append(cover)
    for k, sec in enumerate(split_sections(raw), start=1):
        role = (role_plan or {}).get(sec["heading"]) or guess_role(sec)
        if role not in ROLES:
            raise RolePlanError(f"非法 role: {role}")
        pg = blank_page(k, role)
        pg["_src"] = f"{md_path.name}#L{sec['start_line']}"
        cands = [l.strip() for l in sec["lines"]
                 if BULLET_RE.match(l.strip()) or TABLE_RE.match(l.strip())]
        for j, c in enumerate(cands):
            pg["evidence"].append({
                "kind": kind_of(c),
                "text": strip_md(c),
                "baseline": None,
                "source": f"{md_path.name}#L{sec['start_line'] + 1 + j}",
            })
        if role == "claim" and not pg["evidence"]:
            pg["_todo"].append("evidence")
        pages.append(pg)
    return {"source": md_path.name, "governing_thought": "", "audience": "",
            "duration_min": None, "pages": pages}

def main():
    ap = argparse.ArgumentParser(description="N1 叙事结构器")
    ap.add_argument("--md", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--role-plan", type=str, default=None,
                    help='JSON: {"节标题": "role"}')
    ap.add_argument("--governing", default="")
    ap.add_argument("--audience", default="")
    ap.add_argument("--duration-min", type=int, default=None)
    args = ap.parse_args()

    rp = json.loads(args.role_plan) if args.role_plan else None
    nar = build(args.md, rp)
    nar["governing_thought"] = args.governing
    nar["audience"] = args.audience
    nar["duration_min"] = args.duration_min

    args.out.write_text(json.dumps(nar, ensure_ascii=False, indent=2), encoding="utf-8")

    for pg in nar["pages"]:
        if pg["_todo"]:
            print(f"  页 {pg['index']:02d} [{pg['role']}] 缺: {', '.join(pg['_todo'])}")

if __name__ == "__main__":
    main()
