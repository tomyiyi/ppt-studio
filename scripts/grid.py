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
import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


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


def from_spec_file(
    spec_path: str | Path,
    base_dir: str | Path | None = None,
    cols: int = 12,
    col_gap: float = 24,
) -> Grid:
    """从 spec_lock.md 文件解析 canvas 与 margin 构造 Grid。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    p = Path(spec_path)
    if not p.is_absolute():
        p = (base / p).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"未找到 spec 文件: {p}")
    txt = p.read_text(encoding="utf-8")
    m_viewbox = re.search(r"viewBox\s*:\s*0\s+0\s+(\d+)\s+(\d+)", txt)
    if not m_viewbox:
        raise ValueError(f"spec 文件中未解析到有效的 viewBox (形如 viewBox: 0 0 W H): {p}")
    canvas_w = float(m_viewbox.group(1))
    canvas_h = float(m_viewbox.group(2))

    m_margin = re.search(r"margin\s*[:\uff1a]\s*(\d+)\s*px", txt)
    if not m_margin:
        raise ValueError(f"spec 文件中未解析到有效的 margin (形如 margin: Npx): {p}")
    margin = float(m_margin.group(1))

    return from_spec(canvas_w, canvas_h, margin, cols=cols, col_gap=col_gap)


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="grid.py -- 12 栏网格坐标与单元格区域计算工具",
    )
    parser.add_argument(
        "--spec",
        default=None,
        help="spec_lock.md 文件路径（自动读取 canvas 与 margin）",
    )
    parser.add_argument(
        "--width",
        type=float,
        default=None,
        help="画布宽度（默认: 1920 或从 --spec 读取）",
    )
    parser.add_argument(
        "--height",
        type=float,
        default=None,
        help="画布高度（默认: 1080 或从 --spec 读取）",
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=None,
        help="画布侧边距（默认: 144 或从 --spec 读取）",
    )
    parser.add_argument(
        "--cols",
        type=int,
        default=12,
        help="网格列数（默认: 12）",
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=12,
        help="网格行数（默认: 12）",
    )
    parser.add_argument(
        "--col-gap",
        type=float,
        default=24,
        help="列间距（默认: 24）",
    )
    parser.add_argument(
        "--row-gap",
        type=float,
        default=24,
        help="行间距（默认: 24）",
    )
    parser.add_argument(
        "--col",
        type=int,
        default=None,
        help="单元格起始列索引 (0-based)",
    )
    parser.add_argument(
        "--row",
        type=int,
        default=None,
        help="单元格起始行索引 (0-based)",
    )
    parser.add_argument(
        "--col-span",
        type=int,
        default=1,
        help="跨越列数（默认: 1）",
    )
    parser.add_argument(
        "--row-span",
        type=int,
        default=1,
        help="跨越行数（默认: 1）",
    )
    parser.add_argument(
        "--col-range",
        default=None,
        help="连续多列范围 (1-based 闭区间，形如 '1-5')",
    )
    parser.add_argument(
        "--track",
        action="store_true",
        help="输出单轨尺寸 (track_w / track_h)",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="指定基础工作目录 (默认: 当前工作目录)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出计算结果",
    )
    args = parser.parse_args(argv)

    effective_base = (
        Path(args.base_dir).resolve()
        if args.base_dir
        else (Path(base_dir).resolve() if base_dir else Path.cwd().resolve())
    )

    try:
        if args.spec:
            grid = from_spec_file(args.spec, base_dir=effective_base, cols=args.cols, col_gap=args.col_gap)
            grid.rows = args.rows
            grid.row_gap = args.row_gap
            if args.width is not None:
                grid.width = args.width
            if args.height is not None:
                grid.height = args.height
            if args.margin is not None:
                grid.margin_left = args.margin
                grid.margin_right = args.margin
                grid.margin_top = round(args.margin * 2 / 3)
                grid.margin_bottom = round(args.margin * 2 / 3)
        else:
            w = args.width if args.width is not None else 1920
            h = args.height if args.height is not None else 1080
            m = args.margin if args.margin is not None else 144
            grid = from_spec(w, h, m, cols=args.cols, col_gap=args.col_gap)
            grid.rows = args.rows
            grid.row_gap = args.row_gap
    except Exception as e:
        print(f"[!] 网格初始化失败: {e}", file=sys.stderr)
        return 1

    result: dict[str, object] = {
        "width": grid.width,
        "height": grid.height,
        "cols": grid.cols,
        "rows": grid.rows,
        "track_w": round(grid.track_w, 2),
        "track_h": round(grid.track_h, 2),
    }

    if args.col_range:
        m = re.match(r"^(\d+)\s*-\s*(\d+)$", args.col_range.strip())
        if not m:
            print(f"[!] --col-range 格式不合法，应形如 '1-5': '{args.col_range}'", file=sys.stderr)
            return 2
        start, end = int(m.group(1)), int(m.group(2))
        try:
            cr = grid.col_range(start, end)
        except Exception as e:
            print(f"[!] 列范围计算失败: {e}", file=sys.stderr)
            return 1
        result["col_range"] = {"start": start, "end": end, **cr}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"col_range {start}-{end}: x={cr['x']} w={cr['w']}")
        return 0

    if args.col is not None or args.row is not None:
        c = args.col if args.col is not None else 0
        r = args.row if args.row is not None else 0
        try:
            cell = grid.cell(c, r, args.col_span, args.row_span)
        except Exception as e:
            print(f"[!] 单元格计算失败: {e}", file=sys.stderr)
            return 1
        result["cell"] = {
            "col": c,
            "row": r,
            "col_span": args.col_span,
            "row_span": args.row_span,
            **cell,
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"cell ({c}, {r}, span {args.col_span}x{args.row_span}): x={cell['x']} y={cell['y']} w={cell['w']} h={cell['h']}")
        return 0

    if args.track:
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"track_w={result['track_w']} track_h={result['track_h']}")
        return 0

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"Grid: {grid.width}x{grid.height}, {grid.cols} cols x {grid.rows} rows, track_w={result['track_w']}, track_h={result['track_h']}")
    return 0


__all__ = [
    "Grid",
    "from_spec",
    "from_spec_file",
    "main",
]

if __name__ == "__main__":
    raise SystemExit(main())
