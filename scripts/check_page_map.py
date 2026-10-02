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


def parse_page_map(spec_path: Path) -> dict:
    """解析 ## page_map 节，返回 {页码: {role, rhythm}}。页码如 P01。"""
    try:
        txt = spec_path.read_text(encoding="utf-8")
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


def find_svg_dir(project_dir: Path) -> Path | None:
    # 优先最高版本（v4 > v3 > v2 > 无后缀），避免旧目录掩盖当前版本；按数字版本降序排序
    cands = sorted(
        [d for d in project_dir.glob("svg_output*") if d.is_dir() and list(d.glob("*.svg"))],
        key=_svg_dir_version_key, reverse=True)
    if cands:
        return cands[0]
    if list(project_dir.glob("*.svg")):
        return project_dir
    return None


def check(project_dir: Path, spec_path: Path | None = None) -> tuple[bool, list[str]]:
    """返回 (是否通过, 问题列表)。"""
    issues = []
    if spec_path:
        spec = spec_path
    else:
        from scripts.spec_resolve import resolve_spec

        spec = resolve_spec(project_dir)
    if spec is None or not spec.is_file():
        return False, ["找不到 spec_lock（已按 版本>基线 规则查找）: %s" % project_dir]
    page_map = parse_page_map(spec)
    if not page_map:
        return False, ["spec_lock.md 缺少 ## page_map 节（每页一行：- P01: role=Cover, rhythm=anchor）"]
    svg_dir = find_svg_dir(project_dir)
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


def main() -> None:
    ap = argparse.ArgumentParser(description="page_map roster 完整性检查")
    ap.add_argument("project_dir", help="项目目录")
    ap.add_argument("--spec", help="显式指定 spec_lock.md")
    a = ap.parse_args()
    proj = Path(a.project_dir)
    spec = Path(a.spec) if a.spec else None
    if spec is None:
        from scripts.spec_resolve import resolve_spec
        spec = resolve_spec(proj)
    print("[i] 采用 spec: %s" % (spec if spec else "未找到"))
    ok, issues = check(proj, spec)
    if ok:
        print("[ok] roster 完整")
    else:
        print("[fail] 发现 %d 个问题：" % len(issues))
        for i in issues:
            print("  -", i)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
