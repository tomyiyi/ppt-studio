#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa_cards.py —— 卡片客观质量门禁（交付前必跑）
=============================================

用法：
  python3 qa_cards.py [target] [render_dir] [--spec card_spec.md]

例：
  python3 scripts/qa_cards.py .                          # 自动探测项目及卡片目录
  python3 scripts/qa_cards.py projects/agentflow-os-launch
  python3 scripts/qa_cards.py cards/ render_cards/

九项客观检查，全部 OK 才输出 ALL CLEAR：

  [字号]     所有文本落在 card_spec.md 的阶梯内
  [安全区]   文本不出 64px 硬安全边（SVG 估算 + 渲染像素双重校验）
  [溢出]     文本不出画布
  [压行]     相邻文本块不重叠
  [签名竖线] 包含 6px 品牌强调竖线签名元素且规格与规范色 (#6E7BFF) 一致
  [对比]     每个文本块 WCAG ≥ 4.5:1（背景取 20 分位、字色取 99.5 分位）
  [底图]     图片带面积 / 画布 ≥ 40% 且墨量 ≥ 2%（防漏图）
  [留白]     内容面板墨量 3%–35%（太空 = 没内容，太满 = 拥挤）
  [主句]     跨正文卡片主句 (statement) 字号严格对齐 (72px)，防范"一时大一时小"

依赖：Pillow + numpy
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from collections import Counter
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_RAMP = {28, 36, 44, 56, 72, 96, 132}

# ---------------------------------------------------------------- 字号阶梯与角色
def load_ramp(spec_path):
    if not spec_path or not os.path.exists(str(spec_path)):
        print(f"[warn] 找不到 {spec_path}，用默认阶梯")
        return set(DEFAULT_RAMP)
    txt = open(str(spec_path), encoding="utf-8").read()
    m = re.search(r"^##\s+typography\s*$(.*?)(?=^##\s|\Z)", txt, re.S | re.M)
    if not m:
        return set(DEFAULT_RAMP)
    out = set()
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        mm = re.match(r"^(\d+)\s+(\w+)", line)
        if mm:
            out.add(int(mm.group(1)))
    return out or set(DEFAULT_RAMP)


def load_spec_roles(spec_path):
    """从 card_spec.md 的 ## typography 段读取 (role -> font_size) 映射。"""
    if not spec_path or not os.path.exists(str(spec_path)):
        return {}
    txt = open(str(spec_path), encoding="utf-8").read()
    m = re.search(r"^##\s+typography\s*$(.*?)(?=^##\s|\Z)", txt, re.S | re.M)
    if not m:
        return {}
    roles = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        mm = re.match(r"^(\d+)\s+(\w+)", line)
        if mm:
            roles[mm.group(2)] = int(mm.group(1))
    return roles


def load_spec_colors(spec_path):
    """从 card_spec.md 的 ## colors 段读取色彩配置。"""
    if not spec_path or not os.path.exists(str(spec_path)):
        return {}
    txt = open(str(spec_path), encoding="utf-8").read()
    m = re.search(r"^##\s+colors\s*$(.*?)(?=^##\s|\Z)", txt, re.S | re.M)
    if not m:
        return {}
    colors = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        mm = re.match(r"^(\w+)\s+(#[0-9a-fA-F]{6})", line)
        if mm:
            colors[mm.group(1)] = mm.group(2).upper()
    return colors


def check_card_statement_consistency(
    card_slides: list[tuple[str, list[dict]]],
    expected_sz: int = 72,
) -> tuple[bool, str]:
    """验证正文卡片主句 (statement) 字号在各卡之间是否严格一致。
    防范事故：主句在不同卡片被随手设成 44/56/96，导致跨卡浏览时字号'一时大一时小'。"""
    content_cards = [
        (stem, texts) for stem, texts in card_slides
        if not (stem.startswith("01") or "cover" in stem.lower())
    ]
    if len(content_cards) < 2:
        return True, "卡片数量较少，跳过跨卡主句一致性比对"

    statement_cards = {}
    for stem, texts in content_cards:
        candidate_stmts = []
        for t in texts:
            fs = int(round(t["fs"]))
            txt = t["txt"]
            # 排除纯数字/百分比/短指标 (如 3%, 24h, 100%, 02 / 07)
            clean_txt = re.sub(r"[\s\d\.\%\+\-xXhH/·:：→]+", "", txt)
            if not clean_txt:
                continue
            # 主句通常在 44~96 档位之间
            if fs in (44, 56, 72, 96):
                candidate_stmts.append((fs, txt))
        if not candidate_stmts:
            continue
        # 取最大的非数字字号作为该卡 statement
        top_fs, top_txt = max(candidate_stmts, key=lambda x: x[0])
        statement_cards[stem] = (top_fs, top_txt)

    if not statement_cards:
        return True, "未检测到正文卡片主句"

    counts = Counter(sz for sz, _ in statement_cards.values())
    target_sz = expected_sz if expected_sz in counts else counts.most_common(1)[0][0]

    drifts = []
    aligned = []
    for stem, (sz, txt) in sorted(statement_cards.items()):
        if sz != target_sz:
            drifts.append(f"{stem} ({sz}px: «{txt[:16]}»)")
        else:
            aligned.append(stem)

    if drifts:
        return False, f"发现主句字号漂移 (预期 {target_sz}px，漂移卡: {', '.join(drifts)})"

    aligned_labels = ", ".join(s.split("_")[0] for s in aligned)
    return True, f"各正文卡片主句字号严格对齐 ({target_sz}px) · 卡片 [{aligned_labels}] 无漂移"

# ---------------------------------------------------------------- 文本宽度
def char_w(ch, fs):
    o = ord(ch)
    if o > 0x2E80:
        return fs * 1.0
    if ch in "iljItf.,;:'|!()[]":
        return fs * 0.30
    if ch in "MW@%":
        return fs * 0.92
    if ch.isupper():
        return fs * 0.68
    if ch.isdigit():
        return fs * 0.56
    return fs * 0.55

def text_w(s, fs, ls=0.0):
    return sum(char_w(c, fs) + ls for c in s)

def iter_with_parents(root):
    stack = [(root, [])]
    while stack:
        e, anc = stack.pop()
        yield e, anc
        for k in reversed(list(e)):
            stack.append((k, anc + [e]))

def inherit(e, anc, key, default=None):
    for a in reversed(anc):
        v = a.get(key)
        if v:
            return v
    return e.get(key, default)

def flat_text(t):
    return "".join(t.itertext()).strip()

def collect_texts(root):
    """返回 [(txt, fs, x, y, anchor, ls, fill)]，y 是基线。"""
    out = []
    for e, anc in iter_with_parents(root):
        if e.tag.split("}")[-1] != "text":
            continue
        txt = flat_text(e)
        if not txt:
            continue
        fs = float(inherit(e, anc, "font-size", "16") or 16)
        ls = float(e.get("letter-spacing", 0) or 0)
        out.append(dict(
            txt=txt, fs=fs,
            x=float(e.get("x", 0)), y=float(e.get("y", 0)),
            anchor=e.get("text-anchor", "start"),
            ls=ls,
            fill=inherit(e, anc, "fill", "#FFFFFF") or "#FFFFFF",
            weight=inherit(e, anc, "font-weight", "") == "bold",
        ))
    return out

def bbox(t):
    """按 text-anchor 算边界框。end 向左延伸 —— 最容易算错的一种。"""
    w = text_w(t["txt"], t["fs"], t["ls"])
    x = t["x"]
    if t["anchor"] == "middle":
        x0 = x - w / 2
    elif t["anchor"] == "end":
        x0 = x - w
    else:
        x0 = x
    top = t["y"] - t["fs"] * 0.80
    bot = t["y"] + t["fs"] * 0.25
    return x0, top, x0 + w, bot

# ---------------------------------------------------------------- WCAG
def lum(c):
    def f(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])

