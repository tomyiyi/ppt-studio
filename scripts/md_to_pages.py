#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 方法论文章 -> 分页计划（内容驱动生成的最小闭环）

针对"数字方法论"体裁（N条/X步/N层）：`##` 节标题 -> 一页幻灯片标题，
节内列表项 -> 要点；`> ` 核心立场 -> 封面副标题。

用法：
    python3 scripts/md_to_pages.py --md <文章.md> --out <pages.json>
    python3 scripts/md_to_pages.py --md <文章.md> --out <pages.json> --max-bullets 5

输出 pages.json：[{index, title, bullets[], layout}]，layout 按内容类型推导：
- 含"对比"/"vs"/表格 -> compare
- 含"步骤"/"第一步" -> steps
- 默认 -> bullets（一页一观点）
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
H2_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
BULLET_RE = re.compile(r"^(?:\d+[.、]|[-*])\s+(.+)$")
QUOTE_RE = re.compile(r"^>\s+(.+)$", re.MULTILINE)
TABLE_RE = re.compile(r"^\|.+\|$", re.MULTILINE)


def strip_md(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"\*(.+?)\*", r"\1", s)
    s = re.sub(r"`(.+?)`", r"\1", s)
    s = re.sub(r":::\w+", "", s)
    return s.strip()


def infer_layout(section_text: str) -> str:
    t = section_text
    if TABLE_RE.search(t) or "对比" in t or " vs " in t.lower():
        return "compare"
    if re.search(r"第[一二三四五六七八九\d]+步|步骤", t):
        return "steps"
    return "bullets"


def md_to_pages(md_path: Path, max_bullets: int = 5) -> dict:
    raw = md_path.read_text(encoding="utf-8")
    body = FRONTMATTER_RE.sub("", raw).strip()

    m1 = H1_RE.search(body)
    title = strip_md(m1.group(1)) if m1 else md_path.stem

    m2 = QUOTE_RE.search(body)
    subtitle = strip_md(m2.group(1))[:60] if m2 else ""

    # 按 ## 切节
    parts = H2_RE.split(body)
    # parts[0] 是标题前导，之后每两项一组 (节标题, 节正文)
    pages = [{"index": 0, "title": title, "bullets": [subtitle] if subtitle else [],
              "layout": "cover"}]
    for i in range(1, len(parts), 2):
        sec_title = strip_md(parts[i])
        sec_body = parts[i + 1] if i + 1 < len(parts) else ""
        bullets = []
        for line in sec_body.split("\n"):
            bm = BULLET_RE.match(line.strip())
            if bm:
                bullets.append(strip_md(bm.group(1))[:80])
            if len(bullets) >= max_bullets:
                break
        # 无列表项时，取前两句正文
        if not bullets:
            sentences = [s.strip() for s in re.split(r"[。！？\n]", sec_body) if s.strip()]
            bullets = [strip_md(s)[:80] for s in sentences[:3] if len(s) > 8][:max_bullets]
        pages.append({"index": len(pages), "title": sec_title[:40],
                      "bullets": bullets, "layout": infer_layout(sec_body)})
    return {"source": md_path.name, "title": title, "pages": pages}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Markdown -> 分页计划")
    ap.add_argument("--md", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-bullets", type=int, default=5)
    args = ap.parse_args(argv)

    plan = md_to_pages(args.md, args.max_bullets)
    args.out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"标题：{plan['title'][:40]}")
    print(f"分页：{len(plan['pages'])} 页")
    for pg in plan["pages"]:
        print(f"  p{pg['index']} [{pg['layout']}] {pg['title'][:30]} ({len(pg['bullets'])} 要点)")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
