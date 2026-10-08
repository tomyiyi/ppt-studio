#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agnes 配色策略 -> ppt-studio 强调色。

agnes palette_strategies:
- ink+gold: 墨底 + 金强调（高定/品牌）
- mono+accent: 单色 + 一个强调色（通用）
- low-sat-field+one-pop: 低饱和底 + 一个跳色（时尚）

映射到具体色值（从 agnes 实际海报提取的金 #C4A57C）。
"""
from __future__ import annotations

import json
from pathlib import Path

TOKENS = Path(__file__).parent / "agnes_tokens.json"

# 策略 -> 强调色
STRATEGY_ACCENTS = {
    "ink+gold": "#C4A57C",      # agnes 印章金
    "mono+accent": "#B4232A",   # agnes 印章红（牛血红）
    "low-sat-field+one-pop": "#C4A57C",
}

# mood -> 首选策略
MOOD_STRATEGY = {
    "gaoding": "ink+gold",      # 高定：墨+金
    "dashi": "mono+accent",      # 大气：单色+红
    "wenyi": "low-sat-field+one-pop",
}


def get_accent_color(mood: str = "") -> str:
    """agnes 配色策略驱动的强调色。"""
    strategy = MOOD_STRATEGY.get(mood, "mono+accent")
    # 验证策略在 agnes tokens 里
    try:
        tokens = json.loads(TOKENS.read_text(encoding="utf-8"))
        strategies = tokens.get("palette_strategies", [])
        if strategy not in strategies:
            strategy = strategies[0] if strategies else "mono+accent"
    except Exception:
        pass
    return STRATEGY_ACCENTS.get(strategy, "#B4232A")


if __name__ == "__main__":
    for m in ["gaoding", "dashi", "wenyi", ""]:
        print(m or "default", "->", get_accent_color(m))
