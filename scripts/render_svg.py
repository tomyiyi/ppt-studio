#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SVG 页面渲染器（视觉验证用）
============================

把 PPT Master 的 svg_output/*.svg 或 cards/*.svg 渲染成 PNG，用于「导出前肉眼验收」。
会自动把相对路径或 xlink 格式的 <image href="..."> 内联成 base64，避免跨目录加载失败。

用法：
  python3 render_svg.py <svg_or_dir> <out_dir> [--scale 1] [--only 01_cover]
  python3 render_svg.py <project>/svg_output [--scale 1]
  python3 render_svg.py                                    # 自动发现项目与渲染目录

依赖：playwright + 本机 Google Chrome / Chromium。
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

# 确保在未显式激活 .venv 时也能从项目内 .venv 加载依赖
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    repo_root = Path(__file__).resolve().parent.parent
    for site_pkg in repo_root.glob(".venv/lib/python*/site-packages"):
        if site_pkg.is_dir() and str(site_pkg) not in sys.path:
            sys.path.insert(0, str(site_pkg))
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sync_playwright = None

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome",
]

# 支持标准 href 与 xlink:href，支持双引号与单引号，支持属性前后空格
IMAGE_RE = re.compile(
    r'(<image\b[^>]*?\b(?:href|xlink:href)\s*=\s*["\'])([^"\']+)(["\'])',
    re.IGNORECASE,
)


def resolve_chrome() -> str | None:
    for env_key in ("CHROME_PATH", "PLAYWRIGHT_CHROME_PATH", "CHROMIUM_PATH"):
        val = os.environ.get(env_key)
        if val and Path(val).exists():
            return val

    for c in CHROME_CANDIDATES:
        if c and Path(c).exists():
            return c
    for name in ("chromium", "chromium-browser", "google-chrome-stable", "google-chrome"):
        p = shutil.which(name)
        if p and Path(p).exists():
            return p
    return None


def inline_images(svg_text: str, svg_dir: Path) -> str:
    """把相对路径的 <image href> 或 <image xlink:href> 换成 data URI。"""
    def repl(m: re.Match) -> str:
        href = m.group(2).strip()
        if href.startswith("data:"):
            return m.group(0)
        p = (svg_dir / href).resolve() if not Path(href).is_absolute() else Path(href).resolve()
        if not p.exists():
            print(f"    [warn] 缺图 {href}")
            return m.group(0)
        mime = mimetypes.guess_type(p.name)[0] or "image/png"
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"{m.group(1)}data:{mime};base64,{b64}{m.group(3)}"
    return IMAGE_RE.sub(repl, svg_text)


def svg_size(svg_text: str) -> tuple[int, int]:
    """解析 SVG 画布尺寸，优先读取 viewBox，兜底读取 width/height 属性。"""
    m = re.search(r'viewBox\s*=\s*["\']([^"\']+)["\']', svg_text, re.IGNORECASE)
    if m:
        parts = [x for x in re.split(r'[\s,]+', m.group(1).strip()) if x]
        if len(parts) == 4:
            try:
                w, h = float(parts[2]), float(parts[3])
                if w > 0 and h > 0:
                    return int(round(w)), int(round(h))
            except ValueError:
                pass

    m_w = re.search(r'<svg\b[^>]*\bwidth\s*=\s*["\']([\d.]+)(?:px)?["\']', svg_text, re.IGNORECASE)
    m_h = re.search(r'<svg\b[^>]*\bheight\s*=\s*["\']([\d.]+)(?:px)?["\']', svg_text, re.IGNORECASE)
    if m_w and m_h:
        try:
            w, h = float(m_w.group(1)), float(m_h.group(1))
            if w > 0 and h > 0:
                return int(round(w)), int(round(h))
        except ValueError:
            pass

    return 1280, 720


