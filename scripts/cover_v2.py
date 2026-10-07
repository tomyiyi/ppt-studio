#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""封面引擎 v2：hughhowey/neo 方法论落地

核心：
1. "The title is the design"：标题字号自适应铺满容器宽度
2. 一次 3 方案：hero_full / split / minimal
3. 中文：Noto Serif SC 标题 + Noto Sans SC 正文
"""
from __future__ import annotations

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


# 三种构图方案
COVER_VARIANTS = {
    "hero_full": {
        "desc": "全幅底图 + 底部大标题",
        "title_pos": "bottom",
        "title_align": "left",
    },
    "split": {
        "desc": "左右分栏：左文右图",
        "title_pos": "left",
        "title_align": "left",
    },
    "minimal": {
        "desc": "极简：大面积留白 + 居中标题",
        "title_pos": "center",
        "title_align": "center",
    },
}


# 字体栈：把系统实际装有的字体放前面，避免依赖未安装的字体。
# 与 pages_to_svg.py / template_renderer.py 保持一致的回退策略。
def get_cover_font_family() -> str:
    """封面标题字体：优先衬线（气质），逐级回退到系统一定有的字体。

    注意：旧版首位是 'Noto Serif SC'——本机未安装时会静默回退到
    Songti SC / serif，与项目其他渲染器的 PingFang SC 观感割裂。
    """
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
