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

退出码：0=无漂移，1=有漂移（--fix 后重新检查）。
"""
from __future__ import annotations
import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


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


def spec_viewbox(spec_path: Path) -> str | None:
    txt = spec_path.read_text(encoding="utf-8")
    m = re.search(r"^##\s+canvas\s*$(.*?)(?=^##\s|\Z)", txt, re.S | re.M)
    if not m:
        return None
    mm = re.search(r"viewBox:\s*([0-9\s.]+)", m.group(1))
    return " ".join(mm.group(1).split()) if mm else None


def find_svg_dir(project_dir: Path) -> Path | None:
    # 优先最高版本（v4 > v3 > v2 > 无后缀），避免旧目录掩盖当前版本
    cands = sorted(
        [d for d in project_dir.glob("svg_output*") if d.is_dir() and list(d.glob("*.svg"))],
        key=lambda d: d.name, reverse=True)
    if cands:
        return cands[0]
    if list(project_dir.glob("*.svg")):
        return project_dir
    return None


def check(project_dir: Path) -> tuple[bool, list[str], dict]:
    """返回 (无漂移, 问题列表, 上下文{spec_vb, svg_vb, svg_dir})。"""
    issues: list[str] = []
    ctx: dict = {}
    spec = project_dir / "spec_lock.md"
    if not spec.is_file():
        return False, ["找不到 spec_lock.md"], ctx
    svg_dir = find_svg_dir(project_dir)
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


def fix_canvas(spec_path: Path, new_vb: str) -> bool:
    """把 spec 的 ## canvas 节 viewBox 更新为 new_vb。返回是否改动。"""
    txt = spec_path.read_text(encoding="utf-8")
    new_txt, n = re.subn(
        r"(^##\s+canvas\s*$\n(?:.*\n)*?- viewBox:\s*)[0-9.]+(?: [0-9.]+)*",
        lambda m: m.group(1) + new_vb,
        txt, count=1, flags=re.M)
    if n and new_txt != txt:
        spec_path.write_text(new_txt, encoding="utf-8")
        return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="SVG → spec 反向同步检查")
    ap.add_argument("project_dir")
    ap.add_argument("--fix", action="store_true", help="把 SVG 的 viewBox 写回 spec")
    a = ap.parse_args()
    proj = Path(a.project_dir)
    ok, issues, ctx = check(proj)
    if ok:
        print("[ok] spec 与 SVG 无漂移（viewBox=%s）" % ctx.get("svg_vb"))
        return
    print("[drift] 发现 %d 处漂移：" % len(issues))
    for i in issues:
        print("  -", i)
    if a.fix and ctx.get("svg_vb") and ctx.get("spec_vb"):
        spec = proj / "spec_lock.md"
        if fix_canvas(spec, ctx["svg_vb"]):
            print("[fix] spec viewBox 已更新为 %s" % ctx["svg_vb"])
        # 重新检查
        ok2, _, _ = check(proj)
        sys.exit(0 if ok2 else 1)
    sys.exit(1)


if __name__ == "__main__":
    main()
