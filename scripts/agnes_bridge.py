#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agnes-studio 对接桥：读取设计资产，供 ppt-studio 使用。

对接点：
1. 设计 tokens（配色、字阶）-> spec_lock
2. 海报规则（learned_poster_rules）-> 封面原型选择
3. 字体配方（poster_font_recipes）-> 中文字体渲染
"""
from __future__ import annotations

import json
from pathlib import Path

AGNES_ROOT = Path("/Volumes/3TB_DATA/05-开发项目/agnes-studio-work")
DATA = AGNES_ROOT / "data"


def load_json(name: str) -> dict:
    p = DATA / name
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def get_design_tokens() -> dict:
    """设计 tokens：配色 + 字阶。"""
    # 从 learned_poster_rules 提取
    rules = load_json("learned_poster_rules.json")
    tokens = {
        "colors": {},
        "typography": {},
        "source": "agnes-studio",
    }
    # 尝试多种可能的键
    if isinstance(rules, dict):
        for k in ["colors", "palette", "color_scheme"]:
            if k in rules:
                tokens["colors"] = rules[k]
                break
        for k in ["typography", "fonts", "type_scale"]:
            if k in rules:
                tokens["typography"] = rules[k]
                break
    return tokens


def get_font_recipes() -> dict:
    """中文字体配方。"""
    return load_json("poster_font_recipes.json")


def get_cover_rules() -> dict:
    """封面设计规则。"""
    rules = load_json("learned_poster_rules.json")
    if isinstance(rules, dict):
        return rules.get("cover", rules.get("covers", {}))
    return {}


def get_copy_templates() -> dict:
    """文案模板。"""
    return load_json("copy_templates.json")


if __name__ == "__main__":
    print("design_tokens keys:", list(get_design_tokens().keys()))
    print("font_recipes type:", type(get_font_recipes()))
    print("cover_rules type:", type(get_cover_rules()))
