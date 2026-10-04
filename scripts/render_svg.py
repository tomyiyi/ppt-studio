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
  python3 render_svg.py <svg_or_dir> --engine cli           # 强制 chromium CLI 引擎

渲染引擎（--engine auto|playwright|cli，默认 auto）：
  - playwright：经 Playwright CDP 置入 HTML 并截图（规范链路）；
  - cli：把 HTML 落盘为临时文件，直接调 `chromium --headless --screenshot`
    渲染。第 19 轮实测：omarchy 的 Chromium 152（VMware 虚拟机，
    SwiftShader 软渲染）在 1920x1080 viewport 下经 Playwright 截图必现
    renderer 崩溃（viz CopyOutputResultSender 被拒 + GPU 进程 exit 9），
    而 chromium CLI 同内容一次成功；auto 模式 playwright 失败自动降级 cli。

依赖：playwright + 本机 Google Chrome / Chromium。
"""

from __future__ import annotations

import argparse
import base64
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
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

try:
    from scripts.check_page_map import find_svg_dir, resolve_project_dir as _cpm_resolve_project_dir
except ImportError:
    try:
        from check_page_map import find_svg_dir, resolve_project_dir as _cpm_resolve_project_dir
    except ImportError:
        find_svg_dir = None
        _cpm_resolve_project_dir = None


def resolve_project_dir(project_arg: str | Path | None = None) -> Path:
    """自适应解析项目根目录（支持从子目录 images、svg_output*、cards 等或文件回退）。"""
    if _cpm_resolve_project_dir is not None:
        return _cpm_resolve_project_dir(project_arg)
    if project_arg is not None and str(project_arg).strip() not in ("", "."):
        p = Path(project_arg).resolve()
    else:
        p = Path.cwd().resolve()
    if p.is_file():
        p = p.parent
    if (
        p.name in ("images", "svg_output", "render_cards", "render", "notes", "output", "cards")
        or p.name.startswith("svg_output")
        or p.name.startswith("render")
    ):
        if (
            any(p.parent.glob("spec_lock*.md"))
            or any(p.parent.glob("card_spec*.md"))
            or any(p.parent.glob("svg_output*"))
            or (p.parent / "cards").is_dir()
            or (p.parent / "images").is_dir()
        ):
            return p.parent
    return p


def _find_svg_dir(p: Path) -> Path | None:
    if find_svg_dir is not None:
        return find_svg_dir(p)
    # fallback: 优先按数字版本最高 (svg_output_v4 > svg_output_v3 > svg_output)
    cands = sorted(
        [d for d in p.glob("svg_output*") if d.is_dir() and any(d.glob("*.svg"))],
        key=lambda d: (
            int(m.group(1)) if (m := re.match(r"^svg_output_v(\d+)$", d.name, re.I)) else (0 if d.name == "svg_output" else -1)
        ),
        reverse=True,
    )
    if cands:
        return cands[0]
    if any(p.glob("*.svg")):
        return p
    return None

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
            if p.suffix.lower() == ".svg":
                files = [p]
                parent_name = p.parent.name
                if parent_name == "svg_output" or parent_name.startswith("svg_output"):
                    default_out = p.parent.parent / "render"
                elif parent_name == "cards":
                    default_out = p.parent.parent / "render_cards"
                else:
                    default_out = p.parent / "render"
            else:
                proj = resolve_project_dir(p)
                svg_cand = _find_svg_dir(proj)
                if svg_cand and has_svgs(svg_cand):
                    files = sorted(svg_cand.glob("*.svg"))
                    default_out = proj / "render"
                elif has_svgs(proj / "cards"):
                    files = sorted((proj / "cards").glob("*.svg"))
                    default_out = proj / "render_cards"
                elif has_svgs(proj):
                    files = sorted(proj.glob("*.svg"))
                    default_out = proj / "render"
                else:
                    raise FileNotFoundError(f"在文件关联项目 {proj} 下未找到任何 SVG 文件")
        elif has_svgs(p) and (p.name == "svg_output" or p.name.startswith("svg_output") or p.name == "cards"):
            files = sorted(p.glob("*.svg"))
            if p.name == "cards":
                default_out = p.parent / "render_cards"
            else:
                default_out = p.parent / "render"
        else:
            # 尝试探测是否为项目根目录（按版本优先级查找 svg_output*）
            svg_cand = _find_svg_dir(p)
            if svg_cand and has_svgs(svg_cand):
                files = sorted(svg_cand.glob("*.svg"))
                default_out = p / "render"
            elif has_svgs(p):
                files = sorted(p.glob("*.svg"))
                default_out = p / "render"
            elif has_svgs(p / "cards"):
                files = sorted((p / "cards").glob("*.svg"))
                default_out = p / "render_cards"
            else:
                proj = resolve_project_dir(p)
                if proj != p:
                    svg_cand = _find_svg_dir(proj)
                    if svg_cand and has_svgs(svg_cand):
                        files = sorted(svg_cand.glob("*.svg"))
                        default_out = proj / "render"
                    elif has_svgs(proj / "cards"):
                        files = sorted((proj / "cards").glob("*.svg"))
                        default_out = proj / "render_cards"
                    elif has_svgs(proj):
                        files = sorted(proj.glob("*.svg"))
                        default_out = proj / "render"
                    else:
                        raise FileNotFoundError(f"在指定的目录 {src_arg} 下未找到任何 SVG 文件")
                else:
                    raise FileNotFoundError(f"在指定的目录 {src_arg} 下未找到任何 SVG 文件")
    else:
        # 自动发现
        if (base.name == "svg_output" or base.name.startswith("svg_output")) and has_svgs(base):
            files = sorted(base.glob("*.svg"))
            default_out = base.parent / "render"
        elif base.name == "cards" and has_svgs(base):
            files = sorted(base.glob("*.svg"))
            default_out = base.parent / "render_cards"
        else:
            cand_proj = resolve_project_dir(base)
            if cand_proj != base:
                base_svg = _find_svg_dir(cand_proj)
                if base_svg and has_svgs(base_svg):
                    files = sorted(base_svg.glob("*.svg"))
                    default_out = cand_proj / "render"
                elif has_svgs(cand_proj / "cards"):
                    files = sorted((cand_proj / "cards").glob("*.svg"))
                    default_out = cand_proj / "render_cards"
            if not files:
                base_svg = _find_svg_dir(base)
                if not (base / "projects").is_dir() and base_svg and has_svgs(base_svg) and (base.name != "ppt-studio" or base_svg != base):
                    files = sorted(base_svg.glob("*.svg"))
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

                    seen_sub: set[Path] = set()
                    found_projs: list[tuple[Path, Path, str]] = []
                    for p_dir in candidate_projects_dirs:
                        if not p_dir.is_dir():
                            continue
                        for sub in sorted(p_dir.iterdir()):
                            if sub.is_dir() and sub.resolve() not in seen_sub:
                                sub_svg = _find_svg_dir(sub)
                                if sub_svg and has_svgs(sub_svg):
                                    seen_sub.add(sub.resolve())
                                    found_projs.append((sub, sub_svg, "svg"))
                                elif has_svgs(sub / "cards"):
                                    seen_sub.add(sub.resolve())
                                    found_projs.append((sub, sub / "cards", "cards"))

                    if len(found_projs) == 1:
                        proj, target_svg_dir, kind = found_projs[0]
                        files = sorted(target_svg_dir.glob("*.svg"))
                        if kind == "svg":
                            default_out = proj / "render"
                        else:
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


def _build_html(svg_path: Path, scale: float = 1.0) -> tuple[str, int, int]:
    """SVG -> 自包含 HTML（图片已内联为 data URI）；返回 (html, 输出宽, 输出高)。"""
    text = inline_images(svg_path.read_text(encoding="utf-8"), svg_path.parent)
    w, h = svg_size(text)
    ow, oh = int(w * scale), int(h * scale)
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>html,body{margin:0;padding:0;background:#fff}"
        f"svg{{display:block;width:{ow}px;height:{oh}px}}</style></head><body>"
        f"{text}</body></html>"
    )
    return html, ow, oh


def _warn_if_tmp_full() -> None:
    """第 19 轮教训：omarchy /tmp 是 tmpfs，陈旧产物塞满（曾实测 80%）
    会导致 chromium 渲染进程异常退出。只告警，不阻断。"""
    try:
        usage = shutil.disk_usage(tempfile.gettempdir())
        if usage.used / usage.total > 0.85:
            print(f"  [warn] {tempfile.gettempdir()} 已用 "
                  f"{usage.used / usage.total:.0%}，可能影响 chromium 渲染，"
                  "建议清理 /tmp 下的陈旧产物", flush=True)
    except OSError:
        pass


def _stage_png(out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, staged_name = tempfile.mkstemp(prefix=f".{out_path.name}.", dir=out_path.parent, suffix=".png")
    os.close(fd)
    return Path(staged_name)


def render_one(svg_path: Path, out_path: Path, scale: float = 1.0) -> bool:
    """Playwright 引擎：经 CDP 置入 HTML 并截图（规范渲染链路）。

    保持原有契约：失败直接抛异常（不做引擎降级），调用方按需用 _render_page。
    """
    if sync_playwright is None:
        raise RuntimeError("未安装 playwright，且未在 .venv 中找到该依赖")

    html, ow, oh = _build_html(svg_path, scale)
    staged_path = _stage_png(out_path)
    chrome = resolve_chrome()
    try:
        with sync_playwright() as p:
            kw = {"headless": True}
            if chrome:
                kw["executable_path"] = chrome
            b = p.chromium.launch(**kw)
            pg = b.new_page(viewport={"width": ow, "height": oh}, device_scale_factor=1)
            pg.set_content(html)
            pg.wait_for_timeout(300)
            pg.screenshot(path=str(staged_path), type="png")
            b.close()
        os.replace(staged_path, out_path)
    except Exception:
        staged_path.unlink(missing_ok=True)
        raise
    return True


# Chromium CLI 截图的最小 PNG 体积 sanity（1920x1080 空白 PNG 约 8KB；
# 低于此值视为渲染失败，而非合法输出）
_CLI_MIN_PNG_BYTES = 1024
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def render_one_cli(svg_path: Path, out_path: Path, scale: float = 1.0,
                   timeout: int = 180) -> bool:
    """Chromium CLI 引擎：HTML 落盘 -> `chromium --headless --screenshot`。

    绕过 Playwright CDP（set_content 大 payload / 大 viewport 截图崩溃时用）。
    输出 PNG 做魔数 + 最小体积校验，失败抛 RuntimeError。
    """
    chrome = resolve_chrome()
    if not chrome:
        raise RuntimeError("未找到 Chromium/Chrome 可执行文件（CLI 引擎不可用）")
    html, ow, oh = _build_html(svg_path, scale)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, html_name = tempfile.mkstemp(prefix=".render.", suffix=".html", dir=out_path.parent)
    html_path = Path(html_name)
    staged_path = _stage_png(out_path)
    # 独立 user-data-dir：不与用户桌面 Chromium 共享默认 profile，
    # 避开单例锁/DevTools 端口(9222)争用导致的挂起（第 19 轮实测）。
    profile_dir = Path(tempfile.mkdtemp(prefix=".render-profile.", dir=out_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(html)
        proc = subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--no-sandbox",
             "--hide-scrollbars", f"--window-size={ow},{oh}",
             f"--user-data-dir={profile_dir}",
             "--virtual-time-budget=5000",
             f"--screenshot={staged_path}", html_path.as_uri()],
            capture_output=True, text=True, timeout=timeout,
        )
        if not staged_path.exists():
            raise RuntimeError(
                "chromium CLI 未生成截图 (rc=%d): %s" % (proc.returncode, proc.stderr[-500:]))
        data = staged_path.read_bytes()
        if len(data) < _CLI_MIN_PNG_BYTES or not data.startswith(_PNG_MAGIC):
            raise RuntimeError(
                "chromium CLI 截图无效 (%d bytes, 非 PNG): %s" % (len(data), proc.stderr[-300:]))
        os.replace(staged_path, out_path)
    except Exception:
        staged_path.unlink(missing_ok=True)
        raise
    finally:
        html_path.unlink(missing_ok=True)
        shutil.rmtree(profile_dir, ignore_errors=True)
    return True


def _render_page(svg_path: Path, out_path: Path, scale: float = 1.0,
                 engine: str = "auto") -> bool:
    """引擎调度：playwright 主链路；auto 下失败自动降级到 chromium CLI。"""
    if engine == "cli":
        return render_one_cli(svg_path, out_path, scale)
    try:
        return render_one(svg_path, out_path, scale)
    except Exception as e:
        if engine == "playwright":
            raise
        print(f"  [warn] playwright 引擎失败 ({type(e).__name__})，降级到 chromium CLI",
              file=sys.stderr)
        return render_one_cli(svg_path, out_path, scale)


def render_svg(
    src: str | Path | None = None,
    out: str | Path | None = None,
    scale: float = 1.0,
    only: str | None = None,
    check: bool = False,
    spec_path: str | Path | None = None,
    base_dir: str | Path | None = None,
    engine: str = "auto",
) -> list[Path]:
    """渲染 PPT Master SVG 或卡片 SVG 为 PNG，并可选执行客观质量门禁校验。

    :param src: 单个 .svg 文件、包含 SVG 的目录或项目目录（默认自发现）
    :param out: 输出目录或单文件路径（默认自适应推导为 render 或 render_cards）
    :param scale: 渲染缩放比例（默认 1.0）
    :param only: 过滤文件名子串
    :param check: 是否在渲染完成后执行客观质量门禁校验 (qa_layout.py / qa_cards.py)
    :param spec_path: 可选指定的规范文件 (spec_lock.md 或 card_spec.md)
    :param base_dir: 基础目录（默认当前工作目录）
    :param engine: 渲染引擎 auto|playwright|cli（默认 auto，playwright 失败自动降级 cli）
    :return: 渲染生成的 PNG 文件 Path 列表
    """
    files, out_dir = resolve_targets(src, out, base_dir=base_dir)
    _warn_if_tmp_full()

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
            _render_page(f, dst, scale, engine)
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
    ap.add_argument("--engine", default="auto", choices=("auto", "playwright", "cli"),
                    help="渲染引擎：auto=playwright 失败自动降级 chromium CLI（默认）")
    args = ap.parse_args(argv)

    try:
        render_svg(
            src=args.src,
            out=args.out,
            scale=args.scale,
            only=args.only,
            check=args.check,
            spec_path=args.spec,
            engine=args.engine,
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
