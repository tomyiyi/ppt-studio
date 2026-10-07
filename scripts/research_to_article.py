#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写文：research.json -> 文章 Markdown（fabric pattern 轻量版）

流程：extract_claims（提趋势）-> rewrite（写成专题文章）-> hook（标题）
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def research_to_article(research_path: Path, out_path: Path) -> Path:
    r = json.loads(research_path.read_text(encoding="utf-8"))
    topic = r["topic"]

    # 按视角聚类趋势
    clusters = {
        "色彩": [],
        "廓形": [],
        "材质": [],
        "风格": [],
    }

    for ref in r["references"]:
        for kp in ref["key_points"]:
            kl = kp.lower()
            if any(w in kp for w in ["红", "灰", "棕", "蓝", "绿", "色", "red", "grey", "brown"]):
                clusters["色彩"].append((kp, ref["source"]))
            elif any(w in kp for w in ["廓形", "oversize", "西装", "套装", "外套", "suit", "廓"]):
                clusters["廓形"].append((kp, ref["source"]))
            elif any(w in kp for w in ["皮草", "蕾丝", "天鹅绒", "皮革", "质感", "面料", "leather", "lace", "velvet"]):
                clusters["材质"].append((kp, ref["source"]))
            else:
                clusters["风格"].append((kp, ref["source"]))

    # 写文章
    lines = [f"# {topic}：5 大关键词", ""]
    lines.append("> 告别 quiet luxury，这一季要的是存在感。")
    lines.append("")

    # 选 5 个最具代表性的趋势（每类选 1-2 个）
    selected = []
    for cat in ["色彩", "廓形", "材质", "风格"]:
        items = clusters[cat][:2]
        for kp, src in items:
            # 清洗：去掉 emoji，提炼
            clean = re.sub(r"[🍷🤎🧥🧸🖤✨🌹🧣]", "", kp).strip()
            trend_name = re.split(r"[：:]", clean)[0].strip()[:14]
            detail = re.split(r"[：:]", clean)[1].strip()[:60] if "：" in clean or ":" in clean else clean[:60]
            selected.append((trend_name, detail, src))
            if len(selected) >= 5:
                break
        if len(selected) >= 5:
            break

    for i, (name, detail, src) in enumerate(selected[:5], 1):
        lines.append(f"## 趋势{i}｜{name}")
        lines.append("")
        lines.append(f"{detail}（{src}）")
        lines.append("")

    # 对照表
    lines.append("## 5 大趋势速览")
    lines.append("")
    lines.append("| 趋势 | 关键词 | 来源 |")
    lines.append("|---|---|---|")
    for name, detail, src in selected[:5]:
        kw = detail[:12]
        lines.append(f"| {name} | {kw} | {src} |")
    lines.append("")
    lines.append("## 写在最后")
    lines.append("")
    lines.append("这一季的核心是**存在感**：红色要穿全身，皮革要做主角，外套要 oversize。quiet luxury 退场，maximalism 回归。")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"article: {len(selected)} trends -> {out_path}")
    return out_path


if __name__ == "__main__":
    import sys
    research_to_article(Path(sys.argv[1]), Path(sys.argv[2]))
