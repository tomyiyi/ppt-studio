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
import tempfile
from pathlib import Path

try:
    from scripts.qa_preview import run_qa_slide_preview, run_qa_preview, qa_preview
except ImportError:
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from scripts.qa_preview import run_qa_slide_preview, run_qa_preview, qa_preview
    except ImportError:
        run_qa_slide_preview = None
        run_qa_preview = None
        qa_preview = None

try:
    from scripts.check_page_map import find_svg_dir, resolve_project_dir as _cpm_resolve_project_dir
except ImportError:
    try:
        from check_page_map import find_svg_dir, resolve_project_dir as _cpm_resolve_project_dir
    except ImportError:
        find_svg_dir = None
        _cpm_resolve_project_dir = None


def resolve_project_dir(
    project_arg: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> Path:
    """自适应解析项目根目录（支持从子目录 images、svg_output*、cards 等或文件回退）。"""
    if _cpm_resolve_project_dir is not None:
        try:
            return _cpm_resolve_project_dir(project_arg, base_dir=base_dir)
        except TypeError:
            return _cpm_resolve_project_dir(project_arg)
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    if project_arg is not None and str(project_arg).strip() not in ("", "."):
        p = Path(project_arg)
        if not p.is_absolute():
            p = (base / p).resolve()
        else:
            p = p.resolve()
    else:
        p = base
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

try:
    from scripts.spec_resolve import resolve_spec
except ImportError:
    try:
        from spec_resolve import resolve_spec
    except ImportError:
        resolve_spec = None


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
        # 兼容 URL query 或 fragment (如 photo.png?v=1)
        clean_href = href.split("?")[0].split("#")[0]
        p = Path(clean_href)
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


def resolve_project_meta(src_dir: Path) -> dict:
    """从 spec_lock.md、card_spec.md 或封面 SVG 中提取品牌色板与项目大标题。"""
    meta = {
        "title": "智流 OS",
        "accent": "#6E7BFF",
        "background": "#08090C",
        "surface": "#12131A",
        "divider": "#23242E",
        "primary_text": "#F7F7F9",
        "tertiary_text": "#7F8090",
    }
    proj_dir = resolve_project_dir(src_dir)
    if proj_dir == src_dir and (
        src_dir.name in ("svg_output", "cards") or src_dir.name.startswith("svg_output")
    ):
        proj_dir = src_dir.parent

    found_spec_title = False
    found_colors: set[str] = set()
    cand_specs: list[Path] = []
    if resolve_spec is not None:
        try:
            s = resolve_spec(proj_dir)
            if s and s.is_file():
                cand_specs.append(s)
        except Exception:
            pass
    for spec_name in ("card_spec.md", "spec_lock.md"):
        p = proj_dir / spec_name
        if p.is_file() and p not in cand_specs:
            cand_specs.append(p)

    for spec_path in cand_specs:
        if spec_path.is_file():
            try:
                content = spec_path.read_text(encoding="utf-8")
                # 提取色彩配置
                if "accent" not in found_colors:
                    m_acc = re.search(r"[-*]?\s*accent\s*[:=\s]\s*(#[0-9a-fA-F]{3,8})", content)
                    if m_acc:
                        meta["accent"] = m_acc.group(1).upper()
                        found_colors.add("accent")
                if "background" not in found_colors:
                    m_bg = re.search(r"[-*]?\s*background\s*[:=\s]\s*(#[0-9a-fA-F]{3,8})", content)
                    if not m_bg:
                        m_bg = re.search(r"[-*]?\s*bg\s*[:=\s]\s*(#[0-9a-fA-F]{3,8})", content)
                    if m_bg:
                        meta["background"] = m_bg.group(1).upper()
                        found_colors.add("background")
                if "surface" not in found_colors:
                    m_surf = re.search(r"[-*]?\s*surface\s*[:=\s]\s*(#[0-9a-fA-F]{3,8})", content)
                    if m_surf:
                        meta["surface"] = m_surf.group(1).upper()
                        found_colors.add("surface")
                if "divider" not in found_colors:
                    m_div = re.search(r"[-*]?\s*(?:divider|rule)\s*[:=\s]\s*(#[0-9a-fA-F]{3,8})", content)
                    if m_div:
                        meta["divider"] = m_div.group(1).upper()
                        found_colors.add("divider")

                # 提取标题
                if not found_spec_title:
                    m_title = re.search(r"^[-*]?\s*title\s*[:=]\s*(.+)", content, re.M)
                    if m_title:
                        cand = m_title.group(1).split("#")[0].strip().strip('"\'')
                        # 排除 typography 中的字号定义（如 title: 32）
                        if cand and not cand.isdigit() and len(cand) <= 40:
                            meta["title"] = cand
                            found_spec_title = True
                    if not found_spec_title:
                        m_obj = re.search(r"^[-*]?\s*objective\s*[:=]\s*(.+)", content, re.M)
                        if m_obj:
                            cand_obj = m_obj.group(1).split("#")[0].strip().strip('"\'')
                            m_launch = re.search(r"发布(.+?)(?:[，,。]|$)", cand_obj)
                            if m_launch:
                                meta["title"] = m_launch.group(1).strip()
                                found_spec_title = True
            except Exception:
                pass

    if not found_spec_title and src_dir.is_dir():
        svg_cands = sorted(src_dir.glob("*.svg"))
        if svg_cands:
            cover_svg = next(
                (f for f in svg_cands if "cover" in f.name.lower() or f.name.startswith("01")),
                svg_cands[0],
            )
            try:
                svg_txt = cover_svg.read_text(encoding="utf-8")
                m_text = re.search(
                    r'<text\b[^>]*\bfont-size=["\'](?:9[0-9]|1[0-9]{2})["\'][^>]*>(?:<tspan[^>]*>)?([^<]+)',
                    svg_txt,
                )
                if m_text:
                    cand_title = m_text.group(1).strip()
                    if cand_title:
                        meta["title"] = cand_title
                        found_spec_title = True
            except Exception:
                pass

    if (
        not found_spec_title
        and proj_dir.name not in ("", ".", "ppt-studio", "cards")
        and not proj_dir.name.startswith("svg_output")
    ):
        meta["title"] = proj_dir.name.replace("-", " ").title()

    return meta


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
    cards: bool = False,
) -> Path:
    """自适应探测包含 SVG 画布的源目录。

    1. 保留显式 src 参数行为：
       - 若是目录且直接包含 *.svg，直接返回（若指定 cards 且 cards/ 存在则优先 cards/）；
       - 若是项目目录：
         - cards=True 时优先查找 cards/*.svg，次选 svg_output*/*.svg（按版本优先级）；
         - cards=False 时优先查找 svg_output*/*.svg（按版本优先级），次选 cards/*.svg；
       - 路径不存在则抛出 FileNotFoundError。
    2. 未传时从当前目录或 projects/ 下安全自动发现唯一有效项目。
    """
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()

    def has_svg_files(p: Path) -> bool:
        return p.is_dir() and any(p.glob("*.svg"))

    def has_cards(p: Path) -> bool:
        return has_svg_files(p / "cards")

    if src_arg is not None and str(src_arg).strip() not in ("", "-"):
        p = Path(src_arg)
        if not p.is_absolute() and base_dir is not None:
            p = (Path(base_dir) / p).resolve()
        else:
            p = p.resolve()
        if not p.exists():
            raise FileNotFoundError(f"指定的源目录不存在: {src_arg}")

        if p.is_file():
            if p.suffix.lower() == ".svg":
                return p.parent.resolve()
            proj = resolve_project_dir(p, base_dir=base)
            if cards:
                if has_cards(proj):
                    return (proj / "cards").resolve()
                if has_svg_files(proj):
                    return proj.resolve()
                cand_svg = _find_svg_dir(proj)
                if cand_svg and cand_svg != proj and has_svg_files(cand_svg):
                    return cand_svg.resolve()
            else:
                cand_svg = _find_svg_dir(proj)
                if cand_svg and cand_svg != proj and has_svg_files(cand_svg):
                    return cand_svg.resolve()
                if has_svg_files(proj):
                    return proj.resolve()
                if has_cards(proj):
                    return (proj / "cards").resolve()
            raise FileNotFoundError(f"在文件关联项目 {proj} 下未找到任何 SVG 文件")

        if cards:
            if has_cards(p):
                return (p / "cards").resolve()
            if has_svg_files(p):
                return p
            cand_svg = _find_svg_dir(p)
            if cand_svg and cand_svg != p and has_svg_files(cand_svg):
                return cand_svg.resolve()
            proj = resolve_project_dir(p, base_dir=base)
            if proj != p:
                if has_cards(proj):
                    return (proj / "cards").resolve()
                cand_svg = _find_svg_dir(proj)
                if cand_svg and cand_svg != proj and has_svg_files(cand_svg):
                    return cand_svg.resolve()
                if has_svg_files(proj):
                    return proj.resolve()
            return p

        # cards == False
        if (p.name == "svg_output" or p.name.startswith("svg_output") or p.name == "cards") and has_svg_files(p):
            return p
        cand_svg = _find_svg_dir(p)
        if cand_svg and cand_svg != p and has_svg_files(cand_svg):
            return cand_svg.resolve()
        if has_svg_files(p):
            return p
        if has_cards(p):
            return (p / "cards").resolve()
        proj = resolve_project_dir(p, base_dir=base)
        if proj != p:
            cand_svg = _find_svg_dir(proj)
            if cand_svg and cand_svg != proj and has_svg_files(cand_svg):
                return cand_svg.resolve()
            if has_svg_files(proj):
                return proj.resolve()
            if has_cards(proj):
                return (proj / "cards").resolve()
        return p

    # 未指定 src_arg 时自动发现
    cand_proj = resolve_project_dir(base, base_dir=base)
    if cand_proj != base:
        if cards:
            if has_cards(cand_proj):
                return (cand_proj / "cards").resolve()
            if has_svg_files(cand_proj):
                return cand_proj.resolve()
        else:
            cand_svg = _find_svg_dir(cand_proj)
            if cand_svg and has_svg_files(cand_svg):
                return cand_svg.resolve()
            if has_svg_files(cand_proj):
                return cand_proj.resolve()
            if has_cards(cand_proj):
                return (cand_proj / "cards").resolve()
    if cards:
        if base.name == "cards" and has_svg_files(base):
            return base
        if not (base / "projects").is_dir() and has_cards(base):
            return (base / "cards").resolve()
    else:
        if (base.name == "svg_output" or base.name.startswith("svg_output") or base.name == "cards") and has_svg_files(base):
            return base
        if not (base / "projects").is_dir():
            cand_base = _find_svg_dir(base)
            if cand_base and has_svg_files(cand_base) and (base.name != "ppt-studio" or cand_base != base):
                return cand_base.resolve()
            if has_cards(base):
                return (base / "cards").resolve()

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
            if not sub.is_dir():
                continue
            if cards:
                if has_cards(sub):
                    r_sub = (sub / "cards").resolve()
                    if r_sub not in seen:
                        seen.add(r_sub)
                        found.append(r_sub)
            else:
                sub_svg = _find_svg_dir(sub)
                if sub_svg and has_svg_files(sub_svg) and sub_svg != sub:
                    r_sub = sub_svg.resolve()
                    if r_sub not in seen:
                        seen.add(r_sub)
                        found.append(r_sub)
                elif (sub / "svg_output").is_dir() and has_svg_files(sub / "svg_output"):
                    r_sub = (sub / "svg_output").resolve()
                    if r_sub not in seen:
                        seen.add(r_sub)
                        found.append(r_sub)
                elif has_cards(sub):
                    r_sub = (sub / "cards").resolve()
                    if r_sub not in seen:
                        seen.add(r_sub)
                        found.append(r_sub)
        if found:
            break

    if not found:
        if cards and has_cards(base):
            return (base / "cards").resolve()
        elif not cards:
            cand_base = _find_svg_dir(base)
            if cand_base and has_svg_files(cand_base) and (base.name != "ppt-studio" or cand_base != base):
                return cand_base.resolve()
            elif has_cards(base):
                return (base / "cards").resolve()

    if len(found) == 1:
        return found[0]
    elif len(found) == 0:
        target_name = "cards/*.svg" if cards else "svg_output/*.svg"
        raise FileNotFoundError(
            f"未在当前目录或 projects/ 下发现包含 {target_name} 的有效项目，请显式指定 src 参数"
        )
    else:
        names = ", ".join(
            p.parent.name if (p.name.startswith("svg_output") or p.name == "cards") else p.name
            for p in found
        )
        target_name = "cards" if cards else "svg_output"
        raise ValueError(
            f"发现多个包含 {target_name} 的有效项目 ({names})，无法安全确定，请显式指定 src 参数"
        )


