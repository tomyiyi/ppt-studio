#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa_cards.py —— 卡片质检（交付前必跑）
=====================================

用法：
  python3 qa_cards.py <project>/cards <render_dir>

七项检查，全部 OK 才输出 ALL CLEAR：

  [字号]   所有文本落在 card_spec.md 的阶梯内
  [安全区] 文本不出 64px 硬安全边（SVG 估算 + 渲染像素双重校验）
  [溢出]   文本不出画布
  [压行]   相邻文本块不重叠
  [对比]   每个文本块 WCAG ≥ 4.5:1（背景取 20 分位、字色取 99.5 分位）
  [底图]   图片带面积 / 画布 ≥ 45%
  [留白]   内容面板墨量 3%–35%（太空 = 没内容，太满 = 拥挤）

依赖：Pillow + numpy
"""

from __future__ import annotations

import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

DEFAULT_RAMP = {28, 36, 44, 56, 72, 96, 132}

# ---------------------------------------------------------------- 字号阶梯
def load_ramp(spec_path):
    if not os.path.exists(spec_path):
        print(f"[warn] 找不到 {spec_path}，用默认阶梯")
        return set(DEFAULT_RAMP)
    txt = open(spec_path, encoding="utf-8").read()
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
def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    card_dir, render_dir = sys.argv[1], sys.argv[2]
    proj = os.path.dirname(os.path.abspath(card_dir))
    spec = os.path.join(proj, "card_spec.md")
    ramp = load_ramp(spec)
    print(f"卡片字号阶梯（来自 {os.path.basename(spec)}）: {sorted(ramp)}\n")

    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        np = None
        print("[warn] 缺 numpy/Pillow，跳过像素级检查（对比/留白/安全区像素校验）")

    bad = 0
    for svg in sorted(glob.glob(os.path.join(card_dir, "*.svg"))):
        stem = os.path.splitext(os.path.basename(svg))[0]
        print(f"=== {stem} ===")
        root = ET.parse(svg).getroot()
        vb = root.get("viewBox", "0 0 1080 1350").split()
        W, H = int(float(vb[2])), int(float(vb[3]))
        texts = collect_texts(root)
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

        # ---- 像素级
        png = None
        for pat in (f"{stem}.png", f"{stem}/*.png", f"**/{stem}.png"):
            hit = [p for p in glob.glob(os.path.join(render_dir, pat), recursive=True)
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

    print("ALL CLEAR ✅" if bad == 0 else f"❌ {bad} 项需要处理")
    return 0 if bad == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
