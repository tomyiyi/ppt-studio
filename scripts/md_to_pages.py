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
    # 数据表 vs 对比页：3列以上或4行以上是数据表，用 table 真表格
    if TABLE_RE.search(sec_body):
        _tbl_lines = [l for l in sec_body.split("\n") if l.strip().startswith("|") and "---" not in l.strip()]
        if _tbl_lines:
            _ncols = len(_tbl_lines[0].strip("|").split("|"))
            _nrows = len(_tbl_lines) - 1  # 去表头
            if _ncols >= 3 or _nrows >= 4:
                return "table"
        return "compare"
    if "对比" in t or " vs " in t.lower():
        return "compare"
    # 步骤页
    if re.search(r"第[一二三四五六七八九\d]+步|步骤", t):
        return "steps"
    return "bullets"


def needs_split(bullets: list, max_bullets: int = 4, layout: str = "") -> bool:
    """Slidev 铁律：溢出就拆页，绝不缩小硬塞。"""
    # table 版式：表头+7行内单页，真表格比拆页好
    _is_tbl = any(b.strip().startswith("|") for b in bullets)
    _limit = 8 if (layout == "table" or _is_tbl) else max_bullets
    if len(bullets) > _limit:
        return True
    return sum(len(b) for b in bullets) > 200


# === 标题质量闸门 ===
#
# 旧实现用 `re.split(r"[：:]", sec_title)[0].strip()[:16]` 硬截断，
# 会把"确定性：不是更准，而是可被追溯"砍成"确定性"——正是
# patterns/writing/rewrite_slide_copy.md 规则1 明令禁止的坏输出。
#
# 现在**不用规则去"写"标题，只用规则去"筛"**：
# 好标题原样保留；有主副结构的取主句；实在不行的标记 needs_review，
# 交给人/LLM 判断。规则层不再越权创作。

TITLE_MAX = 20          # 超过这个长度且无法断句才提示
_BAD_TITLE_TAILERS = ("方法", "方式, ", "概述", "简介", "总结", "解析")


def title_quality(title: str) -> dict:
    """评估一个章节标题能不能直接当页面标题用。

    返回 {"ok": bool, "reason": str, "suggested": str | None}
    """
    t = (title or "").strip()
    if not t:
        return {"ok": False, "reason": "空标题", "suggested": None}

    # 章节序号开头：准则一 / 第一层 / 3.2 —— 直接当标题必然是坏输出
    if re.match(r"^(准则|原则|要点|章节|第[一二三四五六七八九十\d]+[层条步点])\s*[一-鿿\d]*\s*$", t):
        return {"ok": False, "reason": "只有章节编号，没有观点",
                "suggested": f"{t}（需补充观点句）"}

    # 主体过短：截断后大概率变成半句
    if len(t) <= 3 and not re.search(r"[：:]", t):
        return {"ok": False, "reason": f"标题过短（{len(t)}字），可能是被截断的半句",
                "suggested": None}

    # 有主副结构：冒号前是主句，冒号后是解释——主句通常可独立成立
    if re.search(r"[：:]", t):
        head = re.split(r"[：:]", t, maxsplit=1)[0].strip()
        if len(head) >= 4 and len(head) <= TITLE_MAX:
            return {"ok": True, "reason": "有主副结构，取主句", "suggested": head}

    if len(t) > TITLE_MAX:
        return {"ok": False, "reason": f"超长（{len(t)}字 > {TITLE_MAX}），需断句",
                "suggested": None}

    return {"ok": True, "reason": "可直接使用", "suggested": t}


def resolve_title(sec_title: str) -> tuple[str, list]:
    """把章节标题解析成页面标题 + 待审标记列表。

    返回 (title, review_flags)
    """
    q = title_quality(sec_title)
    if q["ok"] and q["suggested"]:
        return q["suggested"], []
    # 不合格：原样保留（不截断、不编造），并标记 needs_review
    return (sec_title or "").strip(), [q["reason"]]


def infer_layout(section_text: str) -> str:
    """保留兼容：旧调用走新逻辑。"""
    return detect_reading_function("", section_text, [])


