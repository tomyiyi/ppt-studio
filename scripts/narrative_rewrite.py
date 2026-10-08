#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视觉概念提炼：页面内容 -> 6段式生图 prompt

依据 patterns/visual/visual_concept.md 落地，但**只在确定性安全的范围内工作**。

设计原则（重要）
----------------
1. **不猜内容**。只用显式关键词映射，映射表按"多字词优先"匹配，
   避免单字歧义（旧版用「红」「灰」等单字，中文里极易误伤）。
2. **匹配不到就诚实降级**。subject 返回 None，由调用方决定用哪种底图，
   而不是塞一个"总归对得上"的抽象词。
3. **不跨领域抢命中**。时尚等专属映射需先通过领域门槛，
   否则不启用。
4. 排版计算（字号、行宽）属确定性范畴，可以用规则；
   "画什么"属创作判断，规则只给候选，不给结论。
"""
from __future__ import annotations


# === 领域门槛 ===
# 只有页面里出现这些词，才认为该领域成立，进而启用对应的风格/隐喻。
DOMAIN_GATES = {
    "fashion": ["时尚", "趋势", "穿搭", "秀场", "runway", "fashion", "trend",
                "时装", "服饰", "面料", "廓形", "当季", "秋冬", "春夏"],
    "tech": ["AI", "模型", "算法", "架构", "代码", "部署", "服务", "数据",
             "系统", "平台", "接口", "智能体", "agent", "model", "api"],
    "finance": ["增长", "收入", "成本", "利润", "融资", "估值", "营收", "毛利",
                "revenue", "profit", "cost", "margin"],
}


def detect_domain(text: str) -> str | None:
    """判定页面属于哪个领域。命中不了返回 None（不猜）。"""
    if not text:
        return None
    tl = text.lower()
    for dom, gates in DOMAIN_GATES.items():
        if any(g.lower() in tl for g in gates):
            return dom
    return None


# === 视觉隐喻映射（通用，跨领域）===
VISUAL_METAPHORS = {
    "第一性原理": "peeling layers revealing glowing core",
    "本质": "peeling layers revealing glowing core",
    "核心": "concentric circles converging to center",
    "对抗": "stress test chamber with warning lights",
    "审查": "magnifying glass over circuit board",
    "测试": "stress test chamber with warning lights",
    "校验": "precision caliper measuring golden standard",
    "确定性": "precision caliper measuring golden standard",
    "零信任": "fortress gate with multiple checkpoints",
    "安全": "fortress gate with multiple checkpoints",
    "记忆": "library archive with glowing threads",
    "沉淀": "library archive with glowing threads",
    "对比": "split diptych with contrasting sides",
    "对照": "split diptych with contrasting sides",
    "流程": "flowing luminous timeline path",
    "步骤": "flowing luminous timeline path",
    "协同": "interlocking gears in motion",
    "闭环": "continuous loop of light",
    "演进": "layered geological strata",
    "权衡": "balanced scales on a fulcrum",
}

# 时尚专属（需 fashion 门槛通过才生效，避免技术页被单字误伤）
FASHION_METAPHORS = {
    "皮草": "luxurious faux fur texture",
    "蕾丝": "delicate lace fabric macro",
    "皮革": "glossy leather surface detail",
    "格纹": "heritage plaid pattern flat lay",
    "廓形": "dramatic oversized silhouette",
    "西装": "sharp tailored suit on hanger",
    "外套": "oversized coat silhouette",
    "面料": "textile weave macro detail",
    "红": "crimson fabric draped in wind",
    "棕": "rich brown leather texture",
    "灰": "grey wool texture close-up",
}

_ALL_METAPHORS = {**VISUAL_METAPHORS, **FASHION_METAPHORS}
# 按 key 长度降序，保证「第一性原理」先于「本质」匹配
_METAPHOR_KEYS = sorted(_ALL_METAPHORS.keys(), key=len, reverse=True)


def match_visual_concept(slide_title: str, bullets: list | None = None) -> dict | None:
    """匹配视觉隐喻。返回 None 表示没有可靠匹配（调用方应走中性底图）。"""
    text = (slide_title + " " + " ".join((bullets or [])[:2])).strip()
    if not text:
        return None

    domain = detect_domain(text)
    for kw in _METAPHOR_KEYS:
        if kw not in text:
            continue
        # 时尚词必须在 fashion 领域内才生效
        if kw in FASHION_METAPHORS and domain != "fashion":
            continue
        return {"subject": _ALL_METAPHORS[kw], "domain": domain, "matched": kw}
    return None


ACTION_BY_LAYOUT = {
    "cover": "hero wide composition",
    "bullets": "soft ambient presence",
    "compare": "symmetric balanced tension",
    "steps": "forward flowing motion",
    "statement": "centered spotlight focus",
    "fact": "bold numeric graphic",
    "quote": "editorial pull-quote backdrop",
    "section": "chapter transition",
    "closing": "horizon resolution",
}


def visual_concept(slide_title: str, bullets: list | None = None,
                    layout: str = "bullets") -> dict:
    """返回 concept dict。**subject / environment 可能为 None**，调用方必须处理。"""
    text = (slide_title + " " + " ".join((bullets or [])[:2])).strip()
    m = match_visual_concept(slide_title, bullets)
    domain = m["domain"] if m else detect_domain(text)

    if m is None:
        return {
            "subject": None, "action": ACTION_BY_LAYOUT.get(layout, "soft ambient presence"),
            "environment": None, "domain": domain, "matched": None,
        }
    return {
        "subject": m["subject"],
        "action": ACTION_BY_LAYOUT.get(layout, "soft ambient presence"),
        "environment": ENV_BY_DOMAIN.get(domain, "deep navy black void with subtle grid"),
        "domain": domain, "matched": m["matched"],
    }


# === 风格 / 光照 / 环境：按领域，不再按单字关键词 ===

STYLE_BY_DOMAIN = {
    "fashion": "fashion editorial photography on a dark set, low-key lighting, high fashion magazine aesthetic",
    "tech": "dark tech editorial, deep navy black gradient, cinematic lighting, minimalist",
    "finance": "editorial report style, dark composition, muted professional palette",
    None: "dark editorial background, low-key directional lighting, generous negative space, minimalist",
}
LIGHTING_BY_DOMAIN = {
    "fashion": "low-key diffused studio lighting, deep shadows",
    "tech": "dramatic rim lighting",
    "finance": "dim even lighting, deep shadows",
    None: "rim lighting from the right, left side in shadow",
}
ENV_BY_DOMAIN = {
    "fashion": "charcoal studio backdrop",
    "tech": "deep navy black void with subtle grid",
    "finance": "graphite gradient backdrop",
    None: "deep graphite gradient backdrop",
}

NEGATIVE_PROMPT = ("text, words, letters, watermark, logo, people, face, "
                   "blurry, low quality, cluttered, oversaturated")

# 这些图是文字底板（白色文字直接压在图上），亮底会被遮罩压成一片黑，等于白生图。
# 实测中性/时尚/财经三档环境词都偏亮（文字带亮度 0.48~0.76，遮罩要压到 0.62~0.76），
# 所以统一在 prompt 末尾钉死暗调，让底图在遮罩之后仍然看得见。
DARK_PLATE = ("dark low-key backdrop, deep shadows, underexposed left half for text overlay, "
              "overall luminance below 0.25")


def get_style_suffix(slide_title: str, bullets: list | None = None) -> str:
    """按领域选风格。传空串时返回**中性风格**，不再错误地回落科技风。"""
    domain = detect_domain((slide_title or "") + " " + " ".join(bullets or []))
    return STYLE_BY_DOMAIN.get(domain, STYLE_BY_DOMAIN[None])


def build_image_prompt(concept: dict, slide_title: str = "",
                       bullets: list | None = None) -> tuple[str, str]:
    """6段式：[Subject]+[Action]+[Environment]+[Lighting]+[Style]+[Quality]

    领域判定优先用显式传入的 slide_title/bullets；传空时退回 concept 里记录的
    domain，再不行就是中性风格——**不猜、不伪装成知道**。
    """
    text = (slide_title or "") + " " + " ".join(bullets or [])
    domain = detect_domain(text) if text.strip() else concept.get("domain")

    style = STYLE_BY_DOMAIN.get(domain, STYLE_BY_DOMAIN[None])
    env = concept.get("environment") or ENV_BY_DOMAIN.get(domain, ENV_BY_DOMAIN[None])
    lighting = LIGHTING_BY_DOMAIN.get(domain, LIGHTING_BY_DOMAIN[None])
    # Subject 缺失时用排版元素兜底，避免塞一个可能跑题的具象主体
    subject = concept.get("subject") or "subtle abstract geometric depth"

    positive = ", ".join([
        subject,
        concept.get("action", "soft ambient presence"),
        env, lighting, style,
        "highly detailed, professional quality",
        DARK_PLATE,
    ])
    return positive, NEGATIVE_PROMPT


if __name__ == "__main__":
    print("=== 视觉隐喻匹配（关键：单字是否还误伤）===")
    cases = [
        ("2026 秋冬时尚趋势", ["皮草与格纹同步回潮", "廓形外套替代收腰"]),
        ("增长确定性", ["置信度提升"]),
        ("网络安全护城河", ["多层检查点"]),
        ("三层架构：感知层自主决策", ["工具层统一总线"]),
        ("随手记", ["今天天气不错"]),
        ("红色预警", ["核心指标告警"]),
    ]
    for t, b in cases:
        c = visual_concept(t, b, "bullets")
        flag = "无匹配 -> 中性底图" if c["subject"] is None else f"命中[{c['matched']}]"
        print(f"  {t[:18]:<20} domain={str(c['domain']):<8} {flag}")

    print()
    print("=== 风格判定：传参 vs 不传参（不应再错落科技风）===")
    c1 = visual_concept("2026 秋冬时尚趋势", ["皮草"], "cover")
    p_with, _ = build_image_prompt(c1, "2026 秋冬时尚趋势", ["皮草"])
    p_without, _ = build_image_prompt(c1)
    print("  传参  :", p_with[:92])
    print("  不传参:", p_without[:92])
