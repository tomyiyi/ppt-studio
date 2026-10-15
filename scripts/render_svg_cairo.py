#!/usr/local/bin/python3.11
# -*- coding: utf-8 -*-
"""
SVG 页面渲染器（cairosvg 无浏览器旁路，S7）
==========================================

与 render_svg.py（Playwright/Chrome）同 CLI 形状，但**不开浏览器**——
GPU/WindowServer panic 风险期（R5）的验证循环走这里。render_svg.py 原样不动。

RUN-20261015 S6 定位的三个环境坑，本脚本逐一处理：
  1. cairosvg 2.9 默认 unsafe=False，外链 <image> 被换成 32 字节占位符
     （图"消失"的真因）⇒ 必须 unsafe=True。
  2. cairo 走 FcNameParse 精确匹配，CSS 逗号回退链不生效；模板里的
     "SmileySans"（无空格）解析不命中会整页豆腐块 ⇒ 渲染前做字体族名规范化。
  3. 相对 href 以 SVG 所在目录为基 ⇒ 规范化副本写回**同目录**临时文件。

用法：
  /usr/local/bin/python3.11 render_svg_cairo.py <svg_or_dir> <out_dir> [--width 1280] [--only 00_cover]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FONT_ATTR_RE = re.compile(r'(font-family=")([^"]*)(")')


def normalize_fonts(svg_text: str) -> str:
    def fix_family(m: re.Match) -> str:
        fam = m.group(2)
        fam = re.sub(r'\bSmileySans\b', 'Smiley Sans', fam)
        fam = fam.replace("'思源黑 Heavy'", "'Noto Sans SC'")
        return m.group(1) + fam + m.group(3)
    return FONT_ATTR_RE.sub(fix_family, svg_text)


def render_one(svg_path: Path, out_path: Path, width: int = 1280) -> Path:
    import cairosvg  # 仅 py3.11 环境有，延迟导入便于错误信息集中

    text = svg_path.read_text(encoding="utf-8")
    fixed = normalize_fonts(text)
    tmp = svg_path.parent / (".cairo_" + svg_path.stem + ".svg")
    try:
        tmp.write_text(fixed, encoding="utf-8")  # 同目录：保住相对 ../images/
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cairosvg.svg2png(url=str(tmp), write_to=str(out_path),
                         output_width=width, unsafe=True)
    finally:
        tmp.unlink(missing_ok=True)
    return out_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="cairosvg 无浏览器渲染 PPT Master SVG→PNG")
    ap.add_argument("src", help="单个 .svg 或目录")
    ap.add_argument("out", help="输出目录")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--only", help="只渲染文件名包含该串的页")
    args = ap.parse_args(argv)

    src, out = Path(args.src), Path(args.out)
    files = sorted(src.glob("*.svg")) if src.is_dir() else [src]
    files = [f for f in files if not f.name.startswith(".")]
    if args.only:
        files = [f for f in files if args.only in f.name]
    if not files:
        print(f"[err] 未找到 SVG: {src}")
        return 2

    ok = 0
    for f in files:
        dst = out / (f.stem + ".png")
        try:
            render_one(f, dst, args.width)
            print(f"✓ {f.name} → {dst}  ({dst.stat().st_size // 1024}KB)")
            ok += 1
        except Exception as e:
            print(f"✗ {f.name}: {type(e).__name__} {e}")
    print(f"完成 {ok}/{len(files)}")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
