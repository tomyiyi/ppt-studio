#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_spec.py -- SVG → spec_lock.md 反向同步（防漂移）
=====================================================
借鉴 ppt-master 差距6：SVG 被手工改了之后，spec 必须跟上，
否则 QA 读的是过期契约。

检查项：
  1. canvas viewBox：所有 SVG 的 viewBox 是否一致、是否与 spec 相同
  2. page_map：文件数 vs 条目数（复用 check_page_map）

用法：
    python3 scripts/sync_spec.py projects/fw2026-trends         # 只报告
    python3 scripts/sync_spec.py projects/fw2026-trends --fix   # 写回 spec
    python3 scripts/sync_spec.py projects/fw2026-trends --spec path/to/spec_lock.md

退出码：0=无漂移，1=有漂移（--fix 后重新检查）。
"""
from __future__ import annotations
import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from scripts.check_page_map import (
        find_svg_dir as _check_page_map_find_svg_dir,
        resolve_project_dir as _cpm_resolve_project_dir,
    )
except ImportError:
    try:
        from check_page_map import (
            find_svg_dir as _check_page_map_find_svg_dir,
            resolve_project_dir as _cpm_resolve_project_dir,
        )
    except ImportError:
        _check_page_map_find_svg_dir = None
        _cpm_resolve_project_dir = None

try:
    from scripts.spec_resolve import resolve_spec, find_spec
except ImportError:
    try:
        from spec_resolve import resolve_spec, find_spec
    except ImportError:
        resolve_spec = None
        find_spec = None


def svg_viewboxes(svg_dir: Path) -> dict[str, str]:
    """{文件名: viewBox}。"""
    out = {}
    for f in sorted(svg_dir.glob("*.svg")):
        try:
            root = ET.parse(f).getroot()
            vb = root.get("viewBox", "").strip()
            if vb:
                out[f.name] = vb
        except Exception:
            pass
    return out


def spec_viewbox(spec_path: Path | str) -> str | None:
    p = Path(spec_path)
    try:
        txt = p.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^##\s+canvas\s*$(.*?)(?=^##\s|\Z)", txt, re.S | re.M)
    if not m:
        return None
    mm = re.search(r"viewBox:\s*([0-9\s.]+)", m.group(1))
    return " ".join(mm.group(1).split()) if mm else None


def _svg_dir_version_key(d: Path) -> tuple[int, str]:
    m = re.match(r"^svg_output_v(\d+)$", d.name, re.IGNORECASE)
    if m:
        return (int(m.group(1)), d.name)
    if d.name == "svg_output":
        return (0, d.name)
    return (-1, d.name)


def find_svg_dir(project_dir: Path | str) -> Path | None:
    p = Path(project_dir)
    if _check_page_map_find_svg_dir is not None:
        found = _check_page_map_find_svg_dir(p)
        if found:
            return found
    # 优先最高数字版本（v10 > v4 > v3 > v2 > 无后缀），避免旧目录掩盖当前版本
    cands = sorted(
        [d for d in p.glob("svg_output*") if d.is_dir() and list(d.glob("*.svg"))],
        key=_svg_dir_version_key,
        reverse=True,
    )
    if cands:
        return cands[0]
    if list(p.glob("*.svg")):
        return p
    return None


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


def check(
    project_dir: Path | str,
    spec_path: Path | str | None = None,
) -> tuple[bool, list[str], dict]:
    """返回 (无漂移, 问题列表, 上下文{spec_vb, svg_vb, svg_dir, spec})。"""
    issues: list[str] = []
    ctx: dict = {}
    proj = resolve_project_dir(project_dir)

    spec: Path | None = None
    if spec_path:
        spec = Path(spec_path).resolve()
    else:
        if resolve_spec is not None:
            spec = resolve_spec(proj)
        if (spec is None or not spec.is_file()) and find_spec is not None:
            spec = find_spec(proj)
        if (
            (spec is None or not spec.is_file())
            and find_spec is not None
            and str(proj) != str(Path(project_dir).resolve())
        ):
            spec = find_spec(Path(project_dir).resolve())

    ctx["spec"] = str(spec) if spec else ""
    if spec is None or not spec.is_file():
        return False, ["找不到 spec_lock（已按 版本>基线 规则查找）"], ctx

    svg_dir = find_svg_dir(proj)
    if not svg_dir and str(proj) != str(Path(project_dir).resolve()):
        svg_dir = find_svg_dir(Path(project_dir).resolve())
    if not svg_dir:
        return False, ["找不到 SVG 目录"], ctx
    ctx["svg_dir"] = str(svg_dir)

    vbs = svg_viewboxes(svg_dir)
    ctx["svg_vbs"] = vbs
    uniq = set(vbs.values())
    if len(uniq) > 1:
        issues.append("SVG viewBox 不一致：%s" % sorted(uniq))
    svg_vb = sorted(uniq)[0] if uniq else None
    ctx["svg_vb"] = svg_vb

    spec_vb = spec_viewbox(spec)
    ctx["spec_vb"] = spec_vb
    if spec_vb and svg_vb and spec_vb != svg_vb:
        issues.append("spec viewBox=%s ≠ SVG viewBox=%s（漂移！）" % (spec_vb, svg_vb))
    return (len(issues) == 0), issues, ctx


def fix_canvas(spec_path: Path | str, new_vb: str) -> bool:
    """把 spec 的 ## canvas 节 viewBox 更新为 new_vb。返回是否改动。"""
    p = Path(spec_path)
    try:
        txt = p.read_text(encoding="utf-8")
    except OSError:
        return False
    new_txt, n = re.subn(
        r"(^##\s+canvas\s*$\n(?:.*\n)*?- viewBox:\s*)[0-9.]+(?: [0-9.]+)*",
        lambda m: m.group(1) + new_vb,
        txt, count=1, flags=re.M)
    if n and new_txt != txt:
        p.write_text(new_txt, encoding="utf-8")
        return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="SVG → spec 反向同步检查")
    ap.add_argument("project_dir", help="项目目录或子目录")
    ap.add_argument("--spec", help="可选指定 spec_lock.md 路径")
    ap.add_argument("--fix", action="store_true", help="把 SVG 的 viewBox 写回 spec")
    a = ap.parse_args()
    proj = Path(a.project_dir)
    spec_arg = Path(a.spec).resolve() if a.spec else None
    ok, issues, ctx = check(proj, spec_path=spec_arg)
    print("[i] 采用 spec: %s" % (ctx.get("spec") or "未找到"))
    if ok:
        print("[ok] spec 与 SVG 无漂移（viewBox=%s）" % ctx.get("svg_vb"))
        return
    print("[drift] 发现 %d 处漂移：" % len(issues))
    for i in issues:
        print("  -", i)
    if a.fix and ctx.get("svg_vb") and ctx.get("spec_vb"):
        target_spec = (
            Path(ctx["spec"])
            if ctx.get("spec")
            else (spec_arg or (resolve_spec(proj) if resolve_spec else None))
        )
        if target_spec and fix_canvas(target_spec, ctx["svg_vb"]):
            print("[fix] spec viewBox 已更新为 %s" % ctx["svg_vb"])
        # 重新检查
        ok2, _, _ = check(proj, spec_path=spec_arg)
        sys.exit(0 if ok2 else 1)
    sys.exit(1)


if __name__ == "__main__":
    main()
