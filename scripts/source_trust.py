#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
source_trust.py -- 来源可信度打分（阶段 1：来源审计的脚本初筛）
=====================================================================
借鉴 azdoherty/personal-os 的 source-trust 技能算法骨架（自写实现）：
  域名先验 x 时效乘子 + 印证加分 → trust(0-100) → A/B/C/D 分级

用法：
    echo '[{"url": "...", "title": "...", "published_at": "2026-09-01"}]' \
      | python3 scripts/source_trust.py
    python3 scripts/source_trust.py -i sources.json -o scored.json

输入字段（JSON 数组）：
    url           必填
    title         可选（用于关键词印证）
    published_at  可选，ISO 日期 "2026-09-01"（缺失则跳过时效乘子）
    snippet       可选，内容摘要（用于关键词印证）

输出：每条追加 trust (0-100)、trust_reasons[]、grade (A/B/C/D)。
分级口径：>=80 A（一手） / >=60 B（专业媒体） / >=40 C（二手转述） / <40 D（弱来源）
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
DOMAIN_TRUST_FILE = REPO_ROOT / "assets" / "domain-trust.json"
DEFAULT_PRIOR = 40
NEUTRAL = 40


def load_domain_trust() -> dict:
    try:
        return json.loads(DOMAIN_TRUST_FILE.read_text(encoding="utf-8"))
    except OSError:
        return {}


def domain_prior(url: str, table: dict) -> tuple:
    """域名先验分；子域名回退父域名；未知 40。返回 (分, 理由)。"""
    try:
        host = urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return DEFAULT_PRIOR, "URL 解析失败，默认 40"
    if not host:
        return DEFAULT_PRIOR, "无域名，默认 40"
    parts = host.split(".")
    for i in range(len(parts) - 1):
        cand = ".".join(parts[i:])
        if cand in table:
            return table[cand], "域名先验 %s=%s" % (cand, table[cand])
    return DEFAULT_PRIOR, "未知域名 %s，默认 40" % host


def recency_multiplier(published_at) -> tuple:
    """时效乘子：<=6个月 x1.0，线性衰减到 3 年 x0.5。"""
    if not published_at:
        return 1.0, "无发布日期，跳过时效"
    try:
        pub = datetime.fromisoformat(str(published_at)[:10]).date()
    except ValueError:
        return 1.0, "日期格式无效，跳过时效"
    months = (date.today() - pub).days / 30.44
    if months <= 6:
        return 1.0, "6 个月内，时效 x1.0"
    if months >= 36:
        return 0.5, "超过 3 年，时效 x0.5"
    m = 1.0 - (months - 6) / 30 * 0.5
    return round(m, 3), "%.0f 个月前，时效 x%.2f" % (months, m)


def keywords(text: str) -> set:
    """粗糙关键词提取：英文词>=4字母 + 中文2字以上连续片段。"""
    out = set()
    stop = {"with", "from", "that", "this", "have", "will", "fashion", "trend",
            "autumn", "winter", "fall", "report"}
    for w in re.findall(r"[A-Za-z]{4,}", text or ""):
        wl = w.lower()
        if wl not in stop:
            out.add(wl)
    for w in re.findall(r"[\u4e00-\u9fff]{2,}", text or ""):
        out.add(w)
    return out


def corroboration_bonus(sources: list) -> dict:
    """印证加分：某条的关键词出现在 >=2 个其他来源 → +10。返回 idx→(分,理由)。"""
    kw_list = [keywords((s.get("title") or "") + " " + (s.get("snippet") or ""))
               for s in sources]
    res = {}
    for i, kws in enumerate(kw_list):
        if not kws:
            res[i] = (0, "无关键词可印证")
            continue
        hit = sum(1 for j, other in enumerate(kw_list)
                  if i != j and len(kws & other) >= 2)
        if hit >= 2:
            res[i] = (10, "关键词被 %d 个其他来源印证，+10" % hit)
        else:
            res[i] = (0, "印证不足 2 个来源")
    return res


def score_sources(sources: list) -> list:
    table = load_domain_trust()
    cor = corroboration_bonus(sources)
    out = []
    for i, s in enumerate(sources):
        reasons = []
        prior, r1 = domain_prior(s.get("url", ""), table)
        reasons.append(r1)
        mult, r2 = recency_multiplier(s.get("published_at"))
        reasons.append(r2)
        # 时效乘子围绕中性点 40 应用，避免老但可信的来源崩盘；
        # 未知域名（默认 40）+ 过时则直接衰减，可跌破 40 到 D 级
        if prior == DEFAULT_PRIOR and mult < 1.0:
            score = prior * mult
        else:
            score = NEUTRAL + (prior - NEUTRAL) * mult
        bonus, r3 = cor[i]
        reasons.append(r3)
        score += bonus
        trust = max(0, min(100, round(score)))
        grade = "A" if trust >= 80 else "B" if trust >= 60 else "C" if trust >= 40 else "D"
        reasons.append("综合 %d 分 → %s 级" % (trust, grade))
        out.append({**s, "trust": trust, "trust_reasons": reasons, "grade": grade})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="来源可信度打分 → A/B/C/D")
    ap.add_argument("-i", "--input", help="输入 JSON 文件（缺省读 stdin）")
    ap.add_argument("-o", "--output", help="输出 JSON 文件（缺省 stdout）")
    a = ap.parse_args()
    raw = Path(a.input).read_text(encoding="utf-8") if a.input else sys.stdin.read()
    sources = json.loads(raw)
    if isinstance(sources, dict):
        sources = [sources]
    result = score_sources(sources)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if a.output:
        Path(a.output).write_text(text, encoding="utf-8")
        print("[ok] %d 条来源已打分 → %s" % (len(result), a.output))
    else:
        print(text)


if __name__ == "__main__":
    main()
