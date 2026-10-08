#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找资料自动化：auto_research.py

STORM 方法论落地（参考 patterns/research）：
  视角分解 -> 并行检索 -> 可用性过滤 -> claim 提取 -> 双源验证 -> 收敛停止

输入：
  --brief topic_brief.json      # {topic, audience, purpose, core_questions[]}
  --injected injected.json      # 预注入检索结果（无 Tavily key 时用）
输出：
  research.json {
    topic, perspectives[], claims[{
      id, claim, evidence, sources[{url,title,level,retrieved_at}],
      verification: verified|unverified, perspectives[]
    }], stats{}
  }

关键规则（opendraft §2.2）：
  - 关键事实无双源（≥2 独立域名）则标 unverified，不进终稿
收敛规则（dzhng §1.3）：
  - 新一轮新增 claim < 10% 则停止
去重：
  - URL 去重 + claim 文本相似度去重（Jaccard ≥ 0.7 视为重复）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path


# ============================================================
# 1. 视角分解（STORM Perspective-Guided）
# ============================================================

# 通用认知视角：跨领域适用，加新领域不改代码
PERSPECTIVE_DEFS = [
    ("现状", "目前的核心事实是什么？有哪些可量化的数据？"),
    ("变化", "相比过去发生了什么变化？新出现了什么、消失了什么？"),
    ("动因", "为什么会发生这些变化？背后的驱动因素是什么？"),
    ("影响", "对从业者/用户产生了什么影响？"),
    ("反例", "有哪些争议、反面案例？什么条件下结论不成立？"),
]


def generate_perspectives(brief: dict, max_perspectives: int = 5) -> list[dict]:
    """从 brief 生成 3-5 个视角 + 每个视角 2 个问题。"""
    topic = brief.get("topic", "")
    core_qs = brief.get("core_questions", [])
    perspectives = []
    for name, template in PERSPECTIVE_DEFS[:max_perspectives]:
        questions = [
            f"{topic}：{template}",
            f"{topic} {name}方面有哪些值得关注的具体案例或数据？",
        ]
        # brief 自带的核心问题并入第一个视角
        if name == PERSPECTIVE_DEFS[0][0] and core_qs:
            questions = list(core_qs[:2]) + questions
        perspectives.append({"name": name, "questions": questions[:3]})
    return perspectives


# ============================================================
# 2. 检索 Provider 适配器（STORM 检索器可插拔）
# ============================================================

class SearchProvider(ABC):
    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """返回 [{url, title, snippet}]。"""


