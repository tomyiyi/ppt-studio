#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_page_map.py -- spec_lock.md page_map 与 SVG 文件 roster 完整性检查
==========================================================================
借鉴 ppt-master 的 "SPEC_LOCK RE-READ PER PAGE" 纪律：
  spec_lock.md 的 ## page_map 节是每页的契约（P01: role=Cover, rhythm=anchor），
  本脚本校验 svg_output 里每个文件在 page_map 有条目、page_map 里每个条目有对应文件。

用法：
    python3 scripts/check_page_map.py projects/fw2026-trends
    python3 scripts/check_page_map.py projects/fw2026-trends --spec projects/fw2026-trends/spec_lock.md

退出码：0=roster 完整，1=缺项/多余。
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def parse_page_map(spec_path: Path | str) -> dict:
    """解析 ## page_map 节，返回 {页码: {role, rhythm}}。页码如 P01。"""
    try:
        txt = Path(spec_path).read_text(encoding="utf-8")
    except OSError:
        return {}
    m = re.search(r"^##\s+page_map\s*$(.*?)(?=^##\s|\Z)", txt, re.S | re.M)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 格式：- P01: role=Cover, rhythm=anchor
        mm = re.match(r"^[-*]\s*(P\d+)\s*:\s*(.+)$", line)
        if not mm:
            continue
        page, rest = mm.group(1), mm.group(2)
        kv = dict(re.findall(r"(\w+)\s*=\s*([^,}]+)", rest))
        out[page] = {k: v.strip() for k, v in kv.items()}
    return out


def _svg_dir_version_key(d: Path) -> tuple[int, str]:
    m = re.match(r"^svg_output_v(\d+)$", d.name, re.IGNORECASE)
    if m:
        return (int(m.group(1)), d.name)
    if d.name == "svg_output":
        return (0, d.name)
    return (-1, d.name)


def find_svg_dir(project_dir: Path | str) -> Path | None:
    p = Path(project_dir)
    # 优先最高版本（v4 > v3 > v2 > 无后缀），避免旧目录掩盖当前版本；按数字版本降序排序
    cands = sorted(
        [d for d in p.glob("svg_output*") if d.is_dir() and list(d.glob("*.svg"))],
        key=_svg_dir_version_key, reverse=True)
    if cands:
        return cands[0]
    if list(p.glob("*.svg")):
        return p
    return None


def resolve_project_dir(
    project_arg: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> Path:
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


def check(
    project_dir: str | Path | None = None,
    spec_path: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> tuple[bool, list[str]]:
    """返回 (是否通过, 问题列表)。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    issues = []
    proj = resolve_project_dir(project_dir, base_dir=base)

    spec: Path | None = None
    if spec_path:
        sp = Path(spec_path)
        spec = (base / sp).resolve() if not sp.is_absolute() else sp.resolve()
    else:
        try:
            from scripts.spec_resolve import resolve_spec, find_spec
        except ImportError:
            try:
                from spec_resolve import resolve_spec, find_spec
            except ImportError:
                resolve_spec = None
                find_spec = None

        if resolve_spec is not None:
            spec = resolve_spec(proj)
        if (spec is None or not spec.is_file()) and find_spec is not None:
            spec = find_spec(proj)
        target_in = (
            (base / Path(project_dir)).resolve()
            if project_dir is not None and not Path(project_dir).is_absolute()
            else (Path(project_dir).resolve() if project_dir is not None else None)
        )
        if (
            (spec is None or not spec.is_file())
            and find_spec is not None
            and target_in is not None
            and str(proj) != str(target_in)
        ):
            spec = find_spec(target_in)

    if spec is None or not spec.is_file():
        return False, ["找不到 spec_lock（已按 版本>基线 规则查找）: %s" % project_dir]
    page_map = parse_page_map(spec)
    if not page_map:
        return False, ["spec_lock.md 缺少 ## page_map 节（每页一行：- P01: role=Cover, rhythm=anchor）"]
    svg_dir = find_svg_dir(proj)
    target_in = (
        (base / Path(project_dir)).resolve()
        if project_dir is not None and not Path(project_dir).is_absolute()
        else (Path(project_dir).resolve() if project_dir is not None else None)
    )
    if not svg_dir and target_in is not None and str(proj) != str(target_in):
        svg_dir = find_svg_dir(target_in)
    if not svg_dir:
        return False, ["找不到 SVG 目录（svg_output* 或项目根）"]
    svg_pages = set()
    for f in sorted(svg_dir.glob("*.svg")):
        mm = re.match(r"(P\d+)", f.stem.upper())
        if mm:
            svg_pages.add(mm.group(1))
        else:
            # 兼容 01_cover.svg 命名
            mm2 = re.match(r"(\d+)_", f.stem)
            if mm2:
                svg_pages.add("P%s" % mm2.group(1).zfill(2))
    map_pages = set(page_map.keys())
    for p in sorted(map_pages - svg_pages):
        issues.append("page_map 有 %s 但缺少对应 SVG 文件" % p)
    for p in sorted(svg_pages - map_pages):
        issues.append("SVG 有 %s 但 page_map 缺少条目" % p)
    return (len(issues) == 0), issues


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    ap = argparse.ArgumentParser(description="page_map roster 完整性检查")
    ap.add_argument("project_dir", nargs="?", default=None, help="项目目录")
    ap.add_argument("--spec", help="显式指定 spec_lock.md")
    ap.add_argument(
        "--base-dir",
        default=None,
        help="指定基础工作目录 (默认: 当前工作目录)",
    )
    a = ap.parse_args(argv)
    effective_base = (
        Path(a.base_dir).resolve()
        if a.base_dir
        else (Path(base_dir).resolve() if base_dir else Path.cwd().resolve())
    )
    proj = resolve_project_dir(a.project_dir, base_dir=effective_base)
    spec = None
    if a.spec:
        sp = Path(a.spec)
        spec = (effective_base / sp).resolve() if not sp.is_absolute() else sp.resolve()
    if spec is None:
        try:
            from scripts.spec_resolve import resolve_spec, find_spec
        except ImportError:
            try:
                from spec_resolve import resolve_spec, find_spec
            except ImportError:
                resolve_spec = None
                find_spec = None
        if resolve_spec is not None:
            spec = resolve_spec(proj)
        if (spec is None or not spec.is_file()) and find_spec is not None:
            spec = find_spec(proj)
        target_in = (
            (effective_base / Path(a.project_dir)).resolve()
            if a.project_dir is not None and not Path(a.project_dir).is_absolute()
            else (Path(a.project_dir).resolve() if a.project_dir is not None else None)
        )
        if (
            (spec is None or not spec.is_file())
            and find_spec is not None
            and target_in is not None
            and str(proj) != str(target_in)
        ):
            spec = find_spec(target_in)
    print("[i] 采用 spec: %s" % (spec if spec else "未找到"))
    ok, issues = check(proj, spec_path=spec, base_dir=effective_base)
    if ok:
        print("[ok] roster 完整")
    else:
        print("[fail] 发现 %d 个问题：" % len(issues))
        for i in issues:
            print("  -", i)
    if argv is None:
        sys.exit(0 if ok else 1)
    return 0 if ok else 1


if __name__ == "__main__":
    main()
