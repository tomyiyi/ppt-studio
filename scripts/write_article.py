#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写文管线 v2：research.json -> article.md（STORM 方法论）

替代 research_to_article.py 的拼接逻辑。

原则（来自用户要求 + opendraft 双源门禁）：
1. 正文只用 verification=verified 的 claims
2. unverified 的进"待验证"附录，不进正文
3. 大纲先行：按 perspectives 聚类 -> outline（可独立检查）
4. 每条 claim 扩展为段落：主张 + evidence 转述（不复制原文）+ 来源标注
5. 不编造：verified 为空时如实输出"暂无已验证结论"，不硬写

三阶段（STORM）：
    research.json -> outline.json -> article.md
每阶段独立可重跑、可检查。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from datetime import datetime, timezone


# perspectives -> 文章章节的映射（是什么→为什么→怎么办）
PERSPECTIVE_FLOW = [
    ("现状", "是什么"),
    ("变化", "变了什么"),
    ("动因", "为什么"),
    ("影响", "意味着什么"),
    ("反例", "反例与边界"),
]


def load_research(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def split_claims(claims: list[dict]) -> tuple[list[dict], list[dict]]:
    """verified 进正文，unverified 进附录。"""
    verified = [c for c in claims if c.get("verification") == "verified"]
    unverified = [c for c in claims if c.get("verification") != "verified"]
    return verified, unverified


def build_outline(research: dict, verified: list[dict]) -> dict:
    """大纲：按 perspectives 聚类 verified claims。

    每节 2-3 个 claims；没有 verified claims 的视角不建节。
    """
    perspectives = [p["name"] for p in research.get("perspectives", [])]
    # 按 PERSPECTIVE_FLOW 排序，保证 是什么→为什么→怎么办
    order = {name: i for i, (name, _) in enumerate(PERSPECTIVE_FLOW)}

    sections = []
    for pname in sorted(perspectives, key=lambda n: order.get(n, 99)):
        pclaims = [c for c in verified if pname in c.get("perspectives", [])]
        if not pclaims:
            continue
        # 每节 2-3 个 claims，多的拆节
        for i in range(0, len(pclaims), 3):
            chunk = pclaims[i:i + 3]
            flow_label = dict(PERSPECTIVE_FLOW).get(pname, pname)
            title = flow_label if i == 0 else f"{flow_label}（续）"
            sections.append({
                "perspective": pname,
                "title": title,
                "claim_ids": [c["id"] for c in chunk],
            })

    return {
        "topic": research.get("topic", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_verified": len(verified),
        "sections": sections,
    }


def _paraphrase_evidence(claim: str, evidence: str) -> str:
    """evidence 转述：去重、压缩，不复制原文。

    规则版转述（无 LLM 时）：
    - evidence 与 claim 高度重合时，只保留 claim，不重复
    - 否则取 evidence 中 claim 未覆盖的信息点
    """
    c = claim.strip()
    e = evidence.strip()
    if not e or e == c:
        return ""
    # 去掉 evidence 中与 claim 完全重复的句子
    c_sents = set(re.split(r"[。！？]", c))
    e_sents = [s.strip() for s in re.split(r"[。！？]", e) if s.strip()]
    fresh = [s for s in e_sents if s not in c_sents and len(s) > 4]
    if not fresh:
        return ""
    return "。".join(fresh) + "。"


def _source_note(claim: dict) -> str:
    """来源标注：域名 + 级别。"""
    parts = []
    for s in claim.get("sources", [])[:3]:
        url = s.get("url", "")
        m = re.search(r"https?://(?:www\.)?([^/]+)", url)
        domain = m.group(1) if m else url[:30]
        parts.append(domain)
    if not parts:
        return ""
    return "（" + "、".join(parts) + "）"


def expand_claim(claim: dict) -> str:
    """一条 claim -> 一个段落：主张 + 转述 + 来源。"""
    text = claim.get("claim", "").strip()
    evidence = claim.get("evidence", "").strip()
    para = text
    extra = _paraphrase_evidence(text, evidence)
    if extra:
        para += extra if para.endswith(("。", "！", "？")) else "。" + extra
    note = _source_note(claim)
    if note:
        para += note
    return para


def distill_lede(research: dict, verified: list[dict]) -> str:
    """导语：从 verified claims 提炼核心观点。

    规则版：取前 2 条 verified 的核心主张，找对立/并列关系。
    不编造超出 claims 的判断。
    """
    topic = research.get("topic", "")
    if not verified:
        return f"本次研究的主题是{topic}，但暂无通过双源验证的结论，正文从缺。以下为研究过程记录。"

    # 提炼：把 claims 压缩成 1-2 句核心判断
    cores = []
    for c in verified[:4]:
        cl = c.get("claim", "").strip()
        # 取第一句；太长则在标点处断，不断半词
        first = re.split(r"[。！？]", cl)[0]
        if len(first) > 36:
            # 找最后一个逗号/顿号/冒号处断开
            for sep in ("，", "、", "：", "；"):
                idx = first.rfind(sep, 0, 36)
                if idx > 12:
                    first = first[:idx]
                    break
            else:
                first = first[:36]
        cores.append(first)

    if len(cores) == 1:
        return f"{cores[0]}。这是本次研究中唯一通过双源验证的结论。"
    # 多条：并列呈现，不强行找对立
    joined = "；".join(cores)
    return f"本次研究通过双源验证的核心发现有 {len(verified)} 条：{joined}。"


def write_article(research: dict, outline: dict, verified: list[dict],
                  unverified: list[dict]) -> str:
    """research.json + outline -> article.md。"""
    topic = research.get("topic", "未命名主题")
    brief = research.get("brief", {})
    tone = brief.get("tone", "")

    claim_by_id = {c["id"]: c for c in verified}

    lines = [f"# {topic}", ""]
    lines.append(f"> {distill_lede(research, verified)}")
    lines.append("")

    if not verified:
        lines.append("## 研究说明")
        lines.append("")
        lines.append("本次检索未能形成通过双源验证的结论。")
        lines.append("所有候选发现均列在文末「待验证」附录，供进一步核实。")
        lines.append("")
    else:
        for sec in outline["sections"]:
            lines.append(f"## {sec['title']}")
            lines.append("")
            for cid in sec["claim_ids"]:
                c = claim_by_id.get(cid)
                if not c:
                    continue
                lines.append(expand_claim(c))
                lines.append("")
        # 结尾：基于 verified 的收束，不引申
        lines.append("## 写在最后")
        lines.append("")
        if len(verified) == 1:
            c = verified[0]
            lines.append(f"一句话总结：{re.split(r'[。！？]', c['claim'])[0]}。")
        else:
            lines.append(
                f"本篇基于 {len(verified)} 条双源验证的结论写成，"
                f"覆盖 {len(outline['sections'])} 个方面。"
                "更多未经验证的发现见附录。"
            )
        lines.append("")

    # 附录：待验证
    if unverified:
        lines.append("---")
        lines.append("")
        lines.append("## 附录：待验证（未通过双源验证，不进正文）")
        lines.append("")
        lines.append(
            f"以下 {len(unverified)} 条发现仅有单源支撑，"
            "供进一步核实，暂不作为结论引用。"
        )
        lines.append("")
        # 按 perspective 分组
        by_p: dict[str, list[dict]] = {}
        for c in unverified:
            for p in c.get("perspectives", ["未分类"]):
                by_p.setdefault(p, []).append(c)
        for pname in sorted(by_p, key=lambda n: [p for p, _ in PERSPECTIVE_FLOW].index(n)
                            if n in [p for p, _ in PERSPECTIVE_FLOW] else 99):
            lines.append(f"### {pname}（待验证）")
            lines.append("")
            for c in by_p[pname]:
                note = _source_note(c)
                lines.append(f"- {c.get('claim', '').strip()}{note}")
            lines.append("")

    return "\n".join(lines)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="research.json -> article.md（STORM 三阶段）")
    ap.add_argument("--research", required=True, help="research.json 路径")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--name", default="article", help="输出名前缀")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    research = load_research(Path(args.research))
    verified, unverified = split_claims(research.get("claims", []))

    # 阶段 2：大纲（独立产物，可检查）
    outline = build_outline(research, verified)
    (out / f"{args.name}_outline.json").write_text(
        json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")

    # 阶段 3：成文
    article = write_article(research, outline, verified, unverified)
    (out / f"{args.name}.md").write_text(article, encoding="utf-8")

    print(f"verified={len(verified)} unverified={len(unverified)} "
          f"sections={len(outline['sections'])}")
    print(f"-> {out / f'{args.name}.md'}")
    print(f"-> {out / f'{args.name}_outline.json'}")


if __name__ == "__main__":
    main()
