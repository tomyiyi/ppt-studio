#!/usr/bin/env python3
"""N1 叙事结构器：markdown -> narrative.json 骨架。只筛不写。"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

from evidence_from_prose import extract as prose_extract  # S15-C：散文→evidence

ROLES = ("cover", "section", "claim", "data", "mechanism", "teaching", "closing")

# 与 check_narrative.VALID_IMAGE_INTENTS 保持同步（S6 只增不减，不删既有值）
VALID_IMAGE_INTENTS = {"none", "background", "panel", "hero", "asset", "vector"}  # S6 只增：asset=本地图库 / vector=矢量旁路

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

class IntentPlanError(Exception):
    """--intent-plan 里出现非法 image_intent 值。拒绝，不静默降级为 none。"""
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
         "visual_protagonist": "", "image_intent": "none", "scope_note": "",
         # 意图来源：default=没人决定过（等于配图关闭），declared=intent-plan 显式给出
         "image_intent_source": "default"}
    p["_todo"] = [k for k in REQUIRED[role]
                  if not p.get(k) and k != "evidence"]
    # REQUIRED 里列了 image_intent 的 role：默认值 "none" 是"没决定"，不是"决定不配"
    # —— 所以按待审登记（只加不减，任何 W-xx 判据未动）
    if "image_intent" in REQUIRED[role] and p["image_intent_source"] != "declared":
        p["_todo"].append("image_intent")
    return p

def apply_intent(pg: dict, intent: str, source: str = "declared") -> dict:
    """把配图意图写进页并同步 _todo。非法值直接拒绝，不降级。"""
    if intent not in VALID_IMAGE_INTENTS:
        raise IntentPlanError(
            f"非法 image_intent: {intent}（合法集 {sorted(VALID_IMAGE_INTENTS)}）")
    pg["image_intent"] = intent
    pg["image_intent_source"] = source
    if "image_intent" in REQUIRED.get(pg["role"], []):
        if source == "declared":
            pg["_todo"] = [t for t in pg["_todo"] if t != "image_intent"]
        elif "image_intent" not in pg["_todo"]:
            pg["_todo"].append("image_intent")
    return pg

def sync_todo(pg: dict) -> dict:
    """按字段**当前值**重算 _todo。

    blank_page 是在填字段之前算的，封面 assertion 填上以后仍报"缺 assertion"，
    属于登记与实况不符（本阶段实测发现）。统一在 build 末尾重算一次，
    规则本身不变：REQUIRED 缺项 + claim 无 evidence + 未声明的 image_intent。
    """
    role = pg["role"]
    todo = [k for k in REQUIRED[role] if not pg.get(k) and k != "evidence"]
    if role == "claim" and not pg.get("evidence"):
        todo.append("evidence")
    if "image_intent" in REQUIRED[role] and pg.get("image_intent_source") != "declared":
        todo.append("image_intent")
    pg["_todo"] = todo
    return pg

def build(md_path: Path, role_plan: dict | None = None,
          intent_plan: dict | None = None) -> dict:
    """role_plan: {section_heading: role} —— 由人/LLM 给的意图标注。
    intent_plan: {section_heading: image_intent} —— 由人/LLM 显式声明的配图意图。
    两者都是"筛与记"，不代写文案。以 "_" 开头的键按注释处理（本仓 _todo/_src 同规矩），
    其余任何非法值一律抛错不静默 —— 声明写错必须当场知道。"""
    raw = md_path.read_text(encoding="utf-8")
    ip_plan = {k: v for k, v in (intent_plan or {}).items() if not k.startswith("_")}
    for k, v in ip_plan.items():
        if v not in VALID_IMAGE_INTENTS:
            raise IntentPlanError(f"节「{k}」的 image_intent 非法: {v}"
                                  f"（合法集 {sorted(VALID_IMAGE_INTENTS)}）")
    m1 = H1_RE.search(raw); title = m1.group(1).strip() if m1 else md_path.stem
    mq = QUOTE_RE.search(raw); sub = mq.group(1).strip() if mq else ""
    pages = []
    cover = blank_page(0, "cover")
    cover["assertion"] = title
    cover["scope_note"] = sub
    if title in ip_plan:
        apply_intent(cover, ip_plan[title])
    pages.append(cover)
    for k, sec in enumerate(split_sections(raw), start=1):
        role = (role_plan or {}).get(sec["heading"]) or guess_role(sec)
        if role not in ROLES:
            raise RolePlanError(f"非法 role: {role}")
        pg = blank_page(k, role)
        pg["_src"] = f"{md_path.name}#L{sec['start_line']}"
        cands = []
        for pos, l in enumerate(sec["lines"]):
            ls = l.strip()
            bm = BULLET_RE.match(ls)
            if bm:
                # 只去掉列表标记，保留正文本身（旧实现把 "- " 也当证据文本带进 deck）
                cands.append((pos, bm.group(1).strip()))
            elif TABLE_RE.match(ls) and "---" not in ls:
                # 表格分隔行不是证据（md_to_pages 旧路径同样跳过，两条路径口径对齐）
                cands.append((pos, ls))
        for pos, c in cands:
            pg["evidence"].append({
                "kind": kind_of(c),
                "text": strip_md(c),
                "baseline": None,
                # 行号按候选在节内的真实位置算，不按候选序号（否则第二条起就指错行）
                "source": f"{md_path.name}#L{sec['start_line'] + 1 + pos}",
            })
        if not pg["evidence"]:
            # S15-C（主控 2026-10-16 批准 S13 待决项 A）：上面的存量路径只认列表项/表格行，
            # 纯散文正文一句也取不到 —— run2 的 6 条 [W-07] 全部出在这个缺口上。
            # 只在"一条都没取到"时才补，取到过的节绝不掺 prose，避免同一页两种口径。
            # 抽取器只搬运原文、只填字面存在的 baseline，抽不出就继续判红（见模块 docstring）。
            pg["evidence"] = prose_extract(sec["lines"], sec["start_line"],
                                           md_path.name, kind_of, strip_md)
        if role == "claim" and not pg["evidence"]:
            pg["_todo"].append("evidence")
        if sec["heading"] in ip_plan:
            apply_intent(pg, ip_plan[sec["heading"]])
        pages.append(pg)
    matched = {title} | {s["heading"] for s in split_sections(raw)}
    unmatched = sorted(k for k in ip_plan if k not in matched)
    for pg in pages:
        sync_todo(pg)
    return {"source": md_path.name, "governing_thought": "", "audience": "",
            "duration_min": None, "intent_unmatched": unmatched, "pages": pages}

def load_json_arg(val: str | None, what: str = "plan") -> dict | None:
    """内联 JSON 或文件路径都接受。

    编排器 topic_to_deck.py 传的是**路径**，旧实现只 json.loads(字符串)，
    所以 --role-plan/--intent-plan 经编排器调用必然崩（本阶段实测发现）。
    """
    if not val:
        return None
    p = Path(val)
    try:
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
        return json.loads(val)
    except (json.JSONDecodeError, OSError) as e:
        raise SystemExit(f"{what} 解析失败（内联 JSON 或文件路径皆可）："
                         f"{str(val)[:60]} → {e}")

def main():
    ap = argparse.ArgumentParser(description="N1 叙事结构器")
    ap.add_argument("--md", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--role-plan", type=str, default=None,
                    help='JSON: {"节标题": "role"}')
    ap.add_argument("--intent-plan", type=str, default=None,
                    help='JSON: {"节标题或主标题": "none|background|panel|hero"}，显式声明配图意图')
    ap.add_argument("--governing", default="")
    ap.add_argument("--audience", default="")
    ap.add_argument("--duration-min", type=int, default=None)
    args = ap.parse_args()

    rp = load_json_arg(args.role_plan, "--role-plan")
    ip = load_json_arg(args.intent_plan, "--intent-plan")
    nar = build(args.md, rp, ip)
    nar["governing_thought"] = args.governing
    nar["audience"] = args.audience
    nar["duration_min"] = args.duration_min

    args.out.write_text(json.dumps(nar, ensure_ascii=False, indent=2), encoding="utf-8")

    declared = [pg for pg in nar["pages"] if pg.get("image_intent_source") == "declared"]
    print(f"配图意图：显式声明 {len(declared)} 页 / 共 {len(nar['pages'])} 页"
          f"（未声明的按 none 处理 = 生图阶段跳过）")
    for pg in nar["pages"]:
        if pg["_todo"]:
            print(f"  页 {pg['index']:02d} [{pg['role']}] 缺: {', '.join(pg['_todo'])}")
    if nar["intent_unmatched"]:
        print(f"  ⚠ intent-plan 有 {len(nar['intent_unmatched'])} 个键没对上任何节/主标题: "
              f"{', '.join(nar['intent_unmatched'][:6])}")

if __name__ == "__main__":
    main()
