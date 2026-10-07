#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""叙事重写：extract_claims -> rewrite_slide_copy -> extract_hook

基于 patterns/writing/ 的三个 pattern 的规则版实现。
确定性、离线、快速。LLM 版作为 P1 增强。
"""
from __future__ import annotations

import re


def extract_claims(section_title: str, section_body: str) -> dict:
    """从章节提取核心主张。"""
    # claim: 取标题冒号前的核心，或第一句
    claim = re.split(r"[：:]", section_title)[0].strip()
    if len(claim) > 20:
        # 取正文第一句
        sentences = [s.strip() for s in re.split(r"[。！？\n]", section_body) if s.strip()]
        claim = sentences[0][:20] if sentences else claim[:20]

    # evidence: 取列表项或关键句，清洗连接词
    evidence = []
    for line in section_body.split("\n"):
        line = line.strip()
        m = re.match(r"^(?:\d+[.、]|[-*])\s+(.+)$", line)
        if m:
            ev = re.sub(r"^(首先|其次|另外|此外|最后|第一|第二|第三)[，、]", "", m.group(1).strip())
            ev = re.sub(r"\*\*(.+?)\*\*", r"\1", ev)
            if len(ev) > 8:
                evidence.append(ev[:30])
        if len(evidence) >= 3:
            break

    # hook_candidate: 找最有力的句子（含数字/对比/反差）
    hook_candidate = ""
    sentences = [s.strip() for s in re.split(r"[。！？]", section_body) if len(s.strip()) > 10]
    for s in sentences:
        if re.search(r"\d+[%％倍]|不是.*而是|与其.*不如", s):
            hook_candidate = s[:30]
            break
    if not hook_candidate and sentences:
        hook_candidate = sentences[0][:30]

    return {"claim": claim, "evidence": evidence[:3], "hook_candidate": hook_candidate}


def rewrite_slide_copy(claim: str, evidence: list, layout: str = "bullets") -> dict:
    """改写成演示型文案。"""
    # slide_title: 观点句，12字以内
    slide_title = claim[:12]

    # bullets: 短句，20字以内，保留数字和动词
    bullets = []
    for ev in evidence[:4]:
        # 去修饰，保留核心
        short = re.sub(r"(非常|特别|十分|很|比较|有点)", "", ev)
        short = short.strip("，,。")
        if len(short) > 20:
            # 保留数字部分，截断
            m = re.search(r"(.{0,15}\d+[%％倍]?[^，,]*)", short)
            short = m.group(1) if m else short[:20]
        bullets.append(short)

    # takeaway: 记忆点
    takeaway = claim[:15]

    return {"slide_title": slide_title, "bullets": bullets, "takeaway": takeaway}


def extract_hook(title: str, claims: list) -> dict:
    """提炼封面钩子。"""
    # hook: 从标题提炼断言
    base = re.split(r"[：:——]", title)[0].strip()
    # 尝试制造认知冲突
    hook = base[:12]

    # subhook: 回答"跟我有什么关系"
    subhook = ""
    if claims:
        # 取第一个 claim 的核心
        subhook = claims[0][:20] if isinstance(claims[0], str) else claims[0].get("claim", "")[:20]

    return {"hook": hook, "subhook": subhook}


# === 视觉概念 ===

VISUAL_METAPHORS = {
    "第一性原理": "peeling layers revealing glowing core",
    "本质": "peeling layers revealing glowing core",
    "核心": "concentric circles converging to center",
    "对抗": "stress test chamber with red warning lights",
    "审查": "magnifying glass over circuit board",
    "测试": "stress test chamber with red warning lights",
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
}



FASHION_METAPHORS = {
    "红": "crimson red fabric flowing in wind",
    "red": "crimson red fabric flowing in wind",
    "灰": "grey wool texture close-up",
    "棕": "rich brown leather texture",
    "西装": "sharp tailored suit on hanger",
    "套装": "sharp tailored suit on hanger",
    "皮草": "luxurious faux fur texture",
    "蕾丝": "delicate lace fabric macro",
    "lace": "delicate lace fabric macro",
    "皮革": "glossy leather jacket detail",
    "leather": "glossy leather jacket detail",
    "格纹": "heritage plaid pattern flat lay",
    "外套": "oversized coat silhouette",
    "靴": "knee-high boots still life",
    "廓形": "dramatic oversized silhouette",
}


def visual_concept(slide_title: str, bullets: list, layout: str = "bullets") -> dict:
    """从页面内容提炼视觉概念（6段式前三段）。"""
    text = slide_title + " " + " ".join(bullets[:2])

    subject = "abstract geometric depth"  # 默认
    # 时尚主题优先查时尚映射
    for kw, metaphor in FASHION_METAPHORS.items():
        if kw.lower() in text.lower():
            subject = metaphor
            break
    else:
        for kw, metaphor in VISUAL_METAPHORS.items():
            if kw in text:
                subject = metaphor
                break

    # action: 根据版式
    action_map = {
        "cover": "hero wide composition",
        "bullets": "soft ambient presence",
        "compare": "symmetric balanced tension",
        "steps": "forward flowing motion",
        "statement": "centered spotlight focus",
        "section": "chapter transition",
        "closing": "horizon resolution",
    }
    action = action_map.get(layout, "soft ambient presence")

    environment = "deep navy black void with subtle grid"

    return {"subject": subject, "action": action, "environment": environment}


# === 6段式 Prompt 生成 ===

STYLE_SUFFIX_TECH = "dark tech editorial, deep navy black gradient, cinematic lighting, minimalist"
STYLE_SUFFIX_FASHION = "fashion editorial photography, elegant studio lighting, high fashion magazine aesthetic"
QUALITY_SUFFIX = "highly detailed, professional photography quality"


def get_style_suffix(slide_title: str, bullets: list) -> str:
    """按主题选择风格。"""
    text = slide_title + " " + " ".join(bullets[:2])
    fashion_kw = ["时尚", "趋势", "fashion", "trend", "穿搭", "秀场", "runway"]
    if any(kw.lower() in text.lower() for kw in fashion_kw):
        return STYLE_SUFFIX_FASHION
    return STYLE_SUFFIX_TECH
NEGATIVE_PROMPT = "text, words, letters, watermark, logo, people, face, blurry, low quality"


def build_image_prompt(concept: dict, slide_title: str = "", bullets: list = None) -> tuple[str, str]:
    """6段式：[Subject]+[Action]+[Environment]+[Lighting]+[Style]+[Quality]"""
    style = get_style_suffix(slide_title, bullets or [])
    # 时尚主题的环境也调整
    env = concept["environment"]
    if style == STYLE_SUFFIX_FASHION:
        env = "elegant neutral studio backdrop"
        lighting = "soft diffused studio lighting"
    else:
        lighting = "dramatic rim lighting"
    positive = ", ".join([
        concept["subject"],      # Subject
        concept["action"],       # Action
        env,                     # Environment
        lighting,                # Lighting
        style,                   # Style（按主题锁定）
        QUALITY_SUFFIX,          # Quality
    ])
    return positive, NEGATIVE_PROMPT


if __name__ == "__main__":
    # 自测
    c = extract_claims("准则一｜第一性原理：AI 的自信是机制层面的必然",
                       "AI 的自信不是 bug，是机制必然。\n- RLHF 训练偏置：人类偏好自信的回答\n- 模型缺乏元认知通道")
    print("claims:", c)
    r = rewrite_slide_copy(c["claim"], c["evidence"])
    print("rewrite:", r)
    v = visual_concept("准则一｜第一性原理", c["evidence"])
    print("visual:", v)
    pos, neg = build_image_prompt(v)
    print("positive:", pos[:80])
    print("negative:", neg)
