#!/usr/bin/env python3
# -*- coding: utf-8
"""
video_assemble.py -- 视频分镜组装与项目发现

从 make_video.py 拆出: run_cmd / commit_video_pair / probe_duration /
ensure_page_images / resolve_project_dir。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

try:
    from scripts.check_page_map import find_svg_dir
except ImportError:
    try:
        from check_page_map import find_svg_dir
    except ImportError:
        find_svg_dir = None


try:
    from scripts.render_svg import render_one
except ImportError:
    try:
        from render_svg import render_one
    except ImportError:
        render_one = None


def _find_svg_dir(p: Path | str, base_dir: str | Path | None = None) -> Path | None:
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    target = Path(p)
    target = (base / target).resolve() if not target.is_absolute() else target.resolve()
    if find_svg_dir is not None:
        try:
            return find_svg_dir(target, base_dir=base)
        except TypeError:
            return find_svg_dir(target)
    # fallback: 优先按数字版本最高 (svg_output_v4 > svg_output_v3 > svg_output)
    cands = sorted(
        [d for d in target.glob("svg_output*") if d.is_dir() and any(d.glob("*.svg"))],
        key=lambda d: (
            int(m.group(1)) if (m := re.match(r"^svg_output_v(\d+)$", d.name, re.I)) else (0 if d.name == "svg_output" else -1)
        ),
        reverse=True,
    )
    if cands:
        return cands[0]
    if any(target.glob("*.svg")):
        return target
    return None

def run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=check)

def commit_video_pair(
    staged_video: Path | str,
    staged_srt: Path | str,
    output_video: Path | str,
    output_srt: Path | str,
    base_dir: str | Path | None = None,
) -> None:
    """同时提交 MP4/SRT；任一替换失败都恢复原有 pair。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()

    def _resolve(p: Path | str) -> Path:
        path = Path(p)
        return (base / path).resolve() if not path.is_absolute() else path.resolve()

    s_video = _resolve(staged_video)
    s_srt = _resolve(staged_srt)
    out_video = _resolve(output_video)
    out_srt = _resolve(output_srt)

    out_video.parent.mkdir(parents=True, exist_ok=True)
    out_srt.parent.mkdir(parents=True, exist_ok=True)

    backups: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        for target in (out_video, out_srt):
            if target.exists():
                backup = target.with_name(f".{target.name}.backup")
                if backup.exists():
                    backup.unlink()
                os.replace(target, backup)
                backups.append((target, backup))
        for staged, target in ((s_video, out_video), (s_srt, out_srt)):
            os.replace(staged, target)
            installed.append(target)
    except Exception:
        for target in installed:
            target.unlink(missing_ok=True)
        for target, backup in reversed(backups):
            if backup.exists():
                os.replace(backup, target)
        raise
    else:
        for _, backup in backups:
            backup.unlink(missing_ok=True)

def probe_duration(media_path: Path | str, base_dir: str | Path | None = None) -> float:
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    p = Path(media_path)
    p = (base / p).resolve() if not p.is_absolute() else p.resolve()
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(p),
    ]
    res = run_cmd(cmd)
    return float(res.stdout.strip())

def ensure_page_images(
    project_dir: Path | str,
    pages: list[str],
    format_ratio: str,
    work_dir: Path | str,
    base_dir: str | Path | None = None,
) -> dict[str, Path]:
    """根据画面比例渲染或准备高分辨率静态底图。"""
    global render_one
    if render_one is None:
        from render_svg import render_one

    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    p_proj = Path(project_dir)
    p_proj = (base / p_proj).resolve() if not p_proj.is_absolute() else p_proj.resolve()
    p_work = Path(work_dir)
    p_work = (base / p_work).resolve() if not p_work.is_absolute() else p_work.resolve()

    out_images = {}
    if format_ratio == "16:9":
        # 横版：基于版本最高 svg_output*/*.svg 渲染 1920×1080 (scale 1.5)
        cand_svg = _find_svg_dir(p_proj, base_dir=base)
        if cand_svg and cand_svg.is_dir() and any(cand_svg.glob("*.svg")):
            src_dir = cand_svg
        else:
            src_dir = p_proj / "svg_output"
        scale = 1.5
    else:
        # 竖版：基于 cards/*.svg 渲染 1080×1350 或 1080×1920
        src_dir = p_proj / "cards"
        scale = 1.0

    if not src_dir.exists():
        raise FileNotFoundError(f"源画面目录不存在: {src_dir}")

    p_work.mkdir(parents=True, exist_ok=True)

    for p in pages:
        svg_file = src_dir / f"{p}.svg"
        if not svg_file.exists():
            # 尝试模糊匹配 (比如前缀 01_ 等)
            matches = list(src_dir.glob(f"{p}*.svg"))
            if matches:
                svg_file = matches[0]
            else:
                raise FileNotFoundError(f"未找到对应页面 SVG: {p} in {src_dir}")

        dest_png = p_work / f"{p}.png"
        render_one(svg_file, dest_png, scale=scale)
        out_images[p] = dest_png
    return out_images

def resolve_project_dir(
    project_arg: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> Path:
    """自适应探测包含视频合成资源的项目目录。

    保留显式 project 参数行为；
    未传时从当前目录或 projects/ 下安全发现唯一包含 voiceover/notes 及 SVG 画布的项目。
    """
    if project_arg is not None and str(project_arg).strip() != "":
        proj = Path(project_arg)
        if not proj.is_absolute() and base_dir is not None:
            proj = (Path(base_dir) / proj).resolve()
        else:
            proj = proj.resolve()
        if not proj.exists():
            raise FileNotFoundError(f"指定的项目目录不存在: {project_arg}")
        if proj.is_file():
            proj = proj.parent
        if (
            proj.name in ("images", "svg_output", "render_cards", "render", "notes", "output", "cards")
            or proj.name.startswith("svg_output")
            or proj.name.startswith("render")
        ) and proj.is_dir():
            proj = proj.parent
        return proj

    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()

    def is_valid_project(p: Path) -> bool:
        if not p.is_dir():
            return False
        has_vo = (p / "voiceover.json").is_file() or (
            (p / "notes").is_dir() and any((p / "notes").glob("*.md"))
        )
        cand_svg = _find_svg_dir(p)
        has_svg = (
            (cand_svg is not None and any(cand_svg.glob("*.svg")))
            or ((p / "cards").is_dir() and any((p / "cards").glob("*.svg")))
        )
        return has_vo and has_svg

    # 1. 当前目录本身就是有效项目目录
    if is_valid_project(base):
        return base

    # 若传入或当前位于文件或子目录 (如 svg_output/、render/、render_cards/、images/、notes/、output/)
    if base.is_file() and is_valid_project(base.parent):
        return base.parent

    if (
        base.name in ("images", "svg_output", "render_cards", "render", "notes", "output", "cards")
        or base.name.startswith("svg_output")
        or base.name.startswith("render")
    ) and is_valid_project(base.parent):
        return base.parent

    # 2. 从 projects/ 目录下安全发现
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
            if sub.is_dir() and is_valid_project(sub):
                r_sub = sub.resolve()
                if r_sub not in seen:
                    seen.add(r_sub)
                    found.append(r_sub)
        if found:
            break

    if len(found) == 1:
        return found[0]
    elif len(found) == 0:
        raise FileNotFoundError(
            "未在当前目录或 projects/ 下发现包含解说稿及 SVG 画布的有效项目，请显式指定 project 参数"
        )
    else:
        names = ", ".join(p.name for p in found)
        raise ValueError(
            f"发现多个有效项目 ({names})，无法安全确定，请显式指定 project 参数"
        )

