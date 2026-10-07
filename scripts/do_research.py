#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找资料：多视角提问 -> 检索 -> research.json（STORM 方法论轻量版）

输入：主题
输出：research.json {topic, perspectives[], questions[], references[], outline[]}
"""
from __future__ import annotations

import json
import re
from pathlib import Path


# 预置视角模板（STORM Perspective-Guided）
PERSPECTIVES = {
    "色彩": "本季主导色是什么？有哪些新的色彩组合？",
    "廓形": " silhouette 有什么变化？oversize 还是修身？",
    "材质": "哪些面料/质感是重点？",
    "品牌": "哪些大牌在引领？有什么标志性单品？",
    "风格": "整体美学走向？复古/未来/极简/极繁？",
}


def build_research(topic: str, raw_findings: list[dict]) -> dict:
    """从原始检索结果构建 research.json。"""
    perspectives = []
    for name, question in PERSPECTIVES.items():
        perspectives.append({"name": name, "question": question})

    questions = []
    for p in perspectives:
        questions.append({
            "perspective": p["name"],
            "question": f"{topic}：{p['question']}",
        })

    references = []
    for f in raw_findings:
        references.append({
            "url": f.get("url", ""),
            "title": f.get("title", ""),
            "source": f.get("source", ""),
            "key_points": f.get("key_points", []),
            "credibility": f.get("credibility", "medium"),
        })

    # 大纲：从 references 提炼
    outline = []
    seen = set()
    for ref in references:
        for kp in ref["key_points"]:
            # 提炼趋势名（取冒号前或前12字）
            trend = re.split(r"[：:]", kp)[0].strip()[:12]
            if trend and trend not in seen and len(trend) >= 4:
                seen.add(trend)
                outline.append({"trend": trend, "source": ref["title"][:30]})

    return {
        "topic": topic,
        "perspectives": perspectives,
        "questions": questions,
        "references": references,
        "outline": outline[:10],  # 最多10个趋势
    }


if __name__ == "__main__":
    import sys
    # 从 JSON 文件读取 raw findings
    raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    topic = sys.argv[2]
    out = Path(sys.argv[3])
    result = build_research(topic, raw)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"topic: {topic}")
    print(f"perspectives: {len(result['perspectives'])}")
    print(f"references: {len(result['references'])}")
    print(f"outline trends: {len(result['outline'])}")
    for o in result["outline"]:
        print(f"  - {o['trend']}")
