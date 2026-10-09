#!/usr/bin/env python3
"""N2 写作门禁：W-xx 机械化判定。只把可机械判定的升级为 blocking。"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

NOUN_TAIL_RE = re.compile(r"(背景|概况|分析|介绍|说明|总结|举措|现状|概览)$")
TWO_POINT_RE = re.compile(r"(以及|，且|，并|、| 和 )")
FLUFF = ("赋能", "抓手", "闭环", "颗粒度", "底层逻辑", "心智", "打法", "势能", "对齐", "拉通")
BASELINE_WORDS = ("可能", "大概", "左右", "若干", "一定", "适当")
COPY_MAX = 0.40  # 本仓自定（D 级），非外部标准

REQUIRED = {
    "cover":     ["assertion"],
    "section":   ["assertion"],
    "claim":     ["assertion", "evidence", "so_what", "visual_protagonist", "image_intent"],
    "data":      ["assertion", "evidence", "so_what", "image_intent"],
    "mechanism": ["assertion", "evidence", "so_what", "visual_protagonist", "image_intent"],
    "teaching":  ["assertion", "evidence", "so_what", "image_intent"],
    "closing":   ["assertion", "so_what"],
}

VALID_IMAGE_INTENTS = {"none", "background", "panel", "hero"}

def resolve_source(source: str, base_dir: Path) -> tuple[Path, int] | None:
    """'a.md#L12' -> (路径, 行号)；解析不了返回 None。"""
    if "#" not in source:
        return None
    f, frag = source.split("#", 1)
    m = re.match(r"L(\d+)", frag)
    if not m:
        return None
    p = (base_dir / f) if f else None
    if p is None or not p.exists():
        return None
    return p, int(m.group(1))

def copy_ratio(text: str, src_text: str, n: int = 5) -> float:
    """按 n 元字符 shingle 估计与原文的照抄比例。"""
    t = re.sub(r"\s", "", text); s = re.sub(r"\s", "", src_text)
    if len(t) < n or not s:
        return 1.0 if t and t in s else 0.0
    sh = [t[i:i + n] for i in range(len(t) - n + 1)]
    return sum(1 for g in sh if g in s) / len(sh)

def _cjk_len(s: str) -> int:
    return sum(1 if ord(c) > 0x2E7F else 0.55 for c in s)

def check(plan: dict, src_text: str = "", base_dir: Path | None = None) -> tuple[list[str], list[str]]:
    """返回 (blocking, human_read)。每条消息带 [W-xx] 前缀与页号。"""
    blocking: list[str] = []
    human_read: list[str] = []
    base = base_dir or Path(".")

    for pg in plan.get("pages", []):
        idx = pg["index"]
        role = pg.get("role", "claim")
        assertion = (pg.get("assertion") or "").strip()

        # W-01: assertion 以名词短语结尾（启发式）
        if assertion and NOUN_TAIL_RE.search(assertion):
            blocking.append(f"[W-01] 页 {idx:02d} 标题像名词短语: {assertion[:20]}")

        # W-02: 一页两个论点
        if assertion and TWO_POINT_RE.search(assertion):
            blocking.append(f"[W-02] 页 {idx:02d} 标题含双论点: {assertion[:20]}")

        # W-05: assertion 含 fluff 词
        if assertion:
            for fw in FLUFF:
                if fw in assertion:
                    blocking.append(f"[W-05] 页 {idx:02d} 标题含 fluff 词 «{fw}»")
                    break

        # W-06: assertion 长度
        clen = _cjk_len(assertion)
        if assertion and (clen > 40 or clen < 6):
            blocking.append(f"[W-06] 页 {idx:02d} 标题长度 {clen:.0f} 字（应 6-40）")

        # W-07: evidence 为空但 role 要求
        evidence = pg.get("evidence", [])
        if role in ("claim", "data", "mechanism", "teaching") and not evidence:
            blocking.append(f"[W-07] 页 {idx:02d} [{role}] 缺 evidence")

        for ev in evidence:
            # W-12: number 类 evidence 缺 baseline
            if ev.get("kind") == "number" and not ev.get("baseline"):
                blocking.append(f"[W-12] 页 {idx:02d} 数字证据缺 baseline: {ev.get('text', '')[:20]}")

            # W-18: 照抄率
            if src_text and ev.get("text"):
                cr = copy_ratio(ev["text"], src_text)
                if cr > COPY_MAX:
                    blocking.append(f"[W-18] 页 {idx:02d} 照抄率 {cr:.0%} > {COPY_MAX:.0%}")

            # W-19: evidence 缺 source 或回指解析失败
            src = ev.get("source", "")
            if not src:
                blocking.append(f"[W-19] 页 {idx:02d} evidence 缺 source")
            elif not resolve_source(src, base):
                blocking.append(f"[W-19] 页 {idx:02d} evidence 回指解析失败: {src}")

        # W-24: so_what 为空或含含糊词
        so_what = (pg.get("so_what") or "").strip()
        if not so_what:
            blocking.append(f"[W-24] 页 {idx:02d} 缺 so_what")
        else:
            for bw in BASELINE_WORDS:
                if bw in so_what:
                    blocking.append(f"[W-24] 页 {idx:02d} so_what 含含糊词 «{bw}»")
                    break

        # W-27: visual_protagonist 为空但 image_intent != none
        ii = pg.get("image_intent", "none")
        vp = (pg.get("visual_protagonist") or "").strip()
        if ii != "none" and not vp:
            blocking.append(f"[W-27] 页 {idx:02d} image_intent={ii} 但缺 visual_protagonist")

        # W-28: image_intent 不在合法集
        if ii not in VALID_IMAGE_INTENTS:
            blocking.append(f"[W-28] 页 {idx:02d} image_intent 非法: {ii}")

        # W-29: scope_note 缺失（封面/closing 外）
        if role not in ("cover", "closing") and not pg.get("scope_note"):
            human_read.append(f"[W-29] 页 {idx:02d} 缺 scope_note")

    # 已知盲区（脚本判不了）
    human_read.append("[W-03] 论点是否成立 —— 需人读")
    human_read.append("[W-04] 证据是否充分支持论点 —— 需人读")
    human_read.append("[W-09] so_what 是决策而非复述 —— 需人读")

    return blocking, human_read

def main():
    if len(sys.argv) < 2:
        print("用法: check_narrative.py <narrative.json> [source_dir]")
        sys.exit(1)
    nar_path = Path(sys.argv[1])
    base_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else nar_path.parent
    plan = json.loads(nar_path.read_text(encoding="utf-8"))

    src_text = ""
    src_md = base_dir / "README.md"
    if src_md.exists():
        src_text = src_md.read_text(encoding="utf-8")

    blocking, human_read = check(plan, src_text, base_dir)

    for b in blocking:
        print(f"  BLOCKING  {b}")
    for h in human_read:
        print(f"  需人读    {h}")

    print(f"\nblocking {len(blocking)} 条 / 需人读 {len(human_read)} 条")
    if blocking:
        print("FAIL(部分)：可机械判定的 W-xx 有 blocking。")
    else:
        print("PASS(部分)：只代表可机械判定的 W-01/02/05/06/07/12/18/19/24/27/28 全过，不代表写作合格。")
    sys.exit(1 if blocking else 0)

if __name__ == "__main__":
    main()
