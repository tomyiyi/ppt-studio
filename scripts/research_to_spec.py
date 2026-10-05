#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research_to_spec.py -- 三段式研究→spec（gpt-researcher 方法论落地）
====================================================================
借鉴 gpt-researcher（~28k stars）三段式 prompt 链：
  1. 子查询生成：主题 → 3-5 个子查询（覆盖 What/Why/How/数据/案例）
  2. 来源策展：第 15 轮 search_router 统一路由（多后端独立查询并合并）
     → source_trust 打分 → 分级
  3. 报告生成：按可信度加权，输出带 in-text citation 的研究简报 JSON

第 18 轮改动：来源策展从直连 tavily_search/bili_search 改为走 search_router。
- 广度语义：每个启用的后端独立查询、结果合并（research 要的是多视角覆盖，
  与 router.search() 的"首个有产出即停"的 fallback 冗余语义不同）。
- 单个后端异常只 warn 跳过，不中断其他后端（fail-isolated）。
- xhs 后端默认关闭：其 Cookie 登录态已过期（第 13 轮补记），红线要求拿到
  新 Cookie 前不再发真实请求；用 --with-xhs 显式开启。

本脚本做 1+2（确定性部分）；第 3 段的 LLM 撰写由调用方（Agnes，经 brief_writer.py）完成，
输入即本脚本输出的 JSON。

用法：
    python3 scripts/research_to_spec.py "2026秋冬时尚趋势" -o brief.json
    python3 scripts/research_to_spec.py "query" --no-bili        # 只用 Tavily
    python3 scripts/research_to_spec.py "query" --with-xhs       # 额外启用小红书
    python3 scripts/research_to_spec.py "query" --backends tavily,xhs,bili
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_trust import score_sources
from search_router import search as router_search, resolve_backends, BACKENDS

# 子查询模板（What/Why/How/数据/案例五维）
SUBQUERY_TEMPLATES = [
    "{topic} 是什么 / 定义与范围",
    "{topic} 为什么重要 / 驱动因素",
    "{topic} 怎么做 / 方法与实践",
    "{topic} 数据与统计",
    "{topic} 案例与实例",
]

# 默认后端：tavily（英文专业）+ bili（中文社媒，免凭证）。
# xhs 默认关闭——见模块 docstring（Cookie 过期 + 红线禁真实请求）。
DEFAULT_BACKENDS: tuple[str, ...] = ("tavily", "bili")


def gen_subqueries(topic: str, n: int = 5) -> list[str]:
    """确定性子查询生成（模板法；LLM 增强版由 Agnes 在第 3 段做）。"""
    return [t.format(topic=topic) for t in SUBQUERY_TEMPLATES[:n]]


def search_all_backends(query: str, backends: list[str],
                        max_results: int = 5) -> list[dict]:
    """广度语义：每个后端独立查询并合并，单后端异常隔离。

    与 search_router.search(allow_fallback=True) 的"首个有产出即停"不同，
    research 需要多后端视角并存。每条结果标注 backend_used。
    """
    out: list[dict] = []
    for name in backends:
        try:
            res = router_search(query, backends=[name],
                                max_results=max_results, allow_fallback=False)
        except Exception as e:  # noqa: BLE001 -- 单后端失败不阻塞其他后端
            print("[warn] 后端 %s 失败，已跳过: %s" % (name, e), file=sys.stderr)
            continue
        used = res.get("backend_used") or name
        for r in res.get("results", []) or []:
            if not isinstance(r, dict):
                continue
            r = dict(r)
            r["backend_used"] = used
            out.append(r)
    return out


def _to_scorable(r: dict) -> dict:
    """router 归一化结果 -> source_trust 可打分格式。

    published_at 在各后端的 extra 里字段名不同（tavily: published；
    bili: published_at；xhs: 无），逐个回退。
    """
    extra = r.get("extra") or {}
    published = (r.get("published_at") or extra.get("published")
                 or extra.get("published_at") or "")
    return {"url": r.get("url", ""), "title": r.get("title", ""),
            "published_at": published,
            "snippet": r.get("snippet", "") or ""}


def research(topic: str, backends: tuple[str, ...] | list[str] = DEFAULT_BACKENDS,
             per_query: int = 5) -> dict:
    # 未知后端名直接抛 ValueError（fail-fast，不静默吞掉拼写错误）
    chain = resolve_backends(list(backends))
    names = [b.name for b in chain]
    subqueries = gen_subqueries(topic)
    raw: list[dict] = []
    seen_urls: set[str] = set()
    for sq in subqueries:
        for r in search_all_backends(sq, names, per_query):
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                r["subquery"] = sq
                raw.append(r)
    # source_trust 打分 + 分级
    scored = score_sources([_to_scorable(r) for r in raw])
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
        "backends": names,
        "subqueries": subqueries,
        "source_count": len(raw),
        "grade_histogram": by_grade,
        "sources": raw,
        # 给 Agnes 第 3 段的输入提示
        "next_step": "将 sources 按 trust 加权，A/B 级优先引用，D 级弃用，生成带 in-text citation 的简报",
    }


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    backend_names = ", ".join(b.name for b in BACKENDS)
    ap = argparse.ArgumentParser(description="三段式研究→spec（1+2段，走 search_router 统一路由）")
    ap.add_argument("topic")
    ap.add_argument("--backends", default=None,
                    help="逗号分隔的后端名（可选: %s）；默认 tavily,bili" % backend_names)
    ap.add_argument("--no-tavily", action="store_true")
    ap.add_argument("--no-bili", action="store_true")
    ap.add_argument("--with-xhs", action="store_true",
                    help="显式启用小红书后端（需有效 Cookie；默认关闭）")
    ap.add_argument("--per-query", type=int, default=5)
    ap.add_argument("-o", "--output")
    ap.add_argument(
        "--base-dir",
        default=None,
        help="指定基础工作目录 (默认: 当前工作目录)",
    )
    a = ap.parse_args(argv)
    effective_base = (
        Path(a.base_dir).resolve()
        if a.base_dir
        else (Path(base_dir).resolve() if base_dir else Path.cwd().resolve())
    )
    if a.backends:
        backend_list = [s.strip() for s in a.backends.split(",") if s.strip()]
    else:
        backend_list = list(DEFAULT_BACKENDS)
        if a.no_tavily and "tavily" in backend_list:
            backend_list.remove("tavily")
        if a.no_bili and "bili" in backend_list:
            backend_list.remove("bili")
        if a.with_xhs and "xhs" not in backend_list:
            backend_list.append("xhs")
    if not backend_list:
        ap.error("至少启用一个搜索后端")
    brief = research(a.topic, backends=backend_list, per_query=a.per_query)
    out = json.dumps(brief, ensure_ascii=False, indent=2)
    if a.output:
        out_p = Path(a.output)
        out_file = (effective_base / out_p).resolve() if not out_p.is_absolute() else out_p.resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(out, encoding="utf-8")
        print("[ok] %d 来源（后端: %s）→ %s"
              % (brief["source_count"], ",".join(brief["backends"]), out_file))
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
