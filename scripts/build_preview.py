#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_preview.py —— 把若干 SVG 打包成单文件 HTML 翻页预览
=========================================================

支持 16:9 横版幻灯片、4:5 竖版卡片等多种画幅自动适配，并将图片内联为 Base64，
实现 100% 离线自包含的交互式翻页交付包。
"""

from __future__ import annotations

import argparse
import base64
import mimetypes
import os
import re
import sys
from pathlib import Path

IMAGE_RE = re.compile(r'(<image\b[^>]*?\b(?:href|xlink:href)=")([^"]+)(")')


def inline_images(t: str, svg_dir: str | Path) -> str:
    """把 <image href="../images/x.png"> 内联成 data URI，让预览单文件自包含。"""
    svg_dir_path = Path(svg_dir)

    def repl(m: re.Match) -> str:
        href = m.group(2)
        if href.startswith("data:"):
            return m.group(0)
        p = (svg_dir_path / href).resolve()
        if not p.exists():
            print(f"  [warn] 缺图 {href}")
            return m.group(0)
        mime = mimetypes.guess_type(p.name)[0] or "image/png"
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"{m.group(1)}data:{mime};base64,{b64}{m.group(3)}"

    return IMAGE_RE.sub(repl, t)


def extract_aspect(svg_text: str) -> tuple[float, float]:
    """提取 SVG viewBox 画幅尺寸。"""
    m = re.search(r'viewBox=["\']([\d.\s-]+)["\']', svg_text)
    if m:
        parts = m.group(1).split()
        if len(parts) == 4:
            try:
                w, h = float(parts[2]), float(parts[3])
                if w > 0 and h > 0:
                    return w, h
            except ValueError:
                pass
    return 1280.0, 720.0


def build_preview(src: str | Path, out: str | Path, title: str) -> None:
    src_path = Path(src).resolve()
    out_path = Path(out).resolve()

    if not src_path.is_dir():
        raise FileNotFoundError(f"未找到源目录: {src_path}")

    svg_files = sorted(src_path.glob("*.svg"))
    if not svg_files:
        raise FileNotFoundError(f"目录内无 SVG 文件: {src_path}")

    svgs = []
    for f in svg_files:
        t = f.read_text(encoding="utf-8")
        t = re.sub(r"\s*<\?xml[^>]*\?>", "", t)
        t = inline_images(t, src_path)
        svgs.append(t)

    w, h = extract_aspect(svgs[0]) if svgs else (1280.0, 720.0)
    vw_h = (h / w) * 100.0
    vh_w = (w / h) * 100.0

    slides = "\n".join(f'  <div class="slide{" active" if i == 0 else ""}">{s}</div>' for i, s in enumerate(svgs))
    n = len(svgs)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title}</title><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#05060a;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow:hidden}}
.stage{{width:100vw;height:100vh;display:flex;align-items:center;justify-content:center}}
.slide{{display:none;width:100vw;height:{vw_h:.2f}vw;max-height:100vh;max-width:{vh_w:.2f}vh}}
.slide.active{{display:block}}.slide svg{{width:100%;height:100%;display:block}}
.nav{{position:fixed;bottom:18px;right:22px;display:flex;gap:10px;z-index:50}}
.nav button{{background:rgba(18,19,26,.85);border:1px solid #23242E;color:#F7F7F9;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:13px;backdrop-filter:blur(6px)}}
.nav button:hover{{background:rgba(110,123,255,.3);border-color:#6E7BFF}}
.ind{{position:fixed;bottom:24px;left:22px;color:#5A5B66;font-size:12px;letter-spacing:2px}}
.hint{{position:fixed;top:14px;left:22px;color:#5A5B66;font-size:12px}}
</style></head><body><div class="stage">
{slides}
</div><div class="hint">← → 翻页 · F 全屏</div><div class="ind" id="ind">01 / {n:02d}</div>
<div class="nav"><button onclick="go(-1)">◀ 上一页</button><button onclick="go(1)">下一页 ▶</button></div>
<script>
let cur=0;const sl=document.querySelectorAll('.slide'),ind=document.getElementById('ind');
function show(i){{sl[cur].classList.remove('active');cur=(i+sl.length)%sl.length;sl[cur].classList.add('active');ind.textContent=String(cur+1).padStart(2,'0')+' / '+String(sl.length).padStart(2,'0');}}
function go(d){{show(cur+d);}}
window.addEventListener('keydown',e=>{{if(e.key==='ArrowRight'||e.key===' '){{e.preventDefault();go(1);}}if(e.key==='ArrowLeft'){{e.preventDefault();go(-1);}}if(e.key==='f'||e.key==='F'){{if(!document.fullscreenElement)document.documentElement.requestFullscreen();else document.exitFullscreen();}}}});
</script></body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"saved: {out_path} {out_path.stat().st_size} bytes, {n} slides")


def main() -> int:
    parser = argparse.ArgumentParser(description="把若干 SVG 打包成单文件 HTML 翻页预览")
    parser.add_argument("src", nargs="?", default="projects/agentflow-os-launch/svg_output", help="包含 SVG 文件的目录")
    parser.add_argument("out", nargs="?", default="output/预览.html", help="输出 HTML 路径")
    parser.add_argument("title", nargs="?", default="智流 OS · 幻灯片预览", help="HTML 页面标题")
    args = parser.parse_args()

    build_preview(args.src, args.out, args.title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
