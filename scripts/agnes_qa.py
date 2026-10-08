#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agnes QA 门禁：把 agnes 版式硬指标变成 ppt-studio 的检查器。

规则来源：
- poster_grand_rules.json hard_targets:
  - negative_space_ratio: 0.35 ~ 0.60（甜点 0.45）
  - type_scale_hero_to_micro: 8 ~ 16（甜点 10）
  - spacing_rhythm_px: [8,16,24,32,48,64,96]
- learned_poster_rules.json: 字阶 10:1、留白≥35%

这是新增 QA 维度，不碰 vendor svg_quality_checker 门禁。
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

# agnes 硬指标（从 poster_grand_rules.json hard_targets 提取）
NEG_SPACE_MIN = 0.35
NEG_SPACE_MAX = 0.60
TYPE_SCALE_MIN = 8
TYPE_SCALE_MAX = 16
SPACING_RHYTHM = [8, 16, 24, 32, 48, 64, 96]
SPACING_TOL = 3  # 容差 px


def disp_w(text: str) -> float:
    """显示宽度（em 数）：中文=1，英文=0.55，数字=0.6"""
    w = 0.0
    for ch in text:
        o = ord(ch)
        if 0x4E00 < o < 0x9FFF or 0x3400 < o < 0x4DBF:
            w += 1.0
        elif ch.isdigit():
            w += 0.6
        elif ch.isascii() and ch.isalpha():
            w += 0.55
        else:
            w += 0.8
    return w


def parse_svg(svg_path: Path) -> dict:
    """解析 SVG：画布尺寸、文本元素、图形元素。"""
    src = svg_path.read_text(encoding="utf-8")

    # 画布：优先 viewBox（内容坐标系），模板把 width 改成 1920 但内容仍是 1280x720
    vb = re.search(r'viewBox="([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)"', src)
    if vb:
        W, H = int(float(vb.group(3))), int(float(vb.group(4)))
    else:
        wm = re.search(r'width="(\d+)"', src)
        hm = re.search(r'height="(\d+)"', src)
        W = int(wm.group(1)) if wm else 1920
        H = int(hm.group(1)) if hm else 1080

    texts = []
    for m in re.finditer(r'<text([^>]*)>(.*?)</text>', src, re.DOTALL):
        attrs, content = m.group(1), m.group(2)
        # 去掉内嵌标签
        content = re.sub(r'<[^>]+>', '', content).strip()
        if not content:
            continue
        xm = re.search(r'x="([\d.]+)"', attrs)
        ym = re.search(r'y="([\d.]+)"', attrs)
        fm = re.search(r'font-size="([\d.]+)"', attrs)
        texts.append({
            "x": float(xm.group(1)) if xm else 0,
            "y": float(ym.group(1)) if ym else 0,
            "fs": float(fm.group(1)) if fm else 16,
            "text": content,
        })

    # 图形：rect / image（有明确 x/y/width/height 的）
    shapes = []
    for m in re.finditer(r'<(rect|image)([^>]*)/?>', src):
        attrs = m.group(2)
        try:
            x = float(re.search(r'x="([\d.]+)"', attrs).group(1))
            y = float(re.search(r'y="([\d.]+)"', attrs).group(1))
            w = float(re.search(r'width="([\d.]+)"', attrs).group(1))
            h = float(re.search(r'height="([\d.]+)"', attrs).group(1))
            # 背景不算内容：覆盖 >70% 画布的 image/rect 是背景图/底色/scrim
            if w * h >= W * H * 0.7:
                continue
            shapes.append({"x": x, "y": y, "w": w, "h": h})
        except (AttributeError, ValueError):
            continue

    return {"W": W, "H": H, "texts": texts, "shapes": shapes}


def check_negative_space(parsed: dict) -> dict:
    """留白率：1 - 内容覆盖面积/画布面积，应在 [0.35, 0.60]。"""
    W, H = parsed["W"], parsed["H"]
    canvas = W * H
    covered = 0.0

    for t in parsed["texts"]:
        # 文本 bbox：宽 = 显示宽度 × 字号 × 0.95， 高 = 字号 × 1.2
        tw = disp_w(t["text"]) * t["fs"] * 0.95
        th = t["fs"] * 1.2
        covered += tw * th

    for s in parsed["shapes"]:
        covered += s["w"] * s["h"]

    # 去重叠：简单按 min(covered, canvas) 封顶（精确去重要栅格化，太重）
    covered = min(covered, canvas)
    neg = 1.0 - covered / canvas
    ok = NEG_SPACE_MIN <= neg <= NEG_SPACE_MAX
    return {
        "check": "negative_space",
        "pass": ok,
        "measured": round(neg, 3),
        "target": f"[{NEG_SPACE_MIN}, {NEG_SPACE_MAX}]",
        "note": "文本bbox+图形面积估算，未做像素级去重叠",
    }