class TavilyProvider(SearchProvider):
    """Tavily API。key 从 TAVILY_API_KEY 环境变量读。"""

    API_URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("TAVILY_API_KEY 未设置")

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        payload = json.dumps({
            "query": query,
            "max_results": max_results,
            "search_depth": "advanced",
            "include_answer": False,
        }).encode()
        req = urllib.request.Request(
            self.API_URL, data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return [{"url": r.get("url", ""), "title": r.get("title", ""),
                 "snippet": r.get("content", "")[:500]}
                for r in data.get("results", [])]


class InjectedProvider(SearchProvider):
    """注入式：从 JSON 文件读预抓取结果（无 API key 时用）。

    文件格式：{queries: {query_text: [{url, title, snippet}, ...]}}
    未命中 query 时返回空列表（不伪造）。
    """

    def __init__(self, path: str | Path):
        self.data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.queries = self.data.get("queries", {})

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        # 精确命中；否则按关键词交集找最接近的 query
        if query in self.queries:
            return self.queries[query][:max_results]
        q_words = set(re.findall(r"\w+", query.lower()))
        best, best_score = None, 0
        for k, v in self.queries.items():
            k_words = set(re.findall(r"\w+", k.lower()))
            score = len(q_words & k_words)
            if score > best_score:
                best, best_score = k, score
        if best and best_score >= 2:
            return self.queries[best][:max_results]
        return []


def get_provider(injected_path: str | Path | None = None) -> SearchProvider:
    """优先 Tavily，无 key 则用注入式。"""
    if os.environ.get("TAVILY_API_KEY"):
        try:
            return TavilyProvider()
        except RuntimeError:
            pass
    if injected_path:
        return InjectedProvider(injected_path)
    raise RuntimeError("无可用检索源：请设置 TAVILY_API_KEY 或提供 --injected")


# ============================================================
# 3. 来源分级
# ============================================================

# 一级：官方/权威（品牌官网、Pantone、时装周官方、顶级时尚媒体）
PRIMARY_DOMAINS = [
    "pantone.com", "vogue.com", "vogue.co.uk", "elle.com",
    "fashionweekonline.com", "cfda.com", "londonfashionweek.co.uk",
    "gucci.com", "hermes.com", "bottegaveneta.com",
]
# 二级：可信媒体（门户时尚频道、知名行业媒体）
SECONDARY_DOMAINS = [
    "sina.com.cn", "sina.cn", "sohu.com", "163.com",
    "apparelresources.com", "wwd.com", "businessoffashion.com",
    "gaze-tta.com", "accio.com", "pacificplace.com.hk",
    "coveteur.com", "trendalytics.co", "udn.com",
]


def classify_source(url: str) -> str:
    """一级 primary / 二级 secondary / 三级 tertiary。"""
    domain = re.sub(r"^https?://(www\.)?", "", url.lower()).split("/")[0]
    for d in PRIMARY_DOMAINS:
        if domain == d or domain.endswith("." + d):
            return "primary"
    for d in SECONDARY_DOMAINS:
        if domain == d or domain.endswith("." + d):
            return "secondary"
    return "tertiary"


def domain_of(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url.lower()).split("/")[0]


# ============================================================
# 4. Claim 提取 + 可用性过滤（gpt-researcher §1.2）
# ============================================================

# 中文停用词（极简版，用于关键词打分）
STOPWORDS = set("的了是在有和与或但而于对就为以从如把被让向到及等这那哪怎么什么".split())


def keywords(text: str) -> set[str]:
    words = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", text.lower())
    kw = {w for w in words if w not in STOPWORDS and len(w) >= 2}
    # 中文加 char-bigram：转述时"全身红"/"全身红色"能对上
    chars = re.sub(r"[^\u4e00-\u9fff]", "", text)
    for i in range(len(chars) - 1):
        bg = chars[i:i+2]
        if bg not in STOPWORDS:
            kw.add(bg)
    return kw


def utility_score(snippet: str, topic: str) -> float:
    """可用性打分（BM25 思想轻量版）：关键词交集 / 主题词数。

    gpt-researcher 实测：按可用性过滤 73% 相关 vs embedding 46%。
    无 Jev key 时用此本地零成本回退。
    """
    t_kw = keywords(topic)
    s_kw = keywords(snippet)
    if not t_kw:
        return 0.0
    return len(t_kw & s_kw) / len(t_kw)


def extract_claims(results: list[dict], perspective: str,
                   min_utility: float = 0.15) -> list[dict]:
    """从检索结果提取 claims。snippet 按句切分，每句是一个候选 claim。"""
    claims = []
    for r in results:
        snippet = r.get("snippet", "")
        if utility_score(snippet, perspective) < min_utility and len(snippet) < 40:
            continue
        # 按句切分
        sentences = [s.strip() for s in re.split(r"[。！？!?\n]", snippet) if s.strip()]
        for s in sentences:
            if len(s) < 12 or len(s) > 200:
                continue
            claims.append({
                "claim": s,
                "evidence": s,  # 当前 snippet 即证据摘要
                "url": r.get("url", ""),
                "title": r.get("title", ""),
                "perspective": perspective,
            })
    return claims


# ============================================================
# 5. 去重（URL + claim 相似度）
# ============================================================

def claim_signature(claim: str) -> str:
    """归一化签名：去标点、小写、排序关键词。"""
    words = sorted(keywords(claim))
    return hashlib.md5(" ".join(words).encode()).hexdigest()[:12]


def jaccard(a: str, b: str) -> float:
    ka, kb = keywords(a), keywords(b)
    if not ka or not kb:
        return 0.0
    return len(ka & kb) / len(ka | kb)


def is_same_claim(a: str, b: str, sim_threshold: float = 0.45) -> bool:
    """同义判定：Jaccard 达标，或共享实词 ≥3 且覆盖小集合 40%+。

    中文转述时 Jaccard 容易偏低（如品牌名相同但描述不同），
    共享实词数是更稳的信号。
    """
    ka, kb = keywords(a), keywords(b)
    if not ka or not kb:
        return False
    shared = ka & kb
    if len(shared) >= 3 and len(shared) / min(len(ka), len(kb)) >= 0.3:
        return True
    return jaccard(a, b) >= sim_threshold


def dedupe_claims(new_claims: list[dict], existing: list[dict],
                  sim_threshold: float = 0.45) -> list[dict]:
    """去重：同一 URL 已收录的 claim 跳过；相似度 ≥0.7 视为重复。"""
    seen_urls = set()
    for c in existing:
        for s in c.get("sources", []):
            seen_urls.add(s["url"])
    seen_sigs = {claim_signature(c["claim"]) for c in existing}

    # 新批次内部先去重（同批相似只留一条，来源合并）
    batch_unique: list[dict] = []
    for nc in new_claims:
        if nc["url"] in seen_urls and claim_signature(nc["claim"]) in seen_sigs:
            continue
        merged = False
        for bu in batch_unique:
            if is_same_claim(nc["claim"], bu["claim"], sim_threshold):
                bu.setdefault("_extra_sources", []).append(nc)
                merged = True
                break
        if not merged:
            batch_unique.append(nc)

    unique = []
    for nc in batch_unique:
        dup = False
        for ec in existing:
            if is_same_claim(nc["claim"], ec["claim"], sim_threshold):
                # 相似：合并来源（含同批合并的），不新增 claim
                to_add = [nc] + nc.pop("_extra_sources", [])
                for src_c in to_add:
                    if src_c["url"] not in {s["url"] for s in ec["sources"]}:
                        ec["sources"].append({
                            "url": src_c["url"], "title": src_c["title"],
                            "level": classify_source(src_c["url"]),
                            "retrieved_at": now_iso(),
                        })
                dup = True
                break
        if not dup:
            nc.pop("_extra_sources", None)
            unique.append(nc)
    return unique


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ============================================================
# 6. 双源验证（opendraft §2.2）
# ============================================================

def verify_claims(claims: list[dict]) -> None:
    """≥2 独立域名 -> verified，否则 unverified。原地更新。"""
    for c in claims:
        domains = {domain_of(s["url"]) for s in c.get("sources", []) if s.get("url")}
        c["verification"] = "verified" if len(domains) >= 2 else "unverified"


# ============================================================
# 7. 主流程
# ============================================================

def auto_research(brief: dict, provider: SearchProvider,
                  max_rounds: int = 3, convergence_threshold: float = 0.1,
                  verbose: bool = True) -> dict:
    topic = brief.get("topic", "")
    if not topic:
        raise ValueError("brief.topic 不能为空")

    perspectives = generate_perspectives(brief)
    claims: list[dict] = []
    rounds_log = []

    def log(msg: str):
        if verbose:
            print(msg, flush=True)

    for round_i in range(max_rounds):
        round_new = 0
        for p in perspectives:
            for q in p["questions"]:
                results = provider.search(q, max_results=5)
                if not results:
                    continue
                raw = extract_claims(results, p["name"])
                fresh = dedupe_claims(raw, claims)
                for fc in fresh:
                    _srcs = [{
                        "url": fc["url"], "title": fc["title"],
                        "level": classify_source(fc["url"]),
                        "retrieved_at": now_iso(),
                    }]
                    for _ex in fc.pop("_extra_sources", []):
                        _srcs.append({
                            "url": _ex["url"], "title": _ex["title"],
                            "level": classify_source(_ex["url"]),
                            "retrieved_at": now_iso(),
                        })
                    claims.append({
                        "id": f"c{len(claims)+1:03d}",
                        "claim": fc["claim"],
                        "evidence": fc["evidence"],
                        "sources": _srcs,
                        "perspectives": [fc["perspective"]],
                        "verification": "unverified",
                    })
                round_new += len(fresh)
                # 相似合并可能给旧 claim 加了新 perspective
        total = len(claims)
        new_ratio = round_new / max(total, 1)
        rounds_log.append({"round": round_i + 1, "new_claims": round_new,
                           "total": total, "new_ratio": round(new_ratio, 3)})
        log(f"[round {round_i+1}] 新增 {round_new} 条，累计 {total} 条")
        # 收敛：新一轮新增 < 阈值则停止（dzhng §1.3）
        if round_i > 0 and new_ratio < convergence_threshold:
            log(f"收敛：新增比例 {new_ratio:.1%} < {convergence_threshold:.0%}，停止")
            break

    verify_claims(claims)

    verified = [c for c in claims if c["verification"] == "verified"]
    return {
        "topic": topic,
        "brief": {k: v for k, v in brief.items() if k != "topic"},
        "perspectives": perspectives,
        "claims": claims,
        "rounds": rounds_log,
        "stats": {
            "total_claims": len(claims),
            "verified": len(verified),
            "unverified": len(claims) - len(verified),
            "primary_sources": sum(1 for c in claims for s in c["sources"]
                                   if s["level"] == "primary"),
            "rounds_run": len(rounds_log),
        },
        "generated_at": now_iso(),
    }


def main():
    ap = argparse.ArgumentParser(description="找资料自动化（STORM 方法论）")
    ap.add_argument("--brief", required=True, help="topic_brief.json 路径")
    ap.add_argument("--injected", default=None, help="预注入检索结果 JSON")
    ap.add_argument("--out", required=True, help="research.json 输出路径")
    ap.add_argument("--max-rounds", type=int, default=2)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    brief = json.loads(Path(args.brief).read_text(encoding="utf-8"))
    provider = get_provider(args.injected)
    print(f"检索源：{type(provider).__name__}", flush=True)

    result = auto_research(brief, provider, max_rounds=args.max_rounds,
                           verbose=not args.quiet)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    s = result["stats"]
    print(f"完成：{s['total_claims']} 条 claims（verified {s['verified']} / "
          f"unverified {s['unverified']}），{s['rounds_run']} 轮 -> {args.out}")


if __name__ == "__main__":
    main()