def build_preview(
    src: str | Path | None = None,
    out: str | Path = "output/预览.html",
    title: str | None = None,
    cards: bool = False,
    check: bool = False,
    base_dir: str | Path | None = None,
) -> Path:
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    src_path = resolve_src_dir(src, base_dir=base, cards=cards)
    out_p = Path(out)
    out_path = (base / out_p).resolve() if not out_p.is_absolute() else out_p.resolve()

    if not src_path.is_dir():
        raise FileNotFoundError(f"未找到源目录: {src_path}")

    svg_files = sorted(src_path.glob("*.svg"))
    if not svg_files:
        raise FileNotFoundError(f"目录内无 SVG 文件: {src_path}")

    svgs = []
    aspects = []
    for f in svg_files:
        t = f.read_text(encoding="utf-8")
        t = re.sub(r"\s*<\?xml[^>]*\?>", "", t)
        t = inline_images(t, src_path)
        svgs.append(t)
        aspects.append(extract_aspect(t))

    # 画幅与纵横比跨页一致性检测
    w0, h0 = aspects[0] if aspects else (1280.0, 720.0)
    r0 = w0 / h0 if h0 > 0 else (16.0 / 9.0)
    for f, (w_i, h_i) in zip(svg_files[1:], aspects[1:]):
        r_i = w_i / h_i if h_i > 0 else r0
        if abs(r_i - r0) / r0 > 0.05:
            print(
                f"  [warn] 跨页画幅比例不统一: 首页 {w0:.0f}×{h0:.0f} (比值 {r0:.3f}) vs {f.name} {w_i:.0f}×{h_i:.0f} (比值 {r_i:.3f})"
            )

    w, h = w0, h0
    vw_h = (h / w) * 100.0
    vh_w = (w / h) * 100.0

    slides = "\n".join(f'  <div class="slide{" active" if i == 0 else ""}">{s}</div>' for i, s in enumerate(svgs))
    n = len(svgs)

    meta = resolve_project_meta(src_path)
    is_cards_mode = cards or (src_path.name == "cards")

    if title is None or not str(title).strip():
        proj_title = meta.get("title", "智流 OS")
        sub_title = "卡片集" if is_cards_mode else "幻灯片预览"
        final_title = f"{proj_title} · {sub_title}"
    else:
        final_title = str(title).strip()

    bg = meta.get("background", "#08090C")
    divider = meta.get("divider", "#23242E")
    accent = meta.get("accent", "#6E7BFF")
    primary_text = meta.get("primary_text", "#F7F7F9")
    tertiary_text = meta.get("tertiary_text", "#7F8090")

    def _hex_to_rgba(hex_code: str, alpha: float) -> str:
        h_str = hex_code.lstrip("#")
        if len(h_str) == 6:
            try:
                r_c, g_c, b_c = int(h_str[0:2], 16), int(h_str[2:4], 16), int(h_str[4:6], 16)
                return f"rgba({r_c},{g_c},{b_c},{alpha})"
            except ValueError:
                pass
        return f"rgba(110,123,255,{alpha})"

    hover_bg = _hex_to_rgba(accent, 0.3)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{final_title}</title><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:{bg};font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow:hidden}}
