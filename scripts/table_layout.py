#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Table 版式：Markdown 表格 -> SVG 真表格。

设计：
- 表头深色底 + 白字
- 行交替底色
- 列宽按内容自适应
- 单页容纳 ≤8 行，超出才拆页
"""
from __future__ import annotations

import html
import re


def parse_md_table(bullets: list[str]) -> tuple[list[str], list[list[str]]]:
    """从 bullets 解析 Markdown 表格。返回 (表头, 数据行)。"""
    header: list[str] = []
    rows: list[list[str]] = []
    for b in bullets:
        b = b.strip()
        if not b.startswith("|"):
            continue
        cells = [c.strip() for c in b.strip("|").split("|")]
        if not header:
            header = cells
        else:
            rows.append(cells)
    return header, rows


def disp_w(text: str) -> float:
    w = 0
    for ch in text:
        o = ord(ch)
        if 0x4E00 < o < 0x9FFF:
            w += 1.0
        elif ch.isdigit():
            w += 0.6
        elif ch.isascii() and ch.isalpha():
            w += 0.55
        else:
            w += 0.8
    return w


def render_table_svg(header: list[str], rows: list[list[str]],
                     x: int = 80, y: int = 200, width: int = 1120,
                     font_size: int = 20, row_h: int = 52,
                     title: str = "") -> str:
    """生成 SVG 表格（含标题）。"""
    n_cols = len(header)
    if n_cols == 0:
        return ""
    parts = []
    if title:
        parts.append(
            f'<text x="{x}" y="120" '
            f'font-family="Noto Sans SC, PingFang SC, sans-serif" '
            f'font-size="32" font-weight="700" fill="#1a1d29">'
            f'{html.escape(title)}</text>'
        )

    # 列宽：按最大内容宽度比例分配
    col_max = [disp_w(h) for h in header]
    for r in rows:
        for i, c in enumerate(r[:n_cols]):
            col_max[i] = max(col_max[i], disp_w(c))

    total = sum(col_max)
    col_ws = [max(120, int(width * w / total)) for w in col_max]
    # 归一化到总宽
    scale = width / sum(col_ws)
    col_ws = [int(w * scale) for w in col_ws]
    col_ws[-1] = width - sum(col_ws[:-1])

    # 表头
    cx = x
    for i, h in enumerate(header):
        parts.append(
            f'<rect x="{cx}" y="{y}" width="{col_ws[i]}" height="{row_h}" '
            f'fill="#1a1d29" rx="4"/>'
            f'<text x="{cx + 16}" y="{y + row_h // 2 + 7}" '
            f'font-family="Noto Sans SC, PingFang SC, sans-serif" '
            f'font-size="{font_size}" font-weight="700" fill="#FFFFFF">'
            f'{html.escape(h)}</text>'
        )
        cx += col_ws[i]

    # 数据行
    for ri, r in enumerate(rows):
        ry = y + row_h * (ri + 1)
        bg = "#f5f6fa" if ri % 2 == 0 else "#ffffff"
        cx = x
        for i in range(n_cols):
            cell = r[i] if i < len(r) else ""
            parts.append(
                f'<rect x="{cx}" y="{ry}" width="{col_ws[i]}" height="{row_h}" '
                f'fill="{bg}" stroke="#e0e2ea" stroke-width="1"/>'
                f'<text x="{cx + 16}" y="{ry + row_h // 2 + 7}" '
                f'font-family="Noto Sans SC, PingFang SC, sans-serif" '
                f'font-size="{font_size}" fill="#2a2d3a">'
                f'{html.escape(cell)}</text>'
            )
            cx += col_ws[i]

    return "\n".join(parts)


if __name__ == "__main__":
    h = ["趋势", "核心", "关键词"]
    r = [["红色统治", "全身一色", "Poppy Red、牛血红"]]
    print(render_table_svg(h, r)[:200])
