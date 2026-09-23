#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SVG 页面渲染器（视觉验证用）
============================

把 PPT Master 的 svg_output/*.svg 渲染成 PNG，用于「导出前肉眼验收」。
会自动把 <image href="../images/x.png"> 内联成 base64，避免跨目录加载失败。

用法：
  python3 render_svg.py <svg_or_dir> <out_dir> [--scale 1] [--only 01_cover]
  python3 render_svg.py <project>/svg_output <out_dir>/png --scale 1

依赖：playwright（系统 python3 已装）+ 本机 Google Chrome。
"""

from __future__ import annotations

import argparse
import base64
import mimetypes
import os
import re
import shutil
import sys
from pathlib import Path

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome",
]

IMAGE_RE = re.compile(r'(<image\b[^>]*?\bhref=")([^"]+)(")')


def resolve_chrome() -> str | None:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    for name in ("chromium", "google-chrome-stable", "google-chrome"):
        p = shutil.which(name)
        if p and Path(p).exists():
            return p
    return None


def inline_images(svg_text: str, svg_dir: Path) -> str:
    """把相对路径的 <image href> 换成 data URI。"""
    def repl(m: re.Match) -> str:
        href = m.group(2)
        if href.startswith("data:"):
            return m.group(0)
        p = (svg_dir / href).resolve()
        if not p.exists():
            print(f"    [warn] 缺图 {href}")
            return m.group(0)
        mime = mimetypes.guess_type(p.name)[0] or "image/png"
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"{m.group(1)}data:{mime};base64,{b64}{m.group(3)}"
    return IMAGE_RE.sub(repl, svg_text)


def svg_size(svg_text: str) -> tuple[int, int]:
    m = re.search(r'viewBox="([\d.\s-]+)"', svg_text)
    if m:
        parts = m.group(1).split()
        if len(parts) == 4:
            return int(float(parts[2])), int(float(parts[3]))
    return 1280, 720


def render_one(svg_path: Path, out_path: Path, scale: float = 1.0) -> bool:
    from playwright.sync_api import sync_playwright

    text = inline_images(svg_path.read_text(encoding="utf-8"), svg_path.parent)
    w, h = svg_size(text)
    ow, oh = int(w * scale), int(h * scale)
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>html,body{margin:0;padding:0;background:#fff}"
        f"svg{{display:block;width:{ow}px;height:{oh}px}}</style></head><body>"
        f"{text}</body></html>"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    chrome = resolve_chrome()
    with sync_playwright() as p:
        kw = {"headless": True}
        if chrome:
            kw["executable_path"] = chrome
        b = p.chromium.launch(**kw)
        pg = b.new_page(viewport={"width": ow, "height": oh}, device_scale_factor=1)
        pg.set_content(html)
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(out_path), type="png")
        b.close()
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="渲染 PPT Master SVG 为 PNG")
    ap.add_argument("src", help="单个 .svg 或目录")
    ap.add_argument("out", help="输出目录")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--only", help="只渲染文件名包含该串的页")
    args = ap.parse_args()

    src, out = Path(args.src), Path(args.out)
    files = sorted(src.glob("*.svg")) if src.is_dir() else [src]
    if args.only:
        files = [f for f in files if args.only in f.name]
    if not files:
        print(f"[err] 未找到 SVG: {src}")
        return 2

    ok = 0
    for f in files:
        dst = out / (f.stem + ".png")
        try:
            render_one(f, dst, args.scale)
            print(f"✓ {f.name} → {dst}  ({dst.stat().st_size//1024}KB)")
            ok += 1
        except Exception as e:
            print(f"✗ {f.name}: {type(e).__name__} {e}")
    print(f"完成 {ok}/{len(files)}")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
