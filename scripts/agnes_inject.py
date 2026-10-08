#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agnes-studio 设计资产 -> ppt-studio 可消费的 agnes_tokens.json。

读取：
- poster_font_recipes.json: 3 套字体配方（典雅宋/势能黑/诗意楷）
- poster_grand_rules.json: 硬指标（留白/字阶/间距）
- learned_poster_rules.json: 版式规则 + 配色策略
- copy_templates.json: 主题 hooks（封面副标题用）

输出：scripts/agnes_tokens.json
"""
from __future__ import annotations

import json
from pathlib import Path

AGNES_DATA = Path("/Volumes/3TB_DATA/05-开发项目/agnes-studio-work/data")
OUT = Path("/Volumes/3TB_DATA/05-开发项目/ppt-studio/scripts/agnes_tokens.json")


def load(name: str):
    p = AGNES_DATA / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def parse_font_stack(font_str: str) -> list[str]:
    """'Songti.ttc / STSong / 思源宋体' -> ['Songti SC', 'STSong', 'Noto Serif SC', 'serif']"""
    # 映射表：agnes 字体名 -> CSS font-family
    mapping = {
        "Songti.ttc": "Songti SC",
        "STSong": "STSong",
        "思源宋体": "Noto Serif SC",
        "思源黑": "Noto Sans SC",
        "SmileySans-Oblique": "SmileySans",
        "LXGWWenKai": "LXGWWenKai",
        "PingFang Light": "PingFang SC",
        "PingFang SC": "PingFang SC",
        "Bodoni 72": "Bodoni 72",
        "Didot": "Didot",
        "Baskerville": "Baskerville",
        "Alibaba-PuHuiTi-Heavy": "Alibaba PuHuiTi",
    }
    parts = [p.strip() for p in font_str.replace(" / ", "/").split("/")]
    out = []
    for p in parts:
        # 取映射或原名
        mapped = mapping.get(p, p)
        if mapped not in out:
            out.append(mapped)
    # 补 generic
    return out


def build_tokens() -> dict:
    tokens = {
        "source": "agnes-studio-work",
        "version": "2026-10-08",
        "fonts": {},
        "layout": {},
        "cover_rules": [],
        "palette_strategies": [],
    }

    # 1. 字体配方
    recipes = load("poster_font_recipes.json")
    if recipes:
        mood_map = {
            "典雅宋": "gaoding",  # 高定/品牌/时尚
            "势能黑": "dashi",    # 大气/电影/科技
            "诗意楷": "wenyi",    # 文艺/治愈
        }
        for r in recipes.get("recipes", []):
            name = r.get("name", "")
            mood = None
            for k, v in mood_map.items():
                if k in name:
                    mood = v
                    break
            if not mood:
                continue
            cn_disp = r.get("cn_display", {})
            cn_body = r.get("cn_body", {})
            lat_disp = r.get("latin_display", {})
            tokens["fonts"][mood] = {
                "name": name,
                "cn_display": parse_font_stack(cn_disp.get("font", "")) + ["serif" if "宋" in name else "sans-serif"],
                "cn_body": parse_font_stack(cn_body.get("font", "")) + ["sans-serif"],
                "latin_display": parse_font_stack(lat_disp.get("font", "")) + ["serif"],
                "display_size": cn_disp.get("size", ""),
                "display_tracking": r.get("composition_micro", {}).get("cn_tracking", "0.06em")
                    if isinstance(r.get("composition_micro"), dict) else "0.06em",
                "layout_hint": r.get("layout", ""),
                "avoid": r.get("avoid", []),
            }
        # composition_micro 是顶层的
        micro = recipes.get("composition_micro", {})
        tokens["fonts"]["_micro"] = micro

    # 2. 版式硬指标
    grand = load("poster_grand_rules.json")
    if grand:
        ht = grand.get("hard_targets", {})
        ns = ht.get("negative_space_ratio", {})
        ts = ht.get("type_scale_hero_to_micro", {})
        tokens["layout"] = {
            "negative_space": {
                "min": ns.get("min", 0.35),
                "sweet": ns.get("sweet", 0.45),
                "max": ns.get("max", 0.6),
            },
            "type_scale": {
                "min": ts.get("min", 8),
                "sweet": ts.get("sweet", 10),
                "max": ts.get("max", 16),
            },
            "spacing_rhythm": ht.get("spacing_rhythm_px", [8, 16, 24, 32, 48, 64, 96]),
        }

    # 3. 封面规则 + 配色策略
    learned = load("learned_poster_rules.json")
    if isinstance(learned, list):
        for item in learned:
            if item.get("rule"):
                tokens["cover_rules"].append(item["rule"])
                if "palette_bias" in item:
                    tokens["palette_strategies"].extend(item["palette_bias"])
            elif item.get("rules"):
                tokens["cover_rules"].extend(item["rules"])
    tokens["palette_strategies"] = sorted(set(tokens["palette_strategies"]))

    # 4. copy themes（封面用）：主题名 + 完整词库（title_a/title_b/latin/slogan）
    copy = load("copy_templates.json")
    if copy:
        themes = copy.get("themes", {})
        tokens["copy_themes"] = list(themes.keys())
        tokens["copy_vocab"] = themes
        tokens["copy_rules"] = copy.get("rules", {})

    return tokens


def main():
    tokens = build_tokens()
    OUT.write_text(json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"  fonts: {list(tokens['fonts'].keys())}")
    print(f"  layout keys: {list(tokens['layout'].keys())}")
    print(f"  cover_rules: {len(tokens['cover_rules'])}")
    print(f"  palette_strategies: {tokens['palette_strategies']}")


if __name__ == "__main__":
    main()
