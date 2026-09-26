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

# 支持标准 href 与 xlink:href，支持双引号与单引号，支持属性前后空格与大小写
IMAGE_RE = re.compile(
    r'(<image\b[^>]*?\b(?:href|xlink:href)\s*=\s*["\'])([^"\']+)(["\'])',
    re.IGNORECASE,
)


def inline_images(t: str, svg_dir: str | Path) -> str:
    """把 <image href="../images/x.png"> 内联成 data URI，让预览单文件自包含。"""
    svg_dir_path = Path(svg_dir)

    def repl(m: re.Match) -> str:
        href = m.group(2).strip()
        if href.startswith("data:"):
            return m.group(0)
        p = Path(href)
        if not p.is_absolute():
            p = (svg_dir_path / p).resolve()
        else:
            p = p.resolve()
        if not p.exists():
            print(f"  [warn] 缺图 {href}")
            return m.group(0)
        mime = mimetypes.guess_type(p.name)[0] or "image/png"
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"{m.group(1)}data:{mime};base64,{b64}{m.group(3)}"

    return IMAGE_RE.sub(repl, t)


def extract_aspect(svg_text: str) -> tuple[float, float]:
    """提取 SVG viewBox 或 width/height 画幅尺寸。"""
    m = re.search(r'viewBox\s*=\s*["\']([\d.\s,-]+)["\']', svg_text, re.IGNORECASE)
    if m:
        parts = re.split(r'[\s,]+', m.group(1).strip())
        if len(parts) == 4:
            try:
                w, h = float(parts[2]), float(parts[3])
                if w > 0 and h > 0:
                    return w, h
            except ValueError:
                pass
    w_m = re.search(r'<svg\b[^>]*\bwidth\s*=\s*["\']([\d.]+)p?x?["\']', svg_text, re.IGNORECASE)
    h_m = re.search(r'<svg\b[^>]*\bheight\s*=\s*["\']([\d.]+)p?x?["\']', svg_text, re.IGNORECASE)
    if w_m and h_m:
        try:
            w, h = float(w_m.group(1)), float(h_m.group(1))
            if w > 0 and h > 0:
                return w, h
        except ValueError:
            pass
    return 1280.0, 720.0


def resolve_src_dir(
    src_arg: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> Path:
    """自适应探测包含 SVG 画布的源目录。

    保留显式 src 参数行为；
    未传时从当前目录或 projects/ 下安全自动发现唯一有效项目的 svg_output。
    """
    if src_arg is not None and str(src_arg).strip() not in ("", "-"):
        p = Path(src_arg)
        if not p.is_absolute() and base_dir is not None:
            p = (Path(base_dir) / p).resolve()
        else:
            p = p.resolve()
        if not p.exists():
            raise FileNotFoundError(f"指定的源目录不存在: {src_arg}")
        if p.is_dir() and not any(p.glob("*.svg")) and (p / "svg_output").is_dir() and any((p / "svg_output").glob("*.svg")):
            return (p / "svg_output").resolve()
        return p

    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()

    def has_svg_files(p: Path) -> bool:
        return p.is_dir() and any(p.glob("*.svg"))

    def has_svg_output(p: Path) -> bool:
        return has_svg_files(p / "svg_output")

    # 1. 当前工作目录本身是 svg_output 且包含 svg 文件
    if base.name == "svg_output" and has_svg_files(base):
        return base

    # 2. 当前目录直接包含有效 svg_output（且不是包含 projects/ 的工作区根目录）
    if not (base / "projects").is_dir() and has_svg_output(base):
        return (base / "svg_output").resolve()

    # 3. 从 projects/ 目录下安全发现
    candidate_projects_dirs: list[Path] = []
    if base.is_dir() and base.name == "projects":
        candidate_projects_dirs.append(base)
    elif (base / "projects").is_dir():
        candidate_projects_dirs.append(base / "projects")
    elif base_dir is None:
        for cand in [base.parent, base.parent.parent, Path(__file__).resolve().parent.parent]:
            try:
                p_cand = cand / "projects"
                if p_cand.is_dir() and p_cand.resolve() not in [d.resolve() for d in candidate_projects_dirs]:
                    candidate_projects_dirs.append(p_cand)
                    break
            except Exception:
                pass

    found: list[Path] = []
    seen: set[Path] = set()

    for p_dir in candidate_projects_dirs:
        for sub in sorted(p_dir.iterdir()):
            if sub.is_dir() and has_svg_output(sub):
                r_sub = (sub / "svg_output").resolve()
                if r_sub not in seen:
                    seen.add(r_sub)
                    found.append(r_sub)
        if found:
            break

    # 4. 若 projects/ 下未找到，但 base 本身有 svg_output/*.svg（兜底）
    if not found and has_svg_output(base):
        return (base / "svg_output").resolve()

    if len(found) == 1:
        return found[0]
    elif len(found) == 0:
        raise FileNotFoundError(
            "未在当前目录或 projects/ 下发现包含 svg_output/*.svg 的有效项目，请显式指定 src 参数"
        )
    else:
        names = ", ".join(p.parent.name for p in found)
        raise ValueError(
            f"发现多个包含 svg_output 的有效项目 ({names})，无法安全确定，请显式指定 src 参数"
        )


def build_preview(
    src: str | Path | None = None,
    out: str | Path = "output/预览.html",
    title: str = "智流 OS · 幻灯片预览",
) -> None:
    src_path = resolve_src_dir(src)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把若干 SVG 打包成单文件 HTML 翻页预览")
    parser.add_argument(
        "src",
        nargs="?",
        default=None,
        help="包含 SVG 文件的目录（默认安全自动发现唯一有效项目的 svg_output）",
    )
    parser.add_argument("out", nargs="?", default="output/预览.html", help="输出 HTML 路径")
    parser.add_argument("title", nargs="?", default="智流 OS · 幻灯片预览", help="HTML 页面标题")
    args = parser.parse_args(argv)

    try:
        build_preview(args.src, args.out, args.title)
    except (FileNotFoundError, ValueError) as err:
        print(f"[err] {err}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
