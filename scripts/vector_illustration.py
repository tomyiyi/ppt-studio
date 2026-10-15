#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
矢量配图生成器（S7，vector 意图的本地旁路）
===========================================

不调 Agnes、不开浏览器：用 stdlib 生成确定性几何矢量插画（SVG），
再经 render_svg_cairo.py（py3.11 + cairosvg）栅格化为 PNG。

约束：
- 画面**不含任何文字**（避免与页面文案打架，也绕开照抄率/字体判据）；
- 配色取自 spec_lock.md 的 colors 段（读不到时用同值兜底），不改任何阈值；
- 对比度纪律：本图只作背景/装饰层，主体亮度受 P99 与模板遮罩约束，
  生成侧主动把装饰元素压在 surface/secondary_text 亮度带，仅少量 accent 点缀。

用法：
  python3 vector_illustration.py --prompt "系统架构分层" --seed 7 \
      --svg-out /tmp/v.svg --png-out /tmp/v.png [--spec-lock deck/spec_lock.md]
作为库：make_svg(prompt, seed) -> str；rasterize(svg_path, png_path, width)。
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
PY311_CANDIDATES = ["/usr/local/bin/python3.11", "python3.11"]

FALLBACK_COLORS = {
    "background": "#08090C",
    "surface": "#12131A",
    "divider": "#23242E",
    "primary_text": "#F7F7F9",
    "secondary_text": "#8E8F9A",
    "accent": "#6E7BFF",
    "improvement": "#4ADE80",
}

W, H = 1280, 720


def load_colors(spec_lock: Path | None) -> dict:
    colors = dict(FALLBACK_COLORS)
    if spec_lock and Path(spec_lock).exists():
        try:
            sys.path.insert(0, str(SCRIPTS))
            import spec_tokens  # noqa: 延迟导入，仓库内既有模块

            tok = spec_tokens.load(str(spec_lock))
            for k, v in (tok.colors or {}).items():
                if v:
                    colors[k] = v
        except Exception:
            pass  # 读不到就用兜底配色，不装通
    return colors


def _rand_stream(seed: int, prompt: str):
    h = hashlib.sha256(("%d|%s" % (seed, prompt)).encode("utf-8")).digest()
    i = 0
    while True:
        if i >= len(h):
            h += hashlib.sha256(h).digest()
        yield h[i]
        i += 1


MOTIFS = ("layers", "network", "arcs", "columns")


