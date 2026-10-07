#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
封面构图原型体系（源自 ContentForge 4 大构图原型）

把 agnes_design_cover.py 的 10 个散风格收敛为 4 大原型：
每个原型 codified（留白比例/构图/适用场景），select_cover_archetype()
按平台 + 语气 + 标题长度自动推导最佳风格，不再人肉选。

参考：ContentForge 2026-09-03 交接文档 §3《4 大构图原型》
"""

from __future__ import annotations

# ---------------------------------------------------------------- 原型定义
COVER_ARCHETYPES = {
    "SIDE_PROFILE_WIDE": {
        "name": "人物侧置留白型",
        "platform": "wechat",          # 微信公众号横版
        "ratio": "16:9",
        "whitespace": 0.62,            # 左侧留白 62%
        "title_px": 40,
        "desc": "信息分层鲜明，0.3 秒看清痛点与结论。适合深度干货、个人实践指南。",
        "styles": ["article_01", "article_02"],
    },
    "DEEP_GRADIENT_EDITORIAL": {
        "name": "深色渐变纵深型",
        "platform": "xiaohongshu",     # 小红书竖版
        "ratio": "3:4",
        "whitespace": 0.30,
        "title_px": 44,
        "desc": "杂志编辑感，顶部刊头 + 底部双列特性卡片。适合行业分析、硬核教程。",
        "styles": ["cinema_01", "cinema_02"],
    },
    "MINIMAL_HEADLINE_INSIGHT": {
        "name": "极简大字观点型",
        "platform": "wechat",
        "ratio": "16:9",
        "whitespace": 0.55,            # 留白 > 50%
        "title_px": 44,
        "desc": "反直觉强认知冲击，纯观点大字。适合犀利观点、反直觉复盘。",
        "styles": ["swiss_01", "swiss_02"],
    },
    "DIRECT_GAZE_PORTRAIT": {
        "name": "正面对视沉浸型",
        "platform": "xiaohongshu",
        "ratio": "3:4",
        "whitespace": 0.35,
        "title_px": 42,
        "desc": "强眼神接触 + 信任感，上下渐变夹持排版。适合创作者自白、方法论亲授。",
        "styles": ["chinese_01", "chinese_02"],
    },
}

# 风格 -> 原型 反查
STYLE_TO_ARCHETYPE = {
    s: aid
    for aid, a in COVER_ARCHETYPES.items()
    for s in a["styles"]
}
# cyber 系：高饱和科技风，归入深色纵深（备用分支）
STYLE_TO_ARCHETYPE.update({"cyber_01": "DEEP_GRADIENT_EDITORIAL",
                           "cyber_02": "DEEP_GRADIENT_EDITORIAL"})

# 语气 -> 原型倾向
TONE_TO_ARCHETYPE = {
    "analytical": "DEEP_GRADIENT_EDITORIAL",   # 分析型 -> 纵深
    "provocative": "MINIMAL_HEADLINE_INSIGHT",  # 犀利型 -> 极简大字
    "empathetic": "DIRECT_GAZE_PORTRAIT",       # 共情型 -> 对视
    "practical": "SIDE_PROFILE_WIDE",           # 实操型 -> 侧置留白
}


def select_cover_archetype(platform: str = "wechat",
                           tone: str = "practical",
                           title: str = "") -> tuple[str, str]:
    """按平台+语气选原型，返回 (archetype_id, style)。

    平台优先：platform 决定横/竖；语气决定原型；标题超 18 字时
    倾向留白更大的原型（ContentForge 待办 4：字号自适应）。
    """
    platform = (platform or "wechat").lower()
    tone = (tone or "practical").lower()

    # 候选：先按平台过滤
    cands = [aid for aid, a in COVER_ARCHETYPES.items()
             if a["platform"] == platform] or list(COVER_ARCHETYPES)
    # 再按语气
    want = TONE_TO_ARCHETYPE.get(tone)
    aid = want if want in cands else cands[0]
    # 长标题 -> 选同平台留白更大的
    if len(title) > 18:
        cands.sort(key=lambda x: COVER_ARCHETYPES[x]["whitespace"], reverse=True)
        aid = cands[0]
    styles = COVER_ARCHETYPES[aid]["styles"]
    # 短标题用 _01（更张扬），长标题用 _02（更收敛）
    style = styles[0] if len(title) <= 12 else styles[-1]
    return aid, style


def title_font_size(title: str, base_px: int = 44) -> int:
    """标题字号自适应（ContentForge 待办 4 公式）。"""
    n = len(title)
    if n <= 18:
        return base_px
    return max(28, int(base_px - (n - 18) * 1.5))
