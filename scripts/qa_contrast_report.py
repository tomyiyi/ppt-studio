#!/usr/bin/env python3
"""Render a self-contained report for SVG text contrast failures."""

from __future__ import annotations

import argparse
import base64
import io
from html import escape
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw

from scripts.qa_layout import WCAG_MIN, check_contrast_detailed, spec_polarity


def _uri(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _annotate(image: Image.Image, rows: list[dict]) -> Image.Image:
    out = image.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    for row in rows:
        if row["ratio"] < WCAG_MIN:
            draw.rectangle(row["bbox"], outline=(232, 52, 52), width=max(2, out.width // 640))
    return out


def build_report(svg_dir: Path, render_dir: Path, output: Path, spec: Path | None = None) -> None:
    cards = []
    for svg_path in sorted(svg_dir.glob("*.svg")):
        png_path = render_dir / f"{svg_path.stem}.png"
        if not png_path.is_file():
            continue
        root = ET.parse(svg_path).getroot()
        image = Image.open(png_path).convert("RGB")
        rows = check_contrast_detailed(image, root, polarity=spec_polarity(spec))
        failures = [row for row in rows if row["ratio"] < WCAG_MIN]
        annotated = _annotate(image, failures)
        details = "".join(
            f"<li>{row['ratio']:.2f}:1 · {escape(row['text'][:80])} · bbox={row['bbox']}</li>"
            for row in failures
        ) or "<li>无失败文本</li>"
        cards.append(
            f'<article><h2>{escape(svg_path.stem)}</h2>'
            f'<p>失败 {len(failures)}/{len(rows)}</p>'
            f'<img src="{_uri(annotated)}"><ul>{details}</ul></article>'
        )
    html = (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<title>Contrast QA report</title>'
        '<style>body{font:14px system-ui,sans-serif;background:#f4f5f7;margin:24px}'
        'article{background:white;border:1px solid #d8dce2;border-radius:12px;padding:16px;margin:0 0 16px}'
        'img{display:block;width:min(100%,1280px);height:auto;border-radius:8px}li{margin:4px 0}</style>'
        '<h1>Contrast QA report</h1>' + "".join(cards) + '</html>'
    )
    output.write_text(html, encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("svg_dir", type=Path)
    parser.add_argument("render_dir", type=Path)
    parser.add_argument("--spec", type=Path, default=None)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args(argv)
    build_report(args.svg_dir, args.render_dir, args.output, args.spec)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