.stage{{width:100vw;height:100vh;display:flex;align-items:center;justify-content:center}}
.slide{{display:none;width:100vw;height:{vw_h:.2f}vw;max-height:100vh;max-width:{vh_w:.2f}vh}}
.slide.active{{display:block}}.slide svg{{width:100%;height:100%;display:block}}
.nav{{position:fixed;bottom:18px;right:22px;display:flex;gap:10px;z-index:50}}
.nav button{{background:rgba(18,19,26,.85);border:1px solid {divider};color:{primary_text};padding:8px 16px;border-radius:6px;cursor:pointer;font-size:13px;backdrop-filter:blur(6px)}}
.nav button:hover{{background:{hover_bg};border-color:{accent}}}
.ind{{position:fixed;bottom:24px;left:22px;color:{tertiary_text};font-size:12px;letter-spacing:2px}}
.hint{{position:fixed;top:14px;left:22px;color:{tertiary_text};font-size:12px}}
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
    fd, staged_name = tempfile.mkstemp(prefix=f".{out_path.name}.", dir=out_path.parent)
    os.close(fd)
    staged_path = Path(staged_name)
    try:
        staged_path.write_text(html, encoding="utf-8")
    except Exception:
        staged_path.unlink(missing_ok=True)
        raise
    print(f"prepared: {out_path} {staged_path.stat().st_size} bytes, {n} slides")

    if check:
        if run_qa_slide_preview is not None:
            try:
                ok = (
                    run_qa_slide_preview(staged_path, base_dir=base)
                    if base_dir is not None
                    else run_qa_slide_preview(staged_path)
                )
            except TypeError:
                ok = run_qa_slide_preview(staged_path)
            if not ok:
                staged_path.unlink(missing_ok=True)
                raise RuntimeError(f"翻页预览客观质量门禁未通过: {out_path}")
            print(f"  [门禁] ✓ 翻页预览客观质量门禁通过")
        else:
            print("  [warn] 未导入 run_qa_slide_preview，跳过门禁检查")

    try:
        os.replace(staged_path, out_path)
    except Exception:
        staged_path.unlink(missing_ok=True)
        raise
    print(f"saved: {out_path} {out_path.stat().st_size} bytes, {n} slides")
    return out_path


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="把若干 SVG 打包成单文件 HTML 翻页预览")
    parser.add_argument(
        "src",
        nargs="?",
        default=None,
        help="包含 SVG 文件的目录或项目根目录（默认安全自动发现）",
    )
    parser.add_argument("out", nargs="?", default="output/预览.html", help="输出 HTML 路径")
    parser.add_argument("title", nargs="?", default=None, help="HTML 页面标题（默认智能推导）")
    parser.add_argument("--cards", action="store_true", help="优先打包 cards/ 下的竖版卡片")
    parser.add_argument("--check", action="store_true", help="构建完成后执行客观质量门禁校验")
    parser.add_argument("--title-override", dest="opt_title", default=None, help="显式指定标题（覆盖位置参数）")
    parser.add_argument(
        "--base-dir",
        default=None,
        help="指定基础工作目录 (默认: 当前工作目录)",
    )
    args = parser.parse_args(argv)

    effective_base = (
        Path(args.base_dir).resolve()
        if args.base_dir
        else (Path(base_dir).resolve() if base_dir else Path.cwd().resolve())
    )
    chosen_title = args.opt_title if args.opt_title is not None else args.title
    try:
        build_preview(
            src=args.src,
            out=args.out,
            title=chosen_title,
            cards=args.cards,
            check=args.check,
            base_dir=effective_base,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as err:
        print(f"[err] {err}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
