#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research_to_spec.py -- 三段式研究→spec（gpt-researcher 方法论落地）
====================================================================
借鉴 gpt-researcher（~28k stars）三段式 prompt 链：
  1. 子查询生成：主题 → 3-5 个子查询（覆盖 What/Why/How/数据/案例）
  2. 来源策展：Tavily（英文专业）+ B站（中文社媒）双源搜索 → source_trust 打分 → 分级
  3. 报告生成：按可信度加权，输出带 in-text citation 的研究简报 JSON

本脚本做 1+2（确定性部分）；第 3 段的 LLM 撰写由调用方（Agnes）完成，
输入即本脚本输出的 JSON。

用法：
    python3 scripts/research_to_spec.py "2026秋冬时尚趋势" -o brief.json
    python3 scripts/research_to_spec.py "query" --no-bili  # 只用 Tavily
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_trust import score_sources

# 子查询模板（What/Why/How/数据/案例五维）
SUBQUERY_TEMPLATES = [
    "{topic} 是什么 / 定义与范围",
    "{topic} 为什么重要 / 驱动因素",
    "{topic} 怎么做 / 方法与实践",
    "{topic} 数据与统计",
    "{topic} 案例与实例",
]


def gen_subqueries(topic: str, n: int = 5) -> list[str]:
    """确定性子查询生成（模板法；LLM 增强版由 Agnes 在第 3 段做）。"""
    return [t.format(topic=topic) for t in SUBQUERY_TEMPLATES[:n]]


def search_tavily(query: str, max_results: int = 5) -> list[dict]:
    """调 tavily_search；失败返回 []（不阻塞 B站）。"""
    try:
        from tavily_search import search as _tsearch, load_keys
        keys = load_keys()
        last = None
        for k in keys:
            try:
                r = _tsearch(query, k, "advanced", max_results)
                last = r
                break
            except Exception as e:
                last = e
        if isinstance(last, dict):
            out = []
            for x in last.get("results", [])[:max_results]:
                out.append({
                    "title": x.get("title", ""),
                    "url": x.get("url", ""),
                    "published_at": x.get("published_date", ""),
                    "snippet": (x.get("content", "") or "")[:300],
                    "source": "tavily",
                })
            return out
    except SystemExit:
        pass
    except Exception as e:
        print("[warn] Tavily 搜索失败: %s" % e, file=sys.stderr)
    return []


def search_bili(query: str, max_results: int = 5) -> list[dict]:
    try:
        from bili_search import search as _bsearch
        return _bsearch(query, max_results)
    except Exception as e:
        print("[warn] B站搜索失败: %s" % e, file=sys.stderr)
        return []


def research(topic: str, use_tavily: bool = True, use_bili: bool = True,
             per_query: int = 5) -> dict:
    subqueries = gen_subqueries(topic)
    raw: list[dict] = []
    seen_urls: set[str] = set()
    for sq in subqueries:
        if use_tavily:
            for r in search_tavily(sq, per_query):
                if r["url"] and r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    r["subquery"] = sq
                    raw.append(r)
        if use_bili:
            for r in search_bili(sq, per_query):
                if r["url"] and r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    r["subquery"] = sq
                    raw.append(r)
    # source_trust 打分 + 分级
    scored = score_sources([
        {"url": r["url"], "title": r["title"],
         "published_at": r.get("published_at", ""),
         "snippet": r.get("snippet", r.get("description", ""))}
        for r in raw
    ])
    for r, s in zip(raw, scored):
        r["trust"] = s["trust"]
        r["grade"] = s["grade"]
        r["trust_reasons"] = s["trust_reasons"]
    # 按 trust 降序
    raw.sort(key=lambda x: x.get("trust", 0), reverse=True)
    by_grade: dict[str, int] = {}
    for r in raw:
        by_grade[r["grade"]] = by_grade.get(r["grade"], 0) + 1
    return {
        "topic": topic,
        "subqueries": subqueries,
        "source_count": len(raw),
        "grade_histogram": by_grade,
        "sources": raw,
        # 给 Agnes 第 3 段的输入提示
        "next_step": "将 sources 按 trust 加权，A/B 级优先引用，D 级弃用，生成带 in-text citation 的简报",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="三段式研究→spec（1+2段）")
    ap.add_argument("topic")
    ap.add_argument("--no-tavily", action="store_true")
    ap.add_argument("--no-bili", action="store_true")
    ap.add_argument("--per-query", type=int, default=5)
    ap.add_argument("-o", "--output")
    a = ap.parse_args()
    brief = research(a.topic, use_tavily=not a.no_tavily,
                     use_bili=not a.no_bili, per_query=a.per_query)
    out = json.dumps(brief, ensure_ascii=False, indent=2)
    if a.output:
        Path(a.output).write_text(out, encoding="utf-8")
        print("[ok] %d 来源 → %s" % (brief["source_count"], a.output))
    else:
        print(out)


if __name__ == "__main__":
    main()
