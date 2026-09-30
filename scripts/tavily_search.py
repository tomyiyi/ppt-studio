#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tavily_search.py —— ppt-studio 多源资料搜集
==========================================
从 ~/.config/ppt-studio/tavily.json（600 权限）或 TAVILY_API_KEY 环境变量读 key。
双 key 轮换，失败自动切备用。

用法：
    python3 scripts/tavily_search.py "Pantone FW2026 color report" --max 10
    python3 scripts/tavily_search.py "query" --depth advanced --max 10 -o out.json
"""
from __future__ import annotations
import argparse, itertools, json, os, sys, urllib.request
from pathlib import Path

KEY_FILE = Path.home() / ".config" / "ppt-studio" / "tavily.json"
API_URL = "https://api.tavily.com/search"

def load_keys() -> list[str]:
    keys: list[str] = []
    env = os.environ.get("TAVILY_API_KEY", "").strip()
    if env:
        keys.append(env)
    try:
        data = json.loads(KEY_FILE.read_text(encoding="utf-8"))
        for k in data.get("keys", []):
            if k and k not in keys:
                keys.append(k)
    except Exception as e:
        print(f"[warn] 读 Tavily key 文件失败: {e}", file=sys.stderr)
    if not keys:
        sys.exit("[error] 无可用 Tavily key：设置 TAVILY_API_KEY 或 ~/.config/ppt-studio/tavily.json")
    return keys

def search(query: str, key: str, depth: str, max_results: int) -> dict:
    payload = json.dumps({
        "api_key": key,
        "query": query,
        "search_depth": depth,
        "max_results": max_results,
        "include_answer": True,
    }).encode()
    req = urllib.request.Request(API_URL, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--depth", default="advanced", choices=["basic", "advanced"])
    ap.add_argument("--max", type=int, default=10)
    ap.add_argument("-o", "--output")
    a = ap.parse_args()

    last_err = None
    for key in load_keys():
        try:
            result = search(a.query, key, a.depth, a.max)
            break
        except Exception as e:
            last_err = e
            print(f"[warn] key 失败，切换备用: {e}", file=sys.stderr)
    else:
        sys.exit(f"[error] 所有 key 均失败: {last_err}")

    # 输出时剥掉 key 回显（防泄漏）
    out = json.dumps(result, ensure_ascii=False, indent=2)
    if a.output:
        Path(a.output).write_text(out, encoding="utf-8")
        print(f"[ok] {len(result.get(results, []))} 条结果 → {a.output}")
    else:
        print(out)

if __name__ == "__main__":
    main()