def make_svg(prompt: str, seed: int = 1, spec_lock: Path | None = None) -> str:
    """确定性生成：同 (prompt, seed) 永远同图。返回 SVG 文本。"""
    c = load_colors(spec_lock)
    rnd = _rand_stream(seed, prompt)
    motif = MOTIFS[next(rnd) % len(MOTIFS)]
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d">' % (W, H, W, H),
        '<rect width="%d" height="%d" fill="%s"/>' % (W, H, c["background"]),
    ]

    def r(mod: int) -> int:
        return next(rnd) % mod

    if motif == "layers":  # 错位堆叠的圆角层板（架构分层意象）
        for i in range(4):
            w = 520 + r(240)
            x = 120 + r(120) - i * 30
            y = 140 + i * 120 + r(24)
            stroke = c["accent"] if i == 1 else c["secondary_text"]
            op = "0.9" if stroke == c["accent"] else "1"
            parts.append(
                '<rect x="%d" y="%d" width="%d" height="72" rx="14" fill="%s" '
                'stroke="%s" stroke-width="3" stroke-opacity="%s"/>'
                % (x, y, w, c["surface"], stroke, op))
            for k in range(3 + r(3)):
                parts.append('<circle cx="%d" cy="%d" r="6" fill="%s" opacity="0.85"/>'
                             % (x + 36 + k * 34, y + 36,
                                c["improvement"] if (i + k) % 5 == 0 else c["secondary_text"]))
    elif motif == "network":  # 节点连线（协作/路由意象）
        pts = [(140 + r(1000), 90 + r(540)) for _ in range(9)]
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                dx, dy = pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]
                if dx * dx + dy * dy < 300 * 300:
                    parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" '
                                 'stroke-width="2" stroke-opacity="0.8"/>'
                                 % (pts[i][0], pts[i][1], pts[j][0], pts[j][1], c["secondary_text"]))
        for i, (x, y) in enumerate(pts):
            fill = c["accent"] if i % 3 == 0 else c["surface"]
            rad = 10 + (6 if i % 3 == 0 else 0)
            parts.append('<circle cx="%d" cy="%d" r="%d" fill="%s" stroke="%s" '
                         'stroke-width="2"/>' % (x, y, rad, fill, c["divider"]))
    elif motif == "arcs":  # 同心弧（扩散/节奏意象）
        cx, cy = 940 + r(160), 120 + r(120)
        for i in range(6):
            rad = 90 + i * 70 + r(18)
            col = c["accent"] if i in (1, 4) else c["secondary_text"]
            parts.append('<circle cx="%d" cy="%d" r="%d" fill="none" stroke="%s" '
                         'stroke-width="%s" stroke-opacity="0.9"/>'
                         % (cx, cy, rad, col, "4" if col == c["accent"] else "2"))
        parts.append('<circle cx="%d" cy="%d" r="14" fill="%s"/>' % (cx, cy, c["improvement"]))
        for i in range(3):
            parts.append('<rect x="%d" y="%d" width="%d" height="8" rx="4" fill="%s"/>'
                         % (110, 520 + i * 44, 240 + r(220), c["surface"]))
    else:  # columns —— 不等高柱列（数据/排期意象）
        n = 7
        bw = 96
        gap = (W - 200 - n * bw) // (n - 1)
        for i in range(n):
            bh = 120 + r(360)
            x = 100 + i * (bw + gap)
            col = c["accent"] if i == n - 2 else c["surface"]
            parts.append('<rect x="%d" y="%d" width="%d" height="%d" rx="10" fill="%s" '
                         'stroke="%s" stroke-width="2"/>'
                         % (x, H - 90 - bh, bw, bh, col, c["divider"]))
            parts.append('<circle cx="%d" cy="%d" r="7" fill="%s"/>'
                         % (x + bw // 2, H - 90 - bh - 18,
                            c["improvement"] if i % 2 else c["secondary_text"]))
    parts.append("</svg>")
    return "\n".join(parts)


def rasterize(svg_path: Path, png_path: Path, width: int = 1280) -> bool:
    """经 py3.11 cairosvg 旁路栅格化；环境缺失返回 False（调用方如实缓办）。"""
    for py in PY311_CANDIDATES:
        probe = subprocess.run([py, "-c", "import cairosvg"], capture_output=True)
        if probe.returncode != 0:
            continue
        r = subprocess.run(
            [py, str(SCRIPTS / "render_svg_cairo.py"), str(svg_path),
             str(png_path.parent), "--width", str(width)],
            capture_output=True, text=True)
        produced = png_path.parent / (svg_path.stem + ".png")
        if r.returncode == 0 and produced.exists():
            if produced != png_path:
                produced.replace(png_path)
            return True
        print("  [render_svg_cairo] %s" % (r.stdout + r.stderr).strip()[-300:])
        return False
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="vector 意图：本地确定性矢量配图（无浏览器/无生图调用）")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--svg-out", type=Path, required=True)
    ap.add_argument("--png-out", type=Path, help="给出则同时栅格化（cairosvg 旁路）")
    ap.add_argument("--spec-lock", type=Path)
    ap.add_argument("--width", type=int, default=1280)
    args = ap.parse_args(argv)

    svg = make_svg(args.prompt, args.seed, args.spec_lock)
    args.svg_out.parent.mkdir(parents=True, exist_ok=True)
    args.svg_out.write_text(svg, encoding="utf-8")
    print("SVG → %s (%d bytes)" % (args.svg_out, len(svg)))
    if args.png_out:
        ok = rasterize(args.svg_out, args.png_out, args.width)
        if not ok:
            print("栅格化不可用（缺 py3.11+cairosvg），如实退出 2，不产半成品")
            return 2
        print("PNG → %s (%dKB)" % (args.png_out, args.png_out.stat().st_size // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