def check_type_scale(parsed: dict) -> dict:
    """字阶：最大字号/最小字号，应在 [8, 16]（agnes 原意 hero:micro）。

    说明：PPT 页通常没有 micro 级文字，此项严格按 JSON 原意实现，
    多数内容页会 fail——这是规则与媒介的真实差异，如实报告。
    """
    fss = [t["fs"] for t in parsed["texts"] if t["fs"] > 0]
    if len(fss) < 2:
        return {"check": "type_scale", "pass": True, "measured": None,
                "target": f"[{TYPE_SCALE_MIN}, {TYPE_SCALE_MAX}]",
                "note": "文本不足2种字号，跳过"}
    ratio = max(fss) / min(fss)
    ok = TYPE_SCALE_MIN <= ratio <= TYPE_SCALE_MAX
    return {
        "check": "type_scale",
        "pass": ok,
        "measured": round(ratio, 2),
        "target": f"[{TYPE_SCALE_MIN}, {TYPE_SCALE_MAX}]",
        "detail": f"max_fs={max(fss)}, min_fs={min(fss)}",
        "note": "agnes 原意为海报 hero:micro；PPT 页通常无 micro 文字",
    }


def check_spacing_rhythm(parsed: dict) -> dict:
    """间距：相邻文本 y 差是否落在 rhythm [8,16,24,32,48,64,96] 容差内。

    允许 2 倍（如 128=2×64）。统计命中率。
    """
    ys = sorted(set(round(t["y"]) for t in parsed["texts"]))
    if len(ys) < 2:
        return {"check": "spacing_rhythm", "pass": True, "measured": None,
                "target": str(SPACING_RHYTHM), "note": "文本行不足2行，跳过"}

    diffs = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
    diffs = [d for d in diffs if d > 2]  # 忽略同一行

    def hits_rhythm(d: float) -> bool:
        for r in SPACING_RHYTHM:
            for mult in (1, 2):
                if abs(d - r * mult) <= SPACING_TOL:
                    return True
        return False

    hits = sum(1 for d in diffs if hits_rhythm(d))
    rate = hits / len(diffs) if diffs else 1.0
    # 门禁：命中率 ≥60% 算过（节奏是统计性指标）
    ok = rate >= 0.6
    miss = [round(d) for d in diffs if not hits_rhythm(d)][:5]
    return {
        "check": "spacing_rhythm",
        "pass": ok,
        "measured": round(rate, 2),
        "target": "hit_rate>=0.6",
        "detail": f"{hits}/{len(diffs)} 行距命中，rhythm={SPACING_RHYTHM}±{SPACING_TOL}",
        "miss_samples": miss,
    }


def qa_one(svg_path: Path) -> dict:
    parsed = parse_svg(svg_path)
    checks = [
        check_negative_space(parsed),
        check_type_scale(parsed),
        check_spacing_rhythm(parsed),
    ]
    return {
        "file": svg_path.name,
        "pass": all(c["pass"] for c in checks),
        "checks": checks,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description="agnes 版式硬指标 QA")
    ap.add_argument("svg_dir", help="SVG 目录")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    a = ap.parse_args()

    d = Path(a.svg_dir)
    svgs = sorted(d.glob("*.svg"))
    if not svgs:
        # 可能是 svg_output 子目录
        sub = d / "svg_output"
        if sub.is_dir():
            svgs = sorted(sub.glob("*.svg"))

    results = [qa_one(f) for f in svgs]
    n_pass = sum(1 for r in results if r["pass"])
    report = {
        "total": len(results),
        "passed": n_pass,
        "failed": len(results) - n_pass,
        "rules_source": "agnes poster_grand_rules.json hard_targets",
        "files": results,
    }

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"agnes QA: {n_pass}/{len(results)} 通过")
        for r in results:
            mark = "✓" if r["pass"] else "✗"
            details = " ".join(
                f"{c['check']}={'PASS' if c['pass'] else 'FAIL'}({c['measured']})"
                for c in r["checks"]
            )
            print(f"  {mark} {r['file']}: {details}")


if __name__ == "__main__":
    main()
