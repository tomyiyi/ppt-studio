#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""封面引擎 v2：hughhowey/neo 方法论落地

核心：
1. "The title is the design"：标题字号自适应铺满容器宽度
2. 一次 3 方案：hero_full / split / minimal
3. 中文：Noto Serif SC 标题 + Noto Sans SC 正文
"""
from __future__ import annotations
from pathlib import Path

import re


def disp_width(text: str) -> float:
    """显示宽度：中文=1，英文=0.55，数字=0.6"""
    w = 0
    for ch in text:
        o = ord(ch)
        if o > 0x4E00 and o < 0x9FFF:
            w += 1.0
        elif ch.isdigit():
            w += 0.6
        elif ch.isascii() and ch.isalpha():
            w += 0.55
        else:
            w += 0.8
    return w


def fit_font_size(text: str, container_width: float, base_size: int = 72,
                  min_size: int = 48, char_width_ratio: float = 0.95) -> int:
    """neo 式：字号自适应铺满容器宽度。

    原理：字号 ≈ 容器宽度 / (显示宽度 × 单字宽比)
    中文方块字单字宽 ≈ 字号 × 0.95
    """
    dw = disp_width(text)
    if dw == 0:
        return base_size
    # 目标：文本总宽 = 容器宽度 × 0.9（留边）
    size = int(container_width * 0.9 / (dw * char_width_ratio))
    return max(min_size, min(size, base_size))


def split_cover_title(title: str, max_lines: int = 3) -> list[str]:
    """封面标题分行：按语义断（冒号/破折号），每行尽量铺满。

    **不丢弃副标题**——旧版 `re.split(r"[：:]", title, 1)` 之后只取 parts[0]，
    导致 `AI Agent 开发：从工具到协作者` 只显示前半。
    现在：冒号前的部分做主标题（分行），冒号后的部分作为第二行/第三行追加。
    """
    # 先按冒号/破折号切主副
    parts = re.split(r"[：:]|——|—", title, maxsplit=1)
    main = parts[0].strip()
    sub = parts[1].strip() if len(parts) > 1 else ""

    lines: list[str] = []
    if disp_width(main) <= 14:
        lines = [main] if main else []
    else:
        # 贪心分行：每行显示宽度尽量接近 12
        cur, cur_w = "", 0
        for ch in main:
            cw = disp_width(ch)
            if cur_w + cw > 12 and cur:
                lines.append(cur)
                cur, cur_w = "", 0
            cur += ch
            cur_w += cw
        if cur:
            lines.append(cur)

    # 副标题按需追加（不超过 max_lines）
    if sub:
        sub_lines = [sub] if disp_width(sub) <= 14 else [
            sub[i:i + 12] for i in range(0, len(sub), 12)
        ]
        for sl in sub_lines:
            if len(lines) >= max_lines:
                break
            if sl.strip():
                lines.append(sl.strip())

    return lines[:max_lines] or [title[:12]]




# 字体栈：把系统实际装有的字体放前面，避免依赖未安装的字体。
# 与 pages_to_svg.py / template_renderer.py 保持一致的回退策略。
_AGNES_TOKENS = None

def _load_agnes_tokens() -> dict:
    """加载 agnes_tokens.json（无文件时返回空）。"""
    global _AGNES_TOKENS
    if _AGNES_TOKENS is None:
        try:
            import json
            tp = Path(__file__).parent / "agnes_tokens.json"
            _AGNES_TOKENS = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {}
        except Exception:
            _AGNES_TOKENS = {}
    return _AGNES_TOKENS


def detect_mood(title: str = "", subtitle: str = "") -> str:
    """从标题推断气质：gaoding（高定/时尚）/ dashi（大气/科技）/ wenyi（文艺）。"""
    t = (title + subtitle).lower()
    if any(k in t for k in ["时尚", "fashion", "高定", "品牌", "奢侈", "vogue", "美妆", "穿搭"]):
        return "gaoding"
    if any(k in t for k in ["文艺", "诗", "治愈", "散文", "文学"]):
        return "wenyi"
    return "dashi"


_MOOD_THEME = {"gaoding": "beauty", "wenyi": "cinematic", "dashi": "grand"}

_TECH_KEYS = ["ai", "agent", "数据", "代码", "模型", "算法", "科技", "智能", "系统", "架构"]


def _copy_vocab() -> dict:
    """agnes copy_templates 词库（title_a/title_b/latin/slogan）。"""
    tokens = _load_agnes_tokens()
    return tokens.get("copy_vocab", {})


def _copy_rules() -> dict:
    tokens = _load_agnes_tokens()
    return tokens.get("copy_rules", {})


def _pangu(text: str) -> str:
    """盘古之白话：CJK 与半角字母/数字之间加空格。"""
    import re
    text = re.sub(r"([\u4e00-\u9fff])([A-Za-z0-9])", r"\1 \2", text)
    text = re.sub(r"([A-Za-z0-9])([\u4e00-\u9fff])", r"\1 \2", text)
    return text


def _normalize_quotes(text: str) -> str:
    """forbid_chars -> prefer_quotes（agnes copy_rules）。"""
    rules = _copy_rules()
    forbid = rules.get("forbid_chars", [])
    prefer = rules.get("prefer_quotes", [])
    if forbid and prefer:
        # “” -> 「」，‘’ -> 「」
        text = text.replace("“", "「").replace("”", "」")
        text = text.replace("‘", "「").replace("’", "」")
    return text


def _mood_theme(mood: str, title: str = "") -> str:
    """mood -> agnes theme。dashi 下有科技词走 tech。"""
    if mood == "dashi" and any(k in title.lower() for k in _TECH_KEYS):
        return "tech"
    return _MOOD_THEME.get(mood, "grand")


def _extract_latin(title: str, mood: str, theme: str) -> str:
    """从标题提年份/季节/英文词组装 latin 副标题；组不出才用主题词库兜底。"""
    import re
    parts = []
    m = re.search(r"(19|20)\d{2}", title)
    year = m.group(0) if m else ""
    # 季节 -> SS/FW（时尚语境）
    season = ""
    if mood == "gaoding":
        if "春" in title or "夏" in title:
            season = "SS"
        elif "秋" in title or "冬" in title:
            season = "FW"
    if season and year:
        parts.append("%s %s" % (season, year))
    elif year:
        parts.append(year)
    # 标题里的英文词（全大写）
    for w in re.findall(r"[A-Za-z]{2,}(?:\s+[A-Za-z]{2,})?", title):
        w = w.strip().upper()
        if w and w not in ("THE", "AND", "OF"):
            parts.append(w)
            break
    if parts:
        return " · ".join(parts[:2])
    # 兜底：主题 latin 词库第一个
    vocab = _copy_vocab().get(theme, {})
    latin = vocab.get("latin", [])
    return latin[0] if latin else ""


def generate_cover_copy(title: str, mood: str = "", hook=None, subtitle: str = "") -> dict:
    """封面文案生成：agnes copy_templates 公式。

    优先级：hook（extract_hook 产出，有则直接用）> 公式改写 > 原标题。
    公式 = 短主标题（title_a+title_b 4-8字结构）+ latin 副标题 + 排版规则（盘古/引号）。
    不编造词汇：主标题只从原标题提炼，latin 从年份/季节/英文词派生。

    返回 {"title": 主标题, "subtitle": 副标题, "theme": 主题名}
    """
    theme = _mood_theme(mood or detect_mood(title, subtitle), title)

    # 1. hook 优先（extract_hook 兼容）
    if hook:
        if isinstance(hook, dict):
            h, sh = hook.get("hook", ""), hook.get("subhook", "")
        else:
            h, sh = str(hook), ""
        if h:
            return {"title": _normalize_quotes(_pangu(h.strip()))[:20],
                    "subtitle": _normalize_quotes(_pangu((sh or subtitle).strip()))[:30],
                    "theme": theme}

    # 2. 公式改写
    import re
    core = re.split(r"[：:——]", title)[0].strip()
    # 年份剥离进 latin
    core = re.sub(r"^(19|20)\d{2}\s*", "", core).strip()
    # 主标题：<=8 字直接用；超长按语义断点压缩（取信息量最大的块，不取首块）
    if len(core) > 8:
        # 数字+量词先黏合（"5 条" -> "5条"），避免数字被单独切出来
        core = re.sub(r"(\d)\s*([条个章节款步])", r"\1\2", core)
        cands = [core]
        for sep in ["，", "、", "之", "与", "和", " "]:
            nxt = []
            for c in cands:
                nxt.extend([x.strip() for x in c.split(sep) if x.strip()])
            cands = nxt
        # 的字结构：保留"A的B"整体感，优先含数字/核心词的块
        scored = []
        for c in cands:
            if not c:
                continue
            score = len(c)
            if len(c) >= 2 and re.search(r"\d", c):
                score += 10  # 数字制造具体感（extract_hook 规则2）
            if 4 <= len(c) <= 10:
                score += 5
            scored.append((score, c))
        if scored:
            scored.sort(reverse=True)
            core = scored[0][1]
        if len(core) > 10:
            core = core[:8]
    mood_v = mood or detect_mood(title, subtitle)
    latin = _extract_latin(title, mood_v, theme)
    if not latin:
        # 兜底：主题 latin 词库
        vocab = _copy_vocab().get(theme, {})
        _lat = vocab.get("latin", [])
        latin = _lat[0] if _lat else ""
    # 副标题：latin + 原 subtitle（slogan 位）；超长先砍 slogan，不断 latin
    slogan = subtitle.strip()
    if latin and slogan and len(latin) + 3 + len(slogan) > 30:
        slogan = slogan[: max(0, 30 - len(latin) - 3)].rstrip("，、。 ")
    sub_parts = [q for q in [latin, slogan] if q]
    sub = " · ".join(sub_parts)[:30]

    return {"title": _normalize_quotes(_pangu(core)),
            "subtitle": _normalize_quotes(_pangu(sub)),
            "theme": theme}


def get_cover_font_family(mood: str = "") -> str:
    """封面标题字体：agnes 字体配方驱动。
    gaoding -> 典雅宋 | dashi -> 势能黑 | wenyi -> 诗意楷
    """
    tokens = _load_agnes_tokens()
    fonts = tokens.get("fonts", {})
    if mood and mood in fonts:
        stack = fonts[mood].get("cn_display", [])
        if stack:
            # 单引号包裹含空格字体名：SVG font-family="..." 属性内双引号会破环 XML
            return ", ".join("'%s'" % f if " " in f else f for f in stack)
    return "Songti SC, STSong, Noto Serif SC, serif"


def get_body_font_family() -> str:
    """正文字体：与项目其余部分统一走苹方。"""
    return "PingFang SC, Hiragino Sans GB, Noto Sans SC, Microsoft YaHei, sans-serif"


if __name__ == "__main__":
    # 自测
    tests = [
        "2026 秋冬时尚趋势",
        "AI Agent 开发的 5 条硬核准则",
        "告别 quiet luxury",
    ]
    for t in tests:
        lines = split_cover_title(t)
        for line in lines:
            size = fit_font_size(line, 1000)
            print(f"'{line}' (宽{disp_width(line):.1f}) -> {size}px")
        print()


# === 3 variant 规格（2026-10-08）：一次出 3 种构图，对标
# jakecall/yt-thumbnail-generator --variants 3 / RESEARCH_COVER.md §6.2 ===
# template: (family, file) 对应 template_renderer 的模板管线
# container_width: 标题自适应字号的容器宽（取自各模板 title slot 的 bounds）
# font_cap: 该构图下标题字号上限（窄栏不宜过大）
COVER_VARIANTS = {
    "hero_full": {
        "desc": "全幅底图 + 底部大标题（v4 现状）",
        "template": ("editorial_bleed", "01_hero_full.svg"),
        "container_width": 1120,
        "max_lines": 3,
        "font_cap": 72,
        "centered": False,
        "use_image": True,
    },
    "split": {
        "desc": "左右分栏：左文右图",
        "template": ("editorial_bleed", "04_split_bleed_reverse.svg"),
        "container_width": 480,
        "max_lines": 2,
        "font_cap": 56,
        "centered": False,
        "use_image": True,
    },
    "minimal": {
        "desc": "极简：大面积留白 + 居中标题",
        "template": ("presentation_core", "10_hero_statement.svg"),
        "container_width": 1088,
        "max_lines": 3,
        "font_cap": 96,
        "centered": True,
        "use_image": False,
    },
}

VARIANT_ORDER = ("hero_full", "split", "minimal")


def generate_variants(title: str, subtitle: str = "", bg_image: str | None = None) -> list[dict]:
    """一次生成 3 种封面构图的 page dict，直接喂给 template_renderer.render_page。

    不破坏现有单封面流程：这只是新增的构造器，默认管线仍走 hero_full。
    """
    pages = []
    for name in VARIANT_ORDER:
        spec = COVER_VARIANTS[name]
        page: dict = {
            "title": title,
            "subtitle": subtitle,
            "bullets": [subtitle] if subtitle else [],
            "layout": "cover",
            "cover_variant": name,
        }
        if spec["use_image"] and bg_image:
            page["image_file"] = bg_image
        pages.append(page)
    return pages