def resolve_targets(
    src_arg: str | Path | None = None,
    out_arg: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> tuple[list[Path], Path]:
    """自适应解析待渲染 SVG 文件列表与目标输出路径。

    1. 若指定 src_arg：
       - 文件路径：直接返回该文件，默认输出到对应 render 目录。
       - 包含 *.svg 的目录：直接使用该目录下的所有 SVG。
       - 项目目录：优先查找 svg_output/*.svg（默认输出到 render），
                   次选 cards/*.svg（默认输出到 render_cards）。
       - 路径不存在则抛出 FileNotFoundError。
    2. 若未指定 src_arg：
       - 自底向上自适应探测当前工作目录或 projects/ 下的有效项目；
       - 若存在多个有效项目，抛出 ValueError；
       - 若未找到任何有效项目，抛出 FileNotFoundError。
    3. 若显式指定 out_arg：
       - 强制使用用户指定的输出路径，保持向后完全兼容。
    """
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()

    def has_svgs(p: Path) -> bool:
        return p.is_dir() and any(p.glob("*.svg"))

    files: list[Path] = []
    default_out: Path | None = None

    if src_arg is not None and str(src_arg).strip() not in ("", "-"):
        p = Path(src_arg)
        if not p.is_absolute():
            p = (base / p).resolve()
        else:
            p = p.resolve()

        if not p.exists():
            raise FileNotFoundError(f"指定的源路径不存在: {src_arg}")

        if p.is_file():
            files = [p]
            parent_name = p.parent.name
            if parent_name == "svg_output":
                default_out = p.parent.parent / "render"
            elif parent_name == "cards":
                default_out = p.parent.parent / "render_cards"
            else:
                default_out = p.parent / "render"
        elif has_svgs(p):
            files = sorted(p.glob("*.svg"))
            if p.name == "svg_output":
                default_out = p.parent / "render"
            elif p.name == "cards":
                default_out = p.parent / "render_cards"
            else:
                default_out = p / "render"
        else:
            # 尝试探测是否为项目根目录
            if has_svgs(p / "svg_output"):
                files = sorted((p / "svg_output").glob("*.svg"))
                default_out = p / "render"
            elif has_svgs(p / "cards"):
                files = sorted((p / "cards").glob("*.svg"))
                default_out = p / "render_cards"
            else:
                raise FileNotFoundError(f"在指定的目录 {src_arg} 下未找到任何 SVG 文件")
    else:
        # 自动发现
        if base.name == "svg_output" and has_svgs(base):
            files = sorted(base.glob("*.svg"))
            default_out = base.parent / "render"
        elif base.name == "cards" and has_svgs(base):
            files = sorted(base.glob("*.svg"))
            default_out = base.parent / "render_cards"
        elif not (base / "projects").is_dir() and has_svgs(base / "svg_output"):
            files = sorted((base / "svg_output").glob("*.svg"))
            default_out = base / "render"
        elif not (base / "projects").is_dir() and has_svgs(base / "cards"):
            files = sorted((base / "cards").glob("*.svg"))
            default_out = base / "render_cards"
        else:
            candidate_projects_dirs: list[Path] = []
            if base.is_dir() and base.name == "projects":
                candidate_projects_dirs.append(base)
            elif (base / "projects").is_dir():
                candidate_projects_dirs.append(base / "projects")
            elif base_dir is None:
                repo_root = Path(__file__).resolve().parent.parent
                p_cand = repo_root / "projects"
                if p_cand.is_dir():
                    candidate_projects_dirs.append(p_cand)

            found_projs: list[tuple[Path, str]] = []
            for p_dir in candidate_projects_dirs:
                if not p_dir.is_dir():
                    continue
                for sub in sorted(p_dir.iterdir()):
                    if sub.is_dir():
                        if has_svgs(sub / "svg_output"):
                            found_projs.append((sub, "svg_output"))
                        elif has_svgs(sub / "cards"):
                            found_projs.append((sub, "cards"))

            if len(found_projs) == 1:
                proj, kind = found_projs[0]
                if kind == "svg_output":
                    files = sorted((proj / "svg_output").glob("*.svg"))
                    default_out = proj / "render"
                else:
                    files = sorted((proj / "cards").glob("*.svg"))
                    default_out = proj / "render_cards"
            elif len(found_projs) > 1:
                names = ", ".join(p[0].name for p in found_projs)
                raise ValueError(
                    f"发现多个包含 SVG 的项目 ({names})，无法安全确定，请显式指定 src 参数"
                )
            else:
                raise FileNotFoundError(
                    "未在当前目录或 projects/ 下发现包含有效 SVG 的项目，请显式指定 src 参数"
                )

    if out_arg is not None and str(out_arg).strip() != "":
        out_path = Path(out_arg)
        if not out_path.is_absolute():
            out_path = (base / out_path).resolve()
        else:
            out_path = out_path.resolve()
    else:
        out_path = default_out if default_out is not None else (base / "render")

    return files, out_path


def render_one(svg_path: Path, out_path: Path, scale: float = 1.0) -> bool:
    if sync_playwright is None:
        raise RuntimeError("未安装 playwright，且未在 .venv 中找到该依赖")

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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="渲染 PPT Master SVG 为 PNG")
    ap.add_argument("src", nargs="?", default=None, help="单个 .svg、svg 目录或项目目录（默认自动发现）")
    ap.add_argument("out", nargs="?", default=None, help="输出目录（可选，默认自动推导为 render 或 render_cards）")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--only", help="只渲染文件名包含该串的页")
    args = ap.parse_args(argv)

    try:
        files, out_dir = resolve_targets(args.src, args.out)
    except (FileNotFoundError, ValueError) as err:
        print(f"[err] {err}", file=sys.stderr)
        return 2

    if args.only:
        files = [f for f in files if args.only in f.name]

    if not files:
        target_info = args.src or "目标目录"
        filter_info = f" (匹配 '{args.only}')" if args.only else ""
        print(f"[err] 未找到 SVG{filter_info}: {target_info}", file=sys.stderr)
        return 2

    is_single_png_out = len(files) == 1 and out_dir.suffix.lower() == ".png"

    ok = 0
    for f in files:
        dst = out_dir if is_single_png_out else out_dir / (f.stem + ".png")
        try:
            render_one(f, dst, args.scale)
            size_kb = dst.stat().st_size // 1024 if dst.exists() else 0
            print(f"✓ {f.name} → {dst}  ({size_kb}KB)")
            ok += 1
        except Exception as e:
            print(f"✗ {f.name}: {type(e).__name__} {e}", file=sys.stderr)
    print(f"完成 {ok}/{len(files)}")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
