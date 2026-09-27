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
  python3 render_svg.py --check                            # 渲染后自动执行质量门禁校验

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

try:
    from scripts.qa_layout import run_qa_layout, qa_layout
    from scripts.qa_cards import run_qa_cards, qa_cards
except ImportError:
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    if str(repo_root / "scripts") not in sys.path:
        sys.path.insert(0, str(repo_root / "scripts"))
    try:
        from scripts.qa_layout import run_qa_layout, qa_layout
        from scripts.qa_cards import run_qa_cards, qa_cards
    except ImportError:
        try:
            from qa_layout import run_qa_layout, qa_layout
            from qa_cards import run_qa_cards, qa_cards
        except ImportError:
            run_qa_layout = None
            qa_layout = None
            run_qa_cards = None
            qa_cards = None

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


def render_svg(
    src: str | Path | None = None,
    out: str | Path | None = None,
    scale: float = 1.0,
    only: str | None = None,
    check: bool = False,
    spec_path: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> list[Path]:
    """渲染 PPT Master SVG 或卡片 SVG 为 PNG，并可选执行客观质量门禁校验。

    :param src: 单个 .svg 文件、包含 SVG 的目录或项目目录（默认自发现）
    :param out: 输出目录或单文件路径（默认自适应推导为 render 或 render_cards）
    :param scale: 渲染缩放比例（默认 1.0）
    :param only: 过滤文件名子串
    :param check: 是否在渲染完成后执行客观质量门禁校验 (qa_layout.py / qa_cards.py)
    :param spec_path: 可选指定的规范文件 (spec_lock.md 或 card_spec.md)
    :param base_dir: 基础目录（默认当前工作目录）
    :return: 渲染生成的 PNG 文件 Path 列表
    """
    files, out_dir = resolve_targets(src, out, base_dir=base_dir)

    if only:
        files = [f for f in files if only in f.name]

    if not files:
        target_info = str(src) if src else "目标目录"
        filter_info = f" (匹配 '{only}')" if only else ""
        raise FileNotFoundError(f"未找到 SVG{filter_info}: {target_info}")

    is_single_png_out = len(files) == 1 and out_dir.suffix.lower() == ".png"

    ok = 0
    rendered: list[Path] = []
    errors: list[str] = []
    for f in files:
        dst = out_dir if is_single_png_out else out_dir / (f.stem + ".png")
        try:
            render_one(f, dst, scale)
            size_kb = dst.stat().st_size // 1024 if dst.exists() else 0
            print(f"✓ {f.name} → {dst}  ({size_kb}KB)")
            ok += 1
            rendered.append(dst)
        except Exception as e:
            msg = f"✗ {f.name}: {type(e).__name__} {e}"
            print(msg, file=sys.stderr)
            errors.append(msg)

    print(f"完成 {ok}/{len(files)}")
    if ok != len(files):
        raise RuntimeError(f"渲染未全部成功完成 ({ok}/{len(files)}): {'; '.join(errors)}")

    if check:
        # 判断是卡片还是版面幻灯片
        is_cards = any("cards" in p.parts for p in files) or (files and files[0].parent.name == "cards")
        target_render_dir = out_dir.parent if is_single_png_out else out_dir

        if is_cards:
            target_cards_dir = files[0].parent
            if run_qa_cards is not None:
                passed = run_qa_cards(target_cards_dir, render_dir=target_render_dir, spec_path=spec_path)
                if not passed:
                    raise RuntimeError(f"卡片客观质量门禁未通过: {target_cards_dir}")
                print("  [门禁] ✓ 卡片客观质量门禁通过")
            else:
                print("  [warn] 未导入 run_qa_cards，跳过卡片门禁检查")
        else:
            target_layout = files[0] if len(files) == 1 else files[0].parent
            if run_qa_layout is not None:
                passed = run_qa_layout(target_layout, render_dir=target_render_dir, spec_path=spec_path)
                if not passed:
                    raise RuntimeError(f"SVG 版面客观质量门禁未通过: {target_layout}")
                print("  [门禁] ✓ SVG 版面客观质量门禁通过")
            else:
                print("  [warn] 未导入 run_qa_layout，跳过版面门禁检查")

    return rendered


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="渲染 PPT Master SVG 为 PNG")
    ap.add_argument("src", nargs="?", default=None, help="单个 .svg、svg 目录或项目目录（默认自动发现）")
    ap.add_argument("out", nargs="?", default=None, help="输出目录（可选，默认自动推导为 render 或 render_cards）")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--only", help="只渲染文件名包含该串的页")
    ap.add_argument("--check", action="store_true", help="渲染完成后执行客观质量门禁校验 (qa_layout.py / qa_cards.py)")
    ap.add_argument("--spec", default=None, help="可选指定规范文件 (spec_lock.md 或 card_spec.md)")
    args = ap.parse_args(argv)

    try:
        render_svg(
            src=args.src,
            out=args.out,
            scale=args.scale,
            only=args.only,
            check=args.check,
            spec_path=args.spec,
        )
        return 0
    except (FileNotFoundError, ValueError) as err:
        print(f"[err] {err}", file=sys.stderr)
        return 2
    except RuntimeError as err:
        print(f"[err] {err}", file=sys.stderr)
        return 1
    except Exception as err:
        print(f"[err] {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
