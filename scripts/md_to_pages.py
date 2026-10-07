#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 方法论文章 -> 分页计划（专题设计规范 v1）

核心变化：
1. 叙事风格判定先行：整篇文章先定风格（listicle/how-to/myth-busting/framework/story-arc），
   风格决定整套页面结构，而非逐页猜版式。
2. 版式按"阅读功能"定义：statement（金句）/fact（大数字）/quote（引用）/section（章节）
   /cover/bullets/compare/steps/closing。
3. 溢出即拆分：绝不缩小硬塞。

用法：
    python3 scripts/md_to_pages.py --md <文章.md> --out <pages.json>
    python3 scripts/md_to_pages.py --md <文章.md> --out <pages.json> --max-bullets 5
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    from narrative_rewrite import visual_concept, build_image_prompt
    HAS_NR = True
except ImportError:
    HAS_NR = False

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


# === 专题设计规范 v1：叙事风格判定 ===

NARRATIVE_STYLES = {
    "listicle": "钩子页 -> 每条一页 -> 收束页",
    "how-to": "问题页 -> 步骤页 -> 结果页",
    "myth-busting": "误区页 -> 真相页",
    "framework": "框架总览 -> 每组件一页",
    "story-arc": "Before -> 历程 -> After + CTA",
}


def detect_narrative_style(title: str, body: str) -> str:
    """判定整篇文章的叙事风格。风格决定整套页面结构，而非逐页猜。"""
    t = title + "\n" + body[:2000]
    if re.search(r"\d+\s*条|\d+\s*个|\d+\s*大|\d+\s*种", t):
        return "listicle"
    if re.search(r"\d+\s*层|\d+\s*大结构|三层|架构|框架", t):
        return "framework"
    if re.search(r"步骤|实操|教程|指南|第一步|怎么做|如何", t):
        return "how-to"
    if re.search(r"误区|真相|辟谣|被高估|被低估|其实|并不是", t):
        return "myth-busting"
    if re.search(r"故事|历程|从.+到.+", t):
        return "story-arc"
    h2_count = len(re.findall(r"^##\s+", body, re.MULTILINE))
    return "listicle" if h2_count >= 4 else "framework"


def detect_reading_function(sec_title: str, sec_body: str, bullets: list) -> str:
    """判定单页的阅读功能（版式）。按阅读功能定义版式，而非元素数量。"""
    t = sec_title + " " + sec_body[:500]
    # 章节页：引子 / 收束
    if re.search(r"写在前面|引言|前言", sec_title):
        return "section"
    if re.search(r"总结|写在最后|结语|协同", sec_title):
        return "closing"
    # 金句页：短标题 + 单一观点断言
    if len(bullets) <= 1 and len(sec_title) <= 20:
        if re.search(r"是|要|必须|关键|本质|核心|记住", sec_title):
            return "statement"
    # 大数字页：数字必须在标题中突出（如"41% 失败率"），正文中的数字不算
    if re.search(r"\d+\s*[%％倍]", sec_title):
        return "fact"
    # 对比页
    if TABLE_RE.search(sec_body) or "对比" in t or " vs " in t.lower():
        return "compare"
    # 步骤页
    if re.search(r"第[一二三四五六七八九\d]+步|步骤", t):
        return "steps"
    return "bullets"


def needs_split(bullets: list, max_bullets: int = 4) -> bool:
    """Slidev 铁律：溢出就拆页，绝不缩小硬塞。"""
    if len(bullets) > max_bullets:
        return True
    return sum(len(b) for b in bullets) > 200


def infer_layout(section_text: str) -> str:
    """保留兼容：旧调用走新逻辑。"""
    return detect_reading_function("", section_text, [])


def page_image_prompt(title: str, layout: str, bullets: list = None) -> str:
    """6段式内容感知生图 prompt（Midjourney 公式 + visual_concept）。
    返回 positive prompt；negative 走独立通道（由生图阶段处理）。
    """
    if HAS_NR:
        concept = visual_concept(title, bullets or [], layout)
        positive, _negative = build_image_prompt(concept, title, bullets or [])
        return positive
    # 回退：旧通用模板
    base = ("dark tech editorial background, deep navy black gradient, "
            "abstract geometric depth, subtle grid, cinematic lighting, "
            "minimalist, no text, no words, no letters, no people")
    return base


def md_to_pages(md_path: Path, max_bullets: int = 5) -> dict:
    raw = md_path.read_text(encoding="utf-8")
    body = FRONTMATTER_RE.sub("", raw).strip()

    m1 = H1_RE.search(body)
    title = strip_md(m1.group(1)) if m1 else md_path.stem

    m2 = QUOTE_RE.search(body)
    subtitle = strip_md(m2.group(1))[:60] if m2 else ""

    # 叙事风格判定先行
    narrative_style = detect_narrative_style(title, body)

    # 按 ## 切节
    parts = H2_RE.split(body)
    pages = [{"index": 0, "title": title, "bullets": [subtitle] if subtitle else [],
              "layout": "cover", "image_prompt": page_image_prompt(title, "cover", [subtitle] if subtitle else [])}]
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
        lay = detect_reading_function(sec_title, sec_body, bullets)
        # 标题收紧：取冒号前的核心（不超过16字），避免槽位溢出
        _short = re.split(r"[：:]", sec_title)[0].strip()[:16]
        base_page = {"index": len(pages), "title": _short,
                     "bullets": bullets, "layout": lay,
                     "image_prompt": page_image_prompt(sec_title, lay, bullets)}
        # 溢出拆分：绝不缩小硬塞
        if needs_split(bullets):
            for j in range(0, len(bullets), 4):
                chunk = bullets[j:j + 4]
                sp = base_page.copy()
                sp["bullets"] = chunk
                sp["index"] = len(pages)
                if j > 0:
                    sp["title"] = _short[:14] + "（续）"
                pages.append(sp)
        else:
            pages.append(base_page)
    return {"source": md_path.name, "title": title,
            "narrative_style": narrative_style, "pages": pages}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Markdown -> 分页计划（专题设计规范 v1）")
    ap.add_argument("--md", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-bullets", type=int, default=5)
    args = ap.parse_args(argv)

    plan = md_to_pages(args.md, args.max_bullets)
    args.out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"标题：{plan['title'][:40]}")
    print(f"叙事风格：{plan['narrative_style']}（{NARRATIVE_STYLES[plan['narrative_style']]}）")
    print(f"分页：{len(plan['pages'])} 页")
    for pg in plan["pages"]:
        print(f"  p{pg['index']} [{pg['layout']}] {pg['title'][:30]} ({len(pg['bullets'])} 要点)")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