def contrast(a, b):
    l1, l2 = lum(a), lum(b)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)

def hex2rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

# ---------------------------------------------------------------- 主流程
def run_qa_cards(
    card_dir: str | Path,
    render_dir: str | Path | None = None,
    spec_path: str | Path | None = None,
) -> bool:
    card_path = Path(card_dir).resolve()
    render_path = Path(render_dir).resolve() if render_dir else None
    spec_file = Path(spec_path).resolve() if spec_path else None

    # 如果 card_path 包含 cards/ 子目录，优先使用 cards/
    if not list(card_path.glob("*.svg")) and (card_path / "cards").is_dir():
        card_path = (card_path / "cards").resolve()

    # 自动探测 card_spec.md
    if not spec_file:
        for candidate in [
            card_path / "card_spec.md",
            card_path.parent / "card_spec.md",
            card_path.parent.parent / "card_spec.md",
            Path.cwd() / "card_spec.md",
            Path.cwd() / "projects/agentflow-os-launch/card_spec.md",
            Path(__file__).resolve().parent.parent / "projects/agentflow-os-launch/card_spec.md",
        ]:
            if candidate and candidate.exists():
                spec_file = candidate.resolve()
                break

    # 自动探测 render_cards 目录
    if not render_path:
        for candidate in [
            card_path.parent / "render_cards",
            card_path / "render_cards",
            card_path.parent / "render",
            card_path / "render",
            card_path,
        ]:
            if candidate and candidate.is_dir() and list(candidate.glob("*.png")):
                render_path = candidate.resolve()
                break

    print("=" * 60)
    print("🔍 运行 PPT-Studio 卡片客观质量门禁")
    print(f"   卡片目录: {card_path}")
    if render_path:
        print(f"   渲染目录: {render_path}")
    print("=" * 60)

    ramp = load_ramp(spec_file)
    roles = load_spec_roles(spec_file)
    colors = load_spec_colors(spec_file)
    expected_stmt_sz = roles.get("statement", 72)
    expected_accent = colors.get("accent", "#6E7BFF")
    spec_label = spec_file.name if spec_file else "默认阶梯"
    print(f"卡片字号阶梯（来自 {spec_label}）: {sorted(ramp)}")
    if "statement" in roles:
        print(f"跨卡主句预期字号: {expected_stmt_sz}px (来自 {spec_label})")
    if "accent" in colors:
        print(f"品牌强调色规范: {expected_accent}")
    print()

    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        np = None
        print("[warn] 缺 numpy/Pillow，跳过像素级检查（对比/留白/安全区像素校验）")

    svg_files = sorted(card_path.glob("*.svg"))
    if not svg_files:
        print(f"[!] 目录 {card_path} 下未找到 SVG 卡片文件")
        print("=" * 60)
        return False

    bad = 0
    card_slides = []
    for svg in svg_files:
        stem = svg.stem
        print(f"=== {stem} ===")
        root = ET.parse(svg).getroot()
        vb = root.get("viewBox", "0 0 1080 1350").split()
        W, H = int(float(vb[2])), int(float(vb[3]))
        texts = collect_texts(root)
        card_slides.append((stem, texts))
        SAFE = 64

        # 图片带高度从 SVG 里读，不能硬编码 —— 改了 make_cards 的常量后
        # 质检会拿着旧数字骗人（踩过）。
        band = int(H * 0.52)
        for e, _ in iter_with_parents(root):
            if e.tag.split("}")[-1] == "image":
                band = int(float(e.get("y", 0))) + int(float(e.get("height", 0)))
                break

        # ---- [字号]
        off = [t for t in texts if round(t["fs"]) not in ramp]
        print(f"  [字号]  {'OK' if not off else 'WARN'}  {len(texts)} 段文本"
              + ("" if not off else "  越档: " + ", ".join(f'{t["fs"]:.0f}({t["txt"][:8]})' for t in off)))
        if off:
            bad += 1

        # ---- [安全区] [溢出]
        oob, of = [], []
        for t in texts:
            x0, y0, x1, y1 = bbox(t)
            if x0 < SAFE - 1 or x1 > W - SAFE + 1 or y0 < SAFE - 1 or y1 > H - SAFE + 1:
                oob.append(t)
            if x0 < -1 or x1 > W + 1 or y0 < -1 or y1 > H + 1:
                of.append(t)
        print(f"  [安全区] {'OK' if not oob else 'WARN'}  安全边 {SAFE}px"
              + ("" if not oob else "  越界: " + ", ".join(t["txt"][:10] for t in oob)))
        print(f"  [溢出]   {'OK' if not of else 'WARN'}"
              + ("" if not of else "  " + ", ".join(t["txt"][:10] for t in of)))
        if oob or of:
            bad += 1

        # ---- [压行]
        boxes = []
        for t in texts:
            x0, y0, x1, y1 = bbox(t)
            boxes.append((x0, y0, x1, y1, t["txt"]))
        coll = []
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                ox = min(a[2], b[2]) - max(a[0], b[0])
                oy = min(a[3], b[3]) - max(a[1], b[1])
                if ox > 8 and oy > 6:
                    coll.append((a[4][:8], b[4][:8], round(oy)))
        print(f"  [压行]   {'OK' if not coll else 'WARN'}"
              + ("" if not coll else "  " + ", ".join(f"{a}×{b}({o}px)" for a, b, o in coll)))
        if coll:
            bad += 1

        # ---- [签名竖线]
        bars = []
        for e, _ in iter_with_parents(root):
            if e.tag.split("}")[-1] == "rect":
                try:
                    w_val = float(e.get("width", 0) or 0)
                    if abs(w_val - 6.0) < 0.1:
                        bars.append((
                            float(e.get("x", 0) or 0),
                            float(e.get("y", 0) or 0),
                            float(e.get("height", 0) or 0),
                            e.get("fill", "")
                        ))
                except (ValueError, TypeError):
                    pass
        ok_bar = len(bars) >= 1
        bar_fill = bars[0][3] if ok_bar else ""
        color_ok = True
        if ok_bar and expected_accent and bar_fill:
            color_ok = (bar_fill.strip().upper() == expected_accent.strip().upper())

        if not ok_bar:
            print("  [签名竖线] WARN  缺少 6px 主句签名强调竖线")
            bad += 1
        elif not color_ok:
            print(f"  [签名竖线] WARN  6px 强调竖线颜色 ({bar_fill}) 与品牌规范色 ({expected_accent}) 不符")
            bad += 1
        else:
            print(f"  [签名竖线] OK  6px 强调竖线 (h={bars[0][2]:.0f}, fill={bar_fill})")

        # ---- 像素级
        png = None
        if render_path and render_path.is_dir():
            for pat in (f"{stem}.png", f"{stem}/*.png", f"**/{stem}.png"):
                hit = [p for p in glob.glob(os.path.join(str(render_path), pat), recursive=True)
                       if os.path.isfile(p)]
                if hit:
                    png = hit[0]
                    break

        if png and np is not None:
            im = np.asarray(Image.open(png).convert("RGB")).astype(float)
            h, w = im.shape[:2]

            # [对比] 每块文本：背景 20 分位 vs 字色 99.5 分位
            low = []
            for t in texts:
                if t["fs"] < 24:
                    continue
                x0, y0, x1, y1 = bbox(t)
                x0 = max(0, int(x0)); x1 = min(w, int(x1))
                y0 = max(0, int(y0)); y1 = min(h, int(y1))
                if x1 <= x0 or y1 <= y0:
                    continue
                reg = im[y0:y1, x0:x1]
                mx = reg.max(axis=2)
                bg_v = np.percentile(mx, 20)
                fg_v = np.percentile(mx, 99.5)
                bg = np.array([bg_v] * 3)
                fg = np.array([fg_v] * 3)
                r = contrast(fg, bg)
                if r < 4.5:
                    low.append((t["txt"][:12], round(r, 2)))
            print(f"  [对比]   {'OK' if not low else 'WARN'}  "
                  f"{len([t for t in texts if t['fs'] >= 24])} 块"
                  + ("" if not low else "  不足: " + ", ".join(f"{a}={b}" for a, b in low)))
            if low:
                bad += 1

            # [底图] 面积 + 是否真的画出来（全黑 = 图没加载上）
            cov = band * W / (W * H)
            bmx = im[:band, :, :].max(axis=2)
            bink = float((bmx > 80).mean())
            # ⚠️ 阈值对齐生成器下限（40%）：内容多的卡片图片带会缩到 40%，
            #    这里写 45% 会永远报警。
            # 2% 而非 3%：稀疏点阵类底图（如封面晶格）本身只有 ~2.9% 像素 >80，
            #    这条检查的用途是抓「图没加载上」（此时墨量 ≈0），不是审美标准。
            ok_img = cov >= 0.40 and bink >= 0.02
            print(f"  [底图]   {'OK' if ok_img else 'WARN'}  "
                  f"图片带 {band}/{H} = {cov*100:.1f}%（≥40%）· 墨量 {bink*100:.1f}%（≥2%，防漏图）")
            if not ok_img:
                bad += 1

            # [留白] 面板墨量（文字占比）
            panel = im[band:h, :, :]
            mx = panel.max(axis=2)
            ink = float((mx > 150).mean())
            ok = 0.03 <= ink <= 0.35
            print(f"  [留白]   {'OK' if ok else 'WARN'}  面板墨量 {ink*100:.2f}%"
                  f"（3%–35%）")
            if not ok:
                bad += 1

            # [安全区] 像素校验：面板区亮像素是否越过硬安全边
            pm = mx > 200
            ys, xs = np.where(pm)
            if len(xs):
                px0, px1 = xs.min(), xs.max()
                py1 = ys.max() + band
                voob = px0 < SAFE - 12 or px1 > W - SAFE + 12 or py1 > H - SAFE + 12
                print(f"  [安全区·像素] {'OK' if not voob else 'WARN'}  "
                      f"文字实际范围 x[{px0},{px1}] y底 {py1}")
                if voob:
                    bad += 1
        else:
            print("  [对比]/[底图]/[留白]  跳过（无渲染图）")
        print()

    # 跨卡主句一致性检查（多卡时执行）
    if len(card_slides) > 1:
        print("=== 跨卡一致性 ===")
        ok_stmt, msg_stmt = check_card_statement_consistency(card_slides, expected_stmt_sz)
        if ok_stmt:
            print(f"  [主句] OK  {msg_stmt}")
        else:
            bad += 1
            print(f"  [主句] ⚠️  {msg_stmt}")
        print()

    print("=" * 60)
    print("ALL CLEAR ✅" if bad == 0 else f"❌ {bad} 项需要处理")
    return bad == 0


