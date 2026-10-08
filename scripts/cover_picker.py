#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""封面 3 variant 选择器。

从管线 pages.json 读取封面标题/副标题/底图，一次渲染 3 种构图，
输出 HTML 对比页供用户点选，落盘 cover_choice.json。

用法（交互式预览）：
    python3 scripts/cover_picker.py --pages out/pages.json \\
        --images out/images --out out/cover_previews

直接指定（非交互）：
    python3 scripts/cover_picker.py --pages out/pages.json \\
        --images out/images --out out/cover_previews --pick split

随后 md_to_pptx.py 会自动读取 out/cover_choice.json，
或显式传 --cover-choice {hero_full,split,minimal}。
"""
from __future__ import annotations

import argparse
import html as _html
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from cover_v2 import COVER_VARIANTS, VARIANT_ORDER, generate_variants
from template_renderer import render_page


def pick_cover_page(pages: list[dict]) -> dict | None:
    for pg in pages:
        if pg.get("layout") == "cover":
            return pg
    return pages[0] if pages else None


def render_variant_png(page: dict, images_dir: Path, png_path: Path,
                       width: int = 1280, height: int = 720) -> None:
    import cairosvg
    svg = render_page(page, images_dir)
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(png_path),
                     output_width=width, output_height=height)


CARD_CSS = """
body{background:#0b0d12;color:#e8eaf0;font-family:"Noto Sans SC","PingFang SC",sans-serif;margin:0;padding:32px}
h1{font-size:28px;margin:0 0 6px} .sub{color:#9aa0b4;margin:0 0 24px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;max-width:1500px}
.card{background:#14171f;border:2px solid #232836;border-radius:12px;overflow:hidden;cursor:pointer;transition:border-color .15s}
.card:hover{border-color:#4a5468} .card.sel{border-color:#c4a57c}
.card img{width:100%;aspect-ratio:16/9;display:block;background:#000}
.meta{padding:14px 16px}
.meta .name{font-weight:700;font-size:16px}
.meta .name .tag{color:#c4a57c;font-size:12px;border:1px solid #c4a57c;border-radius:4px;padding:1px 6px;margin-left:8px}
.meta .desc{color:#9aa0b4;font-size:13px;margin-top:6px}
#bar{position:fixed;left:0;right:0;bottom:0;background:#14171fee;border-top:1px solid #232836;padding:14px 32px;display:none;align-items:center;gap:16px}
#bar.show{display:flex}
#bar code{background:#0b0d12;padding:6px 10px;border-radius:6px;font-size:13px}
button{background:#c4a57c;color:#111;border:0;border-radius:8px;padding:10px 18px;font-size:14px;font-weight:700;cursor:pointer}
button.ghost{background:transparent;color:#c4a57c;border:1px solid #c4a57c}
"""


def build_html(title: str, subtitle: str, cards: list[dict]) -> str:
    def esc(s: str) -> str:
        return _html.escape(s or "")

    card_html = []
    for c in cards:
        card_html.append(
            f'<div class="card" data-v="{c["name"]}" onclick="selectV(\'{c["name"]}\')">'
            f'<img src="{c["png"]}" alt="{c["name"]}">'
            f'<div class="meta"><div class="name">{c["name"]}'
            f'<span class="tag">{"默认" if c["name"] == "hero_full" else "备选"}</span></div>'
            f'<div class="desc">{esc(c["desc"])}</div></div></div>'
        )
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>封面三选一 · {esc(title)}</title><style>{CARD_CSS}</style></head><body>
<h1>封面三选一</h1><p class="sub">{esc(title)}{" — " + esc(subtitle) if subtitle else ""}</p>
<div class="grid">{''.join(card_html)}</div>
<div id="bar"><span>已选：<b id="vname"></b></span>
<button class="ghost" onclick="copyCmd()">复制管线命令</button>
<button onclick="dlJson()">下载 cover_choice.json</button>
<code id="cmd"></code></div>
<script>
let cur=null;
function selectV(v){{cur=v;document.getElementById('vname').textContent=v;
document.querySelectorAll('.card').forEach(e=>e.classList.toggle('sel',e.dataset.v===v));
document.getElementById('cmd').textContent='python3 scripts/md_to_pptx.py --md <文章.md> --out <out> --cover-choice '+v;
document.getElementById('bar').classList.add('show');}}
function copyCmd(){{navigator.clipboard.writeText(document.getElementById('cmd').textContent).then(()=>alert('已复制'));}}
function dlJson(){{if(!cur)return;const b=new Blob([JSON.stringify({{cover_variant:cur}},null,2)],{{type:'application/json'}});
const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='cover_choice.json';a.click();}}
</script></body></html>"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="封面 3 variant 预览与选择")
    ap.add_argument("--pages", type=Path, help="管线 pages.json（优先）")
    ap.add_argument("--title", default="", help="标题（无 --pages 时用）")
    ap.add_argument("--subtitle", default="", help="副标题（无 --pages 时用）")
    ap.add_argument("--bg", default="p00_bg.png", help="底图文件名（无 --pages 时用）")
    ap.add_argument("--images", type=Path, required=True, help="图片目录")
    ap.add_argument("--out", type=Path, required=True, help="预览输出目录")
    ap.add_argument("--pick", choices=list(VARIANT_ORDER),
                    help="非交互：直接写入 cover_choice.json")
    a = ap.parse_args(argv)

    if a.pages:
        raw = json.loads(a.pages.read_text(encoding="utf-8"))
        pages = raw["pages"] if isinstance(raw, dict) else raw
        cover = pick_cover_page(pages)
        if not cover:
            print("pages.json 为空", file=sys.stderr)
            return 1
        title = cover.get("title", "")
        subtitle = cover.get("subtitle", "")
        bg = cover.get("image_file") or "p00_bg.png"
    else:
        if not a.title:
            print("需要 --pages 或 --title", file=sys.stderr)
            return 1
        title, subtitle, bg = a.title, a.subtitle, a.bg

    a.out.mkdir(parents=True, exist_ok=True)
    if not (a.images / bg).exists():
        print(f"警告：底图 {bg} 不存在，hero_full/split 将按无图渲染", file=sys.stderr)
        bg = None

    variants = generate_variants(title, subtitle, bg)
    cards = []
    for pg in variants:
        name = pg["cover_variant"]
        png = f"{name}.png"
        render_variant_png(pg, a.images, a.out / png)
        cards.append({"name": name, "png": png,
                      "desc": COVER_VARIANTS[name]["desc"]})
        print(f"  {name}: {png}")

    (a.out / "index.html").write_text(build_html(title, subtitle, cards),
                                      encoding="utf-8")
    print(f"预览页：{a.out / 'index.html'}")

    choice_path = a.out / "cover_choice.json"
    if a.pick:
        choice_path.write_text(json.dumps({"cover_variant": a.pick},
                                          ensure_ascii=False, indent=2),
                               encoding="utf-8")
        print(f"已选 {a.pick} -> {choice_path}")
    else:
        print("在浏览器打开 index.html 点选，或加 --pick <variant> 直接指定")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
