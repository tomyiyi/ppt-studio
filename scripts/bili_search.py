#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bili_search.py -- B站视频搜索（中文社媒用户层）
================================================
Agent-Reach 评估结论的落地：B站官方搜索 API 免登录可用，
只需 buvid3 设备指纹 + Referer 头（实测绕过 412）。

与 scripts/tavily_search.py 形成多源印证：
  Tavily = 英文专业媒体层，B站 = 中文社媒用户层。

输出统一 JSON，可直接喂给 source_trust.py 打分：
    python3 scripts/bili_search.py "2026时尚趋势" --max 10
    python3 scripts/bili_search.py "query" -o out.json
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.bilibili.com/x/web-interface/search/type"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def search(query: str, max_results: int = 10) -> list[dict]:
    buvid = str(uuid.uuid4())
    out: list[dict] = []
    page, per = 1, min(max_results, 50)
    while len(out) < max_results:
        qs = urllib.parse.urlencode({
            "search_type": "video", "keyword": query,
            "page": page, "page_size": per,
        })
        req = urllib.request.Request(API + "?" + qs, headers={
            "User-Agent": UA,
            "Referer": "https://search.bilibili.com/",
            "Origin": "https://search.bilibili.com",
            "Cookie": "buvid3=%s;" % buvid,
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode())
        except Exception as e:
            print("[warn] B站 API 请求失败: %s" % e, file=sys.stderr)
            break
        if data.get("code") != 0:
            print("[warn] B站返回 code=%s msg=%s" % (data.get("code"), data.get("message")),
                  file=sys.stderr)
            break
        results = (data.get("data") or {}).get("result") or []
        if not results:
            break
        for v in results:
            title = re.sub(r"<[^>]+>", "", v.get("title") or "")
            desc = re.sub(r"<[^>]+>", "", v.get("description") or "")
            bvid = v.get("bvid") or ""
            pub = v.get("pubdate")
            out.append({
                "title": title,
                "url": "https://www.bilibili.com/video/%s" % bvid if bvid else "",
                "author": v.get("author"),
                "play": v.get("play"),
                "danmaku": v.get("danmaku"),
                "duration": v.get("duration"),
                "published_at": (datetime.fromtimestamp(pub, tz=timezone.utc)
                                 .strftime("%Y-%m-%d") if pub else ""),
                "description": desc[:200],
                "source": "bilibili",
            })
            if len(out) >= max_results:
                break
        page += 1
        time.sleep(0.5)  # 礼貌间隔
    return out


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    ap = argparse.ArgumentParser(description="B站视频搜索（中文社媒层）")
    ap.add_argument("query")
    ap.add_argument("--max", type=int, default=10)
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
    results = search(a.query, a.max)
    payload = {"query": a.query, "source": "bilibili",
               "count": len(results), "results": results}
    out = json.dumps(payload, ensure_ascii=False, indent=2)
    if a.output:
        out_p = Path(a.output)
        out_file = (effective_base / out_p).resolve() if not out_p.is_absolute() else out_p.resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(out, encoding="utf-8")
        print("[ok] %d 条结果 → %s" % (len(results), out_file))
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
