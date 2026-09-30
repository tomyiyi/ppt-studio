#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
grid.py -- 12 栏网格坐标计算（确定性版式基础）
================================================
借鉴 json-to-office 的 12x12 网格公式 + deck-factory 的 compose 原则：
  "LLM 只写内容 + 选版式名，代码拥有坐标/颜色/层叠"

LLM 端只输出 grid: {column, row, columnSpan, rowSpan}（0-based），
本模块算出绝对像素坐标。LLM 永远碰不到像素数，版式错位类 bug 从根上消失。

公式：
    trackW = (W - mL - mR - (n-1)*g) / n
    x = mL + col * (trackW + g)
    w = span * trackW + (span-1) * g
    （行方向同理，用画布高 H、上下边距、行数、行距）
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Grid:
    width: float = 1920
    height: float = 1080
    cols: int = 12
    rows: int = 12
    margin_left: float = 144
    margin_right: float = 144
    margin_top: float = 96
    margin_bottom: float = 96
    col_gap: float = 24
    row_gap: float = 24

    @property
    def track_w(self) -> float:
        return (self.width - self.margin_left - self.margin_right
                - (self.cols - 1) * self.col_gap) / self.cols

    @property
    def track_h(self) -> float:
        return (self.height - self.margin_top - self.margin_bottom
                - (self.rows - 1) * self.row_gap) / self.rows

    def cell(self, column: int, row: int,
             column_span: int = 1, row_span: int = 1) -> dict:
        """返回 {x, y, w, h} 绝对坐标。column/row 从 0 起。"""
        if not (0 <= column < self.cols and 0 <= row < self.rows):
            raise ValueError("column/row 越界: %s,%s" % (column, row))
        if column + column_span > self.cols or row + row_span > self.rows:
            raise ValueError("span 越界")
        x = self.margin_left + column * (self.track_w + self.col_gap)
        w = column_span * self.track_w + (column_span - 1) * self.col_gap
        y = self.margin_top + row * (self.track_h + self.row_gap)
        h = row_span * self.track_h + (row_span - 1) * self.row_gap
        return {"x": round(x, 2), "y": round(y, 2),
                "w": round(w, 2), "h": round(h, 2)}

    def col_range(self, start: int, end: int) -> dict:
        """连续多列（start/end 为 1-based 闭区间，如 1-5），返回 x/w。"""
        c = self.cell(start - 1, 0, end - start + 1, 1)
        return {"x": c["x"], "w": c["w"]}


def from_spec(canvas_w: float, canvas_h: float, margin: float,
              cols: int = 12, col_gap: float = 24) -> Grid:
    """从 spec_lock 的 canvas/margin 快速构造（上下边距取左右的 2/3）。"""
    side = margin
    tb = round(margin * 2 / 3)
    return Grid(width=canvas_w, height=canvas_h, cols=cols,
                margin_left=side, margin_right=side,
                margin_top=tb, margin_bottom=tb, col_gap=col_gap)
