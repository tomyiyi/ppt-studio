#!/usr/bin/env python3
"""S15-C（主控 2026-10-16 批准 S13 待决项 A）：散文段落 → evidence 的确定性抽取。

背景：`plan_narrative.build()` 只从列表项 / 表格行取证据，纯散文正文一句都取不到，
于是文章→deck 路径上每个 claim 页都判 `[W-07] 缺 evidence`（run2 实测 6 条）。
本模块把散文正文按句切开、**逐字**登记为证据，补上这条通路。

红线（本模块的全部设计约束，任何一条被破坏都应当日返工）：
1) 只搬运不改写：`evidence.text` 必须是原文里的连续片段，不生成、不摘要、不换词、不截断。
2) 必须可回指：`source` 记到 markdown 的具体行号，由 W-19 的 `resolve_source` 校验，指错即判红。
3) 不无中生有：抽不出合格句子就返回空列表，让 W-07 继续判红。
   S13 里执行者不肯做这件事的理由就是"塞散文进 evidence 等于喂内容给门禁"——
   所以本模块的自检（test_evidence_from_prose.py）专门有一条反向查：
   纯自指/纯套话的段落必须仍然抽不出证据，W-07 必须仍然亮。
4) 不新增也不放松任何判据数字：`kind` 沿用 `plan_narrative.kind_of`；
   `baseline` 只在原文**字面**含参照值（"从 X 改成 Y"这类）时才填，填不出来就留 None，
   让 W-12 照常判红。run2 的附录页本来就有 2 条 W-12，说明这条线在存量路径上就是咬人的。

零第三方依赖（只用 re），零 LLM 调用，输出完全确定（同输入同输出，无随机、无时间戳）。
"""
from __future__ import annotations

import re

# 句子终止符：中文全角为主，兼容半角；保留终止符本身，保证"逐字"
SENT_SPLIT_RE = re.compile(r"(?<=[。！？；])")
# 段末引用括号：（example.com、example.org）——只在整串像域名/URL 时才当引用剥掉
CITATION_TAIL_RE = re.compile(r"[（(]([^（）()]{2,})[）)]\s*$")
CITATION_BODY_RE = re.compile(r"^[A-Za-z0-9._\-/&%?#:、,，;；\s]+$")
# 自指句：说的是"这篇文章"而不是"这件事"，不构成证据
META_RE = re.compile(r"^(本篇|本文|本节|本文档|下文|上文|下面|接下来)|见附录|更多未经验证")
# 列表 / 表格 / 标题行不属于散文（存量路径已各自处理）
NON_PROSE_RE = re.compile(r"^\s*(?:[-*+]\s|\||#{1,6}\s|>|\*\*\*|---|$)")

# 参照值：原文里必须字面出现被比较的那个量，否则不填 baseline
BASELINE_PATTERNS = (
    r"从([^，。；、]{1,24}?)(?:改到|改成|改为|提高到|提升至|提升到|降低到|降至|升至|减少到|压缩到|压缩至|缩短到|变成|到)",
    r"比([^，。；、]{1,18}?)(?:更|高|低|快|慢|多|少|长|短)",
    r"(?:高于|低于|较)([^，。；、]{1,18}?)(?:的)?[，。；]",
)

MAX_ITEMS = 3          # 与写作 skill 的 evidence_points(≤3) 同数：只收紧，不放宽
MIN_SENT_CHARS = 12    # 短于 12 字的片段承载不了一条证据（只收紧，不放宽）


def split_sentences(paragraph: str) -> list[str]:
    """按中文终止标点切句，保留标点，不改动任何字符。"""
    parts = [s.strip() for s in SENT_SPLIT_RE.split(paragraph)]
    return [p for p in parts if p]


def split_citation(sentence: str) -> tuple[str, list[str]]:
    """剥掉句末的引用括号，返回（正文, 引用列表）。不像引用就原样留着。"""
    m = CITATION_TAIL_RE.search(sentence)
    if not m or not CITATION_BODY_RE.match(m.group(1).strip()):
        return sentence, []
    body = [c.strip() for c in re.split(r"[、,，;；]", m.group(1)) if c.strip()]
    return sentence[:m.start()].rstrip(), body


def extract_baseline(sentence: str) -> str | None:
    """只在原文字面含参照值时返回它；否则 None（宁可让 W-12 判红，不编）。"""
    for pat in BASELINE_PATTERNS:
        m = re.search(pat, sentence)
        if m:
            ref = m.group(1).strip()
            return ref or None
    return None


def is_evidence(sentence: str) -> bool:
    """自指句 / 过短句 / 非散文行都不算证据。"""
    if NON_PROSE_RE.match(sentence):
        return False
    if META_RE.search(sentence):
        return False
    core, _ = split_citation(sentence)
    core = re.sub(r"[\s。！？；、，,]", "", core)
    return len(core) >= MIN_SENT_CHARS


def extract(lines: list[str], start_line: int, md_name: str,
            kind_of, strip_md) -> list[dict]:
    """把一个节的原文行 → evidence 列表。

    lines / start_line 沿用 plan_narrative.split_sections 的口径：
    start_line 是该节 ## 标题在文件里的 1-based 行号，lines[0] 即它的下一行，
    所以 lines[i] 的行号 = start_line + 1 + i —— 与存量 bullet 路径同一算法。
    """
    out: list[dict] = []

    def add_paragraph(lineno: int, paragraph: str) -> None:
        for sent in split_sentences(paragraph):
            if not is_evidence(sent):
                continue
            core, _cites = split_citation(sent)
            out.append({
                "kind": kind_of(core),
                "text": strip_md(core),
                "baseline": extract_baseline(core),
                "source": f"{md_name}#L{lineno}",
                "provenance": "prose",
            })
            if len(out) >= MAX_ITEMS:
                return

    for pos, raw in enumerate(lines):
        # 本仓正文约定"一段一行"（write_article 即如此产出），所以逐行即逐段，
        # 不跨行合并 —— 这样 source 行号一定指得准，不会把第二句记到第一行上。
        stripped = raw.strip()
        if stripped and not NON_PROSE_RE.match(raw):
            add_paragraph(start_line + 1 + pos, stripped)
        if len(out) >= MAX_ITEMS:
            break
    return out[:MAX_ITEMS]


if __name__ == "__main__":  # 手工验一条：python3 scripts/evidence_from_prose.py <md> <start_line>
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from plan_narrative import kind_of, strip_md
    p = Path(sys.argv[1])
    ln = int(sys.argv[2])
    txt = p.read_text(encoding="utf-8").split("\n")
    print(json.dumps(extract(txt[ln:ln + 6], ln, p.name, kind_of, strip_md),
                     ensure_ascii=False, indent=2))