def main():
    parser = argparse.ArgumentParser(description="PPT-Studio 卡片客观质量门禁（交付前必跑）")
    parser.add_argument("target", nargs="?", default=".", help="卡片目录、项目目录或目标路径（默认当前目录）")
    parser.add_argument("render_dir", nargs="?", default=None, help="可选渲染图 PNG 目录（缺省时自动查找 render_cards/ 或 render/）")
    parser.add_argument("--spec", help="可选指定 card_spec.md 路径")
    args = parser.parse_args()

    target_path = Path(args.target).resolve()
    spec_path = Path(args.spec).resolve() if args.spec else None
    render_dir = Path(args.render_dir).resolve() if args.render_dir else None

    # 如果显式传入两个目录 (card_dir, render_dir)
    if args.render_dir:
        success = run_qa_cards(target_path, render_dir, spec_path)
        sys.exit(0 if success else 1)

    # 如果 target_path 包含 cards/ 子目录
    if (target_path / "cards").is_dir():
        card_dir = target_path / "cards"
        success = run_qa_cards(card_dir, render_dir, spec_path)
        sys.exit(0 if success else 1)

    # 如果 target_path 本身就是包含 .svg 的目录
    if target_path.is_dir() and list(target_path.glob("*.svg")):
        success = run_qa_cards(target_path, render_dir, spec_path)
        sys.exit(0 if success else 1)

    # 如果 target_path 是项目根目录且 projects/ 下有项目，或向上级查找 projects/
    projects_with_cards = []
    search_dirs = [target_path]
    if not (target_path / "projects").is_dir():
        for cand in [target_path.parent, target_path.parent.parent, Path.cwd()]:
            if cand and (cand / "projects").is_dir():
                search_dirs.append(cand)
                break
    for base_dir in search_dirs:
        if (base_dir / "projects").is_dir():
            for p in sorted((base_dir / "projects").iterdir()):
                if p.is_dir() and (p / "cards").is_dir() and list((p / "cards").glob("*.svg")):
                    projects_with_cards.append(p / "cards")
            if projects_with_cards:
                break
    if projects_with_cards:
        all_ok = True
        for cdir in projects_with_cards:
            ok = run_qa_cards(cdir, render_dir, spec_path)
            if not ok:
                all_ok = False
        sys.exit(0 if all_ok else 1)

    print(f"[!] 在 {target_path} 未找到有效卡片 SVG 文件或 cards/ 子目录")
    sys.exit(1)

if __name__ == "__main__":
    sys.exit(main())
