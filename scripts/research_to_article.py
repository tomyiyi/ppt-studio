#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写文：research.json -> 文章 Markdown

从 references 的key_points 提炼趋势，按类别聚合成一篇文章。
**不硬编码任何具体主题的结论**——所有内容必须来自输入的 research.json。

输出结构由 KEYWORD_CATEGORIES 决定的通用聚类逻辑生成；
若一条趋势都没聚出来，函数会明确报错，而不是编造内容。
"""
from __future__ import annotations

import json
import re
from pathlib import Path


# 通用聚类：类别名 -> 触发词。这些是**跨主题**的语义类别，不是某个领域的术语。
# 每个类别会自动从 key_points 里吸收匹配的趋势。
KEYWORD_CATEGORIES = {
    "变化": ["变化", "趋势", "转向", "崛起", "回归", "取代", "替代", "升级", "演进",
             "shift", "trend", "replace", "emerge", "return", "upgrade"],
    "冲突": ["冲突", "矛盾", "对立", "分歧", "争议", "下降", "衰退", "失速", "瓶颈",
             "problem", "conflict", "decline", "risk", "issue", "challenge"],
    "技术": ["技术", "架构", "算法", "模型", "自动化", "智能", "工程", "标准", "协议",
             "tech", "model", "architecture", "auto", "standard", "engine"],
    "方法": ["方法", "策略", "路径", "步骤", "实践", "流程", "方式", "机制", "原则",
             "method", "strategy", "practice", "process", "principle"],
    "效果": ["提升", "下降", "降低", "节省", "倍", "%", "增长", "效率", "成本", "速度",
             "improve", "reduce", "save", "faster", "efficiency", "cost"],
    "案例": ["例如", "案例", "比如", "样本", "实测", "报告显示", "统计",
             "example", "case", "sample", "report", "study"],
}

# 兜底类别：没有任何关键词命中时，归入此处，避免趋势凭空消失
FALLBACK = "观察"

# emoji 清洗：覆盖新闻标题里常见的装饰性符号
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF☀-➿️⬜-⯿]"
)


def _clean(text: str) -> str:
    """去emoji、去零宽字符、去首尾空白。"""
    text = EMOJI_RE.sub("", text)
    text = text.replace("", "").replace("﻿", "")
    return text.strip()


def _split_kp(kp: str) -> tuple[str, str]:
    """把 key_point 切成 (趋势名, 展开说明)。

    支持两种形态：
      - "趋势名：说明"       -> ("趋势名", "说明")
      - "趋势名——说明"       -> ("趋势名", "说明")
      - 纯说明（无分隔符）    -> (前若干字, 全文)
    """
    kp = _clean(kp)
    m = re.split(r"[：:]|——|—", kp, 1)
    name = m[0].strip()
    detail = m[1].strip() if len(m) > 1 else ""
    if not name:
        name = kp[:12].strip()
        detail = kp
    return name, detail


def _assign_category(text: str) -> str:
    """把一条趋势归入最匹配��类别（关键词命中数最多的那一类）。"""
    tl = text.lower()
    best, best_hits = FALLBACK, 0
    for cat, words in KEYWORD_CATEGORIES.items():
        hits = sum(1 for w in words if w.lower() in tl)
        if hits > best_hits:
            best, best_hits = cat, hits
    return best


def research_to_article(research_path: Path, out_path: Path,
                        max_trends: int = 5) -> Path:
    """把 research.json 写成一篇 Markdown 专题文章。

    内容 100% 来自 research.json。没有素材就报错，绝不编造。
    """
    r = json.loads(research_path.read_text(encoding="utf-8"))
    topic = r.get("topic", "").strip()
    refs = r.get("references", []) or []
    if not topic:
        raise ValueError("research.json 缺少 topic")
    if not refs:
        raise ValueError(
            f"research.json 没有 references，无法写成文章（topic={topic!r}）。"
            "请先补充素材——本脚本不会凭空生成内容。"
        )

    # 1. 收集所有去重后的趋势
    seen_names: set[str] = set()
    candidates: list[dict] = []
    for ref in refs:
        source = ref.get("source") or ref.get("title") or "未知来源"
        for kp in ref.get("key_points", []) or []:
            name, detail = _split_kp(kp)
            # 趋势名去重：同名只保留第一次出现。
            # 不设最小长度门槛——中文单字（甲/乙/红/冷）作为趋势名是合法的。
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            # 优先保留信息量更大的 key_point（有说明的优先）
            candidates.append({
                "name": name,
                "detail": detail,
                "source": source,
                "cat": _assign_category(name + " " + detail),
            })

    if not candidates:
        raise ValueError(
            f"references 里没有可用的 key_points（topic={topic!r}）。"
            "请确认每条reference 都有非空 key_points 列表。"
        )

    # 2. 按类别取样，保证文章结构有层次而不是同质化
    by_cat: dict[str, list[dict]] = {}
    for c in candidates:
        by_cat.setdefault(c["cat"], []).append(c)

    selected: list[dict] = []
    # 轮转各类别，避免某一类霸占全部名额
    order = sorted(by_cat.keys(), key=lambda k: -len(by_cat[k]))
    idx = 0
    while len(selected) < max_trends and any(by_cat[k] for k in order):
        k = order[idx % len(order)]
        if by_cat[k]:
            selected.append(by_cat[k].pop(0))
        idx += 1
        if idx > max_trends * len(order) + 10:  # 死循环保护
            break

    n = len(selected)
    # 标题里的数字必须与实际条数一致，不能写死"5 大"
    title_num = {5: "5", 4: "4", 3: "3", 2: "两"}.get(n, str(n))

    # 3. 组装文章
    L: list[str] = [f"# {topic}：{title_num} 个关键信号", ""]
    L.append(f"> 本文由 {len(refs)} 条来源材料提炼，覆盖 "
             f"{len({c['cat'] for c in selected})} 个维度。")
    L.append("")

    for i, c in enumerate(selected, 1):
        L.append(f"## {i}｜{c['name']}")
        L.append("")
        body = c["detail"] or c["name"]
        L.append(f"{body}（来源：{c['source']}）")
        L.append("")

    # 速览表
    L.append(f"## {title_num} 个信号速览")
    L.append("")
    L.append("| 信号 | 维度 | 要点 | 来源 |")
    L.append("|---|---|---|---|")
    for c in selected:
        kw = (c["detail"] or c["name"])[:20]
        L.append(f"| {c['name']} | {c['cat']} | {kw} | {c['source']} |")
    L.append("")

    # 收束：只总结维度分布，不编造具体结论
    cats = [c["cat"] for c in selected]
    L.append("## 写在最后")
    L.append("")
    L.append(
        f"这 {n} 个信号分布在 {len(set(cats))} 个维度上"
        f"（{'、'.join(sorted(set(cats)))}）。"
        f"其中「{max(set(cats), key=cats.count)}」维度出现最密集，"
        "值得优先展开。"
    )
    L.append("")
    L.append("> 本节由模板按维度分布自动生成，不含主观判断。"
             "结论请自行基于上方来源材料提炼。")

    out_path.write_text("\n".join(L), encoding="utf-8")
    print(f"article: {n} signals ({len(refs)} sources) -> {out_path}")
    return out_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("用法: python3 research_to_article.py <research.json> <out.md> [max_trends]")
        raise SystemExit(1)
    research_to_article(Path(sys.argv[1]), Path(sys.argv[2]),
                        int(sys.argv[3]) if len(sys.argv) > 3 else 5)
