#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prompt 安全拦截模块（源自 ContentForge 白瓷肌标准）

核心原理 —— 否定词反噬（Negative Prompt Leakage）：
扩散模型的 tokenizer 会解析 `no blush` 中的 `blush`，在降噪初期向红色潜空间
漂移，导致"写不要等于写要"。因此：
1. 严禁在 prompt 中出现腮红/发红类词汇，无论是否带否定前缀；
2. 用正向单色调标准替代否定描述。

参考：ContentForge 2026-09-03 交接文档 §2《白瓷肌标准与注意力泄露防御》
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------- 违禁词
# ContentForge 原版正则 + 中文变体 + 常见扩写
BANNED_RED_TOKENS = re.compile(
    r"\b("
    r"blush|rouge|rosy|redness|red[\s_\-]*cheeks?|red[\s_\-]*face|"
    r"flushed[\s_\-]*cheeks?|crimson[\s_\-]*cheeks?|"
    r"sunburn|red[\s_\-]*blotches?"
    r")\b"
    r"|(腮红|酒糟鼻|发红|泛红|脸红|红血丝)",
    re.IGNORECASE,
)

# 否定词反噬模式：否定前缀 + 颜色词 = 反而注入该语义
_NEG_WORDS = r"no|without|avoid|never|don't|do not|doesn't|not|none of|free of|less|minus|无|不要|避免|禁止|去掉|去除|别"
NEGATIVE_LEAKAGE = re.compile(
    rf"\b({_NEG_WORDS})\b[\s\W]{{0,25}}"
    r"(blush|rouge|rosy|redness|red[\s_\-]*cheeks?|red|腮红|发红|泛红|红色)",
    re.IGNORECASE,
)

# 正向替代标准（ContentForge 白瓷肌）
POSITIVE_SKIN_STANDARD = (
    "monochrome pale ivory skin, translucent natural porcelain complexion, "
    "neutral undertone, clean skin texture, soft rim light"
)

# 中文乱码高风险：纯 AI 生图对中文字符渲染不可靠，提示走排版层
CJK_IN_PROMPT = re.compile(r"[\u4e00-\u9fff]{4,}")


def check_prompt_safety(prompt: str) -> tuple[bool, list[str]]:
    """检查 prompt 是否安全。返回 (是否通过, 问题列表)。"""
    issues: list[str] = []
    if not prompt or not prompt.strip():
        return False, ["prompt 为空"]

    m = BANNED_RED_TOKENS.search(prompt)
    if m:
        issues.append(
            f"[违禁词] 命中 `{m.group(0)}`：腮红/发红类词汇在 diffusion 模型中会污染面部，"
            f"请删除并改用正向描述 `{POSITIVE_SKIN_STANDARD[:45]}...`"
        )

    m2 = NEGATIVE_LEAKAGE.search(prompt)
    if m2 and not m:  # 已报违禁词的不重复报
        issues.append(
            f"[否定反噬] `{m2.group(0)[:40]}...`：否定词 `{m2.group(1)}` 不会抑制语义，"
            "反而向模型注入该颜色语义。请删掉整句，改用正向白瓷肌描述。"
        )

    if CJK_IN_PROMPT.search(prompt):
        issues.append(
            "[中文乱码风险] prompt 含连续中文：AI 生图对中文字符渲染不可靠，"
            "文字请走 SVG/HTML 排版层叠加，不要进生图 prompt。"
        )

    return (not issues, issues)


def assert_prompt_safe(prompt: str) -> None:
    """不安全则抛 ValueError（供 generate() fail-fast 调用）。"""
    ok, issues = check_prompt_safety(prompt)
    if not ok:
        raise ValueError("[Prompt安全拦截] " + " | ".join(issues))
