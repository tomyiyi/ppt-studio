#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找资料：多视角提问 -> 检索 -> research.json（STORM 方法论轻量版）

设计原则：**领域无关**。
视角模板用通用的认知维度（现状/变化/动因/影响/反例），不绑定任何具体行业术语。
加新领域不需要改这个文件。

输入：主题 + 原始检索结果
输出：research.json {topic, perspectives[], questions[], references[], outline[]}
"""
from __future__ import annotations

import json
import re
from pathlib import Path


# 通用认知视角（STORM Perspective-Guided），跨领域适用
PERSPECTIVES = {
    "现状": "目前这个主题的核心事实是什么？有哪些可量化的数据或事实？",
    "变化": "相比过去发生了什么变化？出现了哪些新东西、消失了哪些旧的？",
    "动因": "为什么会发生这些变化？背后的技术、市场或政策驱动因素是什么？",
    "影响": "这些变化对从业者、用户或下游产生了什么影响？成本收益如何变化？",
    "反例": "有哪些反面案例、失败教训或争议？什么条件下结论不成立？",
    "趋势": "接下来可能往哪个方向走？有哪些苗头或先行指标？",
}


def build_research(topic: str, raw_findings: list[dict]) -> dict:
    """从原始检索结果构建 research.json。

    raw_findings 每项形如：
        {url, title, source, key_points: [...], credibility: "high|medium|low"}
    """
    if not topic:
        raise ValueError("topic 不能为空")

    perspectives = [{"name": n, "question": q} for n, q in PERSPECTIVES.items()]
    questions = [{"perspective": p["name"],
                  "question": f"{topic}：{p['question']}"} for p in perspectives]

    references = []
    for f in raw_findings or []:
        kps = [kp.strip() for kp in (f.get("key_points") or []) if kp and kp.strip()]
        # 一条 key_point 都没有的reference 不纳入（对下游写作无价值）
        if not kps:
            continue
        references.append({
            "url": f.get("url", ""),
            "title": f.get("title", ""),
            "source": f.get("source", "") or "未知来源",
            "key_points": kps,
            "credibility": f.get("credibility", "medium"),
        })

    # outline：跨 reference 提炼主题词。
    # 长度门槛用"显示宽度"而非字符数——单字主题词（红/AI）在中文里合法。
    outline, seen = [], set()
    for ref in references:
        for kp in ref["key_points"]:
            trend = re.split(r"[：:]|——|—", kp, 1)[0].strip()
            if trend and trend not in seen:
                seen.add(trend)
                outline.append({"trend": trend[:20], "source": (ref["title"] or ref["source"])[:30]})

    return {
        "topic": topic,
        "perspectives": perspectives,
        "questions": questions,
        "references": references,
        "outline": outline[:20],  # 最多 20 个信号
        "stats": {
            "source_count": len(references),
            "key_point_count": sum(len(r["key_points"]) for r in references),
            "high_credibility": sum(1 for r in references if r["credibility"] == "high"),
        },
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("用法: python3 do_research.py <raw_findings.json> <topic> <out.json>")
        raise SystemExit(1)
    raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = build_research(sys.argv[2], raw)
    Path(sys.argv[3]).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    s = result["stats"]
    print(f"topic: {result['topic']}")
    print(f"perspectives: {len(result['perspectives'])}")
    print(f"references: {s['source_count']} (high credibility: {s['high_credibility']})")
    print(f"key_points: {s['key_point_count']}")
    print(f"outline: {len(result['outline'])} signals")
    for o in result["outline"]:
        print(f"  - {o['trend']}")