# 叙事风格 -> 收尾页策略。让 narrative_style 真正被消费，而不只是打印。
CLOSING_BY_STYLE = {
    "listicle": "要点回顾",
    "how-to": "下一步行动",
    "myth-busting": "误区澄清",
    "framework": "框架总览",
    "story-arc": "行动号召",
}


def page_image_prompt(title: str, layout: str, bullets: list = None) -> str:
    """6段式内容感知生图 prompt（Midjourney 公式 + visual_concept）。
    返回 positive prompt；negative 走独立通道（由生图阶段处理）。
    """
    if HAS_NR:
        concept = visual_concept(title, bullets or [], layout)
        positive, _negative = build_image_prompt(concept, title, bullets or [])
        return positive
    # 回退：不猜领域，用中性底图（旧的"一律深色科技"是退化的开始）
    return ("clean editorial background, soft directional lighting, "
            "generous whitespace, minimalist, no text, no words, no letters, no people")


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
    review_flags: list[dict] = []   # 收集需要人工/LLM 复核的标题
    pages = [{"index": 0, "title": title, "bullets": [subtitle] if subtitle else [],
              "layout": "cover", "needs_review": [],
              "image_prompt": page_image_prompt(title, "cover", [subtitle] if subtitle else [])}]
    for i in range(1, len(parts), 2):
        sec_title = strip_md(parts[i])
        sec_body = parts[i + 1] if i + 1 < len(parts) else ""
        bullets = []
        for line in sec_body.split("\n"):
            ls = line.strip()
            bm = BULLET_RE.match(ls)
            if bm:
                bullets.append(strip_md(bm.group(1))[:80])
            elif ls.startswith("|") and "---" not in ls:
                # 表格行：完整收集，不受 max_bullets 截断（丢一行就是丢数据）
                # 表格的分页由 needs_split 统一处理
                bullets.append(ls[:100])
                continue
            if len(bullets) >= max_bullets:
                break
        # 无列表项时，取前两句正文
        if not bullets:
            sentences = [s.strip() for s in re.split(r"[。！？\n]", sec_body) if s.strip()]
            bullets = [strip_md(s)[:80] for s in sentences[:3] if len(s) > 8][:max_bullets]
        lay = detect_reading_function(sec_title, sec_body, bullets)
        # 标题：规则层只做「筛」，不做「写」——不截断成半句，不合格就标记待审
        _title, _flags = resolve_title(sec_title)
        if _flags:
            review_flags.append({"page": len(pages), "source_title": sec_title,
                                 "issue": _flags[0]})
        base_page = {"index": len(pages), "title": _title,
                     "bullets": bullets, "layout": lay,
                     "needs_review": _flags,
                     "image_prompt": page_image_prompt(sec_title, lay, bullets)}
        # 溢出拆分：绝不缩小硬塞
        if needs_split(bullets, layout=lay):
            for j in range(0, len(bullets), 4):
                chunk = bullets[j:j + 4]
                sp = base_page.copy()
                sp["bullets"] = chunk
                sp["index"] = len(pages)
                if j > 0:
                    sp["title"] = (_title[:14] + "（续）") if _title else "（续）"
                pages.append(sp)
        else:
            pages.append(base_page)

    # 让 narrative_style 真正被消费：给出该风格下的收尾页建议
    plan = {"source": md_path.name, "title": title,
            "narrative_style": narrative_style,
            "closing_hint": CLOSING_BY_STYLE.get(narrative_style, "收束"),
            "pages": pages}
    if review_flags:
        plan["review_flags"] = review_flags
    return plan


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
        mark = " ⚠" if pg.get("needs_review") else ""
        print(f"  p{pg['index']} [{pg['layout']}]{mark} {pg['title'][:30]} ({len(pg['bullets'])} 要点)")
    # 标题质量待审清单：规则层筛出来的问题，交人/LLM 复核
    rf = plan.get("review_flags") or []
    if rf:
        print(f"\n⚠ {len(rf)} 个标题需人工复核（规则不做改写，只标记）：")
        for f in rf:
            print(f"  p{f['page']}「{f['source_title'][:24]}」→ {f['issue']}")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
