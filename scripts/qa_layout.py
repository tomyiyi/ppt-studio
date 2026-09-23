#!/usr/bin/env python3
"""
qa_layout.py — PPT Master SVG 版面客观复核（不看图也能判断）

三项检查：
  1. overflow  : 文本是否超出画布安全区（正确处理 text-anchor=start/middle/end）
  2. panel     : 图片面板区域是否真的有内容（不为纯色/不为空白）
  3. contrast  : 渲染后文字区域是否满足 WCAG 4.5:1（背景=区域20分位，笔画=99.5分位）

用法：
  python3 qa_layout.py <svg_dir> <rendered_dir>
例：
  python3 qa_layout.py tools/ppt-master/projects/agentflow-os-launch/svg_output qa_render
"""
import os
import re
import sys
import glob
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

NS = "{http://www.w3.org/2000/svg}"
CANVAS_W, CANVAS_H = 1280, 720
MARGIN = 60
WCAG_MIN = 4.5

# ---------------------------------------------------------------- 文本测宽
def char_w(ch, mono=False):
    o = ord(ch)
    if o > 0x2E80:          # CJK / 全角
        return 1.0
    if mono:
        return 0.60
    return 0.52             # 拉丁字母比例字体近似

def text_width(s, size, mono=False, ls=0.0):
    w = sum(char_w(c, mono) for c in s) * size
    return w + ls * max(0, len(s) - 1)

def mono_family(style):
    return bool(re.search(r"Consolas|monospace|Mono", style or "", re.I))

# ---------------------------------------------------------------- 溢出
def check_overflow(root):
    issues = []
    for t, anc in _iter_with_parents(root):
        if t.tag != NS + "text":
            continue
        txt = "".join(t.itertext())
        if not txt.strip():
            continue
        x = float(t.get("x", 0) or 0)
        size = inherited_font_size(t, anc)
        ls = float(t.get("letter-spacing", 0) or 0)
        anchor = t.get("text-anchor", "start")
        mono = mono_family(t.get("font-family", "") or t.get("style", ""))
        w = text_width(txt, size, mono, ls)
        if anchor == "middle":
            left, right = x - w / 2, x + w / 2
        elif anchor == "end":
            left, right = x - w, x          # 向左延伸，右边界就是 x
        else:
            left, right = x, x + w
        if right > CANVAS_W - MARGIN + 1:
            issues.append(f"右溢出 {right - (CANVAS_W - MARGIN):.0f}px  «{txt[:24]}»")
        if left < MARGIN - 1:
            issues.append(f"左溢出 {(MARGIN - left):.0f}px  «{txt[:24]}»")
    return issues

# ---------------------------------------------------------------- 面板
DEFAULT_RAMP = {11, 13, 16, 20, 24, 32, 44, 96}


def load_ramp(spec_lock_path):
    """从 spec_lock.md 的 ## typography 段读字号阶梯（单一事实源）。
    解析 `- role: 数字` 这行，跳过 # 开头的注释。"""
    try:
        txt = open(spec_lock_path, encoding="utf-8").read()
    except OSError:
        return DEFAULT_RAMP
    m = re.search(r"^##\s+typography\s*$(.*?)(?=^##\s|\Z)", txt, re.S | re.M)
    if not m:
        return DEFAULT_RAMP
    out = set()
    for line in m.group(1).splitlines():
        line = line.strip()
        if line.startswith("#"):
            continue
        mm = re.match(r"^-\s*\w+\s*:\s*(\d+)\s*$", line)
        if mm:
            out.add(int(mm.group(1)))
    return out or DEFAULT_RAMP


def _iter_with_parents(root):
    """(elem, [ancestors...]) —— 用来解析继承属性。
    ⚠️ 踩过的坑：font-size 经常写在父 <g> 上（如 <g font-size="56">）由子 <text> 继承。
    只读 elem.get('font-size') 会把 56px 的大标题误报成默认的 16px。"""
    stack = [(root, [])]
    while stack:
        e, anc = stack.pop()
        yield e, anc
        kids = list(e)
        for k in reversed(kids):
            stack.append((k, anc + [e]))


def inherited_font_size(t, anc, default=16.0):
    for a in reversed(anc):
        v = a.get("font-size")
        if v:
            try:
                return float(v)
            except ValueError:
                pass
    v = t.get("font-size")
    if v:
        try:
            return float(v)
        except ValueError:
            pass
    return float(default)


def check_typescale(root, ramp):
    """字号一致性：所有字号必须落在阶梯上。
    典型事故：改版式时为了让内容塞进变小的地方，随手把正文 16 降到 14、
    把微标签 13 降到 12 —— 单页看着没事，全篇翻起来就"一时大一时小"。"""
    used = {}
    for t, anc in _iter_with_parents(root):
        if t.tag != NS + "text":
            continue
        if not "".join(t.itertext()).strip():
            continue
        s = int(round(inherited_font_size(t, anc)))
        used[s] = used.get(s, 0) + 1
    off = sorted(s for s in used if s not in ramp)
    return used, off


def check_backdrop(root):
    """底图效果：图必须铺满画布，不能只是角落里一块面板。
    判据：最大的 <image> 面积 / 画布面积 ≥ 90%"""
    areas = []
    for im in root.iter(NS + "image"):
        try:
            areas.append(float(im.get("width", 0)) * float(im.get("height", 0)))
        except ValueError:
            pass
    if not areas:
        return None
    return 100.0 * max(areas) / (CANVAS_W * CANVAS_H)


def check_dup_images(root):
    """同一张源图在一页里出现两次 = 同一个图形被画了两遍，视觉上是"重影"。
    典型事故：全幅铺底用 xxx_bg.png，右半面板又用 xxx_bg_panel.png。"""
    srcs = []
    for im in root.iter(NS + "image"):
        h = os.path.basename(im.get("href", ""))
        srcs.append(re.sub(r"_panel(\.\w+)?$", "", h))
    seen, dup = set(), set()
    for s in srcs:
        (dup if s in seen else seen).add(s)
    return sorted(dup)


def panels_of(root):
    """返回 (id, x, y, w, h) —— 带 clip-path 的 <image>，即独立图片面板"""
    out = []
    clips = {}
    for cp in root.iter(NS + "clipPath"):
        cid = cp.get("id")
        r = cp.find(NS + "rect")
        if cid and r is not None:
            clips[cid] = tuple(float(r.get(k, 0)) for k in ("x", "y", "width", "height"))
    for im in root.iter(NS + "image"):
        ref = im.get("clip-path", "")
        m = re.search(r"url\(#([^)]+)\)", ref)
        if not m:
            continue
        geo = clips.get(m.group(1))
        if not geo:
            continue
        out.append(("panel:" + m.group(1),) + geo)
    return out

def check_panel(img, box, name):
    """必须用 max 通道衡量，不能只用亮度：
    #6E7BFF 靛蓝的蓝通道是 255，但相对亮度权重只有 0.0722，
    折算成灰度只有 ~136。用亮度会把满饱和靛蓝误判成"太暗"。"""
    x, y, w, h = [int(v) for v in box]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(img.width, x + w), min(img.height, y + h)
    if x1 <= x0 or y1 <= y0:
        return f"{name} 区域无效"
    c = np.asarray(img.crop((x0, y0, x1, y1)).convert("RGB"), dtype=np.float64)
    mx = c.max(axis=2)
    ink = 100 * float(np.mean(mx > 80))
    bg = np.percentile(c.reshape(-1, 3), 10, axis=0)
    st = c.reshape(-1, 3)[mx.reshape(-1) > np.percentile(mx, 99)].mean(axis=0)
    cr = (lambda a, b: (max(lum(a), lum(b)) + 0.05) / (min(lum(a), lum(b)) + 0.05))(st, bg)
    warn = []
    if ink < 3.0:
        warn.append(f"⚠️主体太小(墨量{ink:.1f}%)")
    if cr < 3.0:
        warn.append(f"⚠️笔画对比不足({cr:.1f}:1)")
    tag = "  ".join(warn) if warn else "OK"
    return f"{name} {w}x{h} 墨量={ink:.2f}% 笔画RGB={st.round(0)} 对比={cr:.1f}:1  {tag}"

# ---------------------------------------------------------------- 对比度
def lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def lum(v):
    return 0.2126 * lin(v[0]) + 0.7152 * lin(v[1]) + 0.0722 * lin(v[2])

def check_line_collisions(root):
    """改版式挪动文字后，同一列里相邻两行可能压到一起。
    按 x 相近（±24px）归为同一列，按 y 排序，检查行框是否重叠。
    行框 = [baseline - 0.80*size, baseline + 0.25*size]。"""
    rows = []
    for t, anc in _iter_with_parents(root):
        if t.tag != NS + "text":
            continue
        txt = "".join(t.itertext()).strip()
        if not txt:
            continue
        x = float(t.get("x", 0) or 0); y = float(t.get("y", 0) or 0)
        rows.append((x, y, inherited_font_size(t, anc), txt))
    rows.sort(key=lambda r: (r[0], r[1]))
    out = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            x1, y1, s1, t1 = rows[i]
            x2, y2, s2, t2 = rows[j]
            if abs(x1 - x2) > 24:
                continue
            a0, a1 = y1 - 0.80 * s1, y1 + 0.25 * s1
            b0, b1 = y2 - 0.80 * s2, y2 + 0.25 * s2
            ov = min(a1, b1) - max(a0, b0)
            if ov > 2:
                out.append(f"压行 {ov:.0f}px «{t1[:14]}» × «{t2[:14]}»")
    return out


def check_contrast(img, root):
    """对每段文本，取渲染图中文字包围盒：背景=20分位亮度，笔画=99.5分位亮度"""
    rgb = np.asarray(img.convert("RGB"), dtype=np.float64)
    g = rgb.mean(axis=2)
    rows = []
    for t, anc in _iter_with_parents(root):
        if t.tag != NS + "text":
            continue
        txt = "".join(t.itertext()).strip()
        if not txt:
            continue
        x = float(t.get("x", 0) or 0)
        y = float(t.get("y", 0) or 0)
        size = inherited_font_size(t, anc)
        anchor = t.get("text-anchor", "start")
        mono = mono_family(t.get("font-family", "") or t.get("style", ""))
        ls = float(t.get("letter-spacing", 0) or 0)
        w = text_width(txt, size, mono, ls)
        if anchor == "middle":
            left = x - w / 2
        elif anchor == "end":
            left = x - w
        else:
            left = x
        x0 = int(max(0, left)); x1 = int(min(img.width, left + w))
        y0 = int(max(0, y - size * 0.85)); y1 = int(min(img.height, y + size * 0.25))
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        reg = g[y0:y1, x0:x1]
        if reg.size < 30:
            continue
        bg_t = np.percentile(reg, 20)
        gl_t = np.percentile(reg, 99.5)
        bgm = reg <= bg_t
        glm = reg >= gl_t
        if not bgm.any() or not glm.any():
            continue
        bg = rgb[y0:y1, x0:x1][bgm].mean(axis=0)
        gl = rgb[y0:y1, x0:x1][glm].mean(axis=0)
        L1, L2 = lum(gl), lum(bg)
        if L1 < L2:
            L1, L2 = L2, L1
        ratio = (L1 + 0.05) / (L2 + 0.05)
        rows.append((ratio, txt, size))
    return rows

# ---------------------------------------------------------------- main
def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    svg_dir, render_dir = sys.argv[1], sys.argv[2]
    # spec_lock 在 <project>/spec_lock.md，svg_dir 是 <project>/svg_output
    spec = os.path.join(os.path.dirname(os.path.abspath(svg_dir)), "spec_lock.md")
    ramp = load_ramp(spec)
    print(f"字号阶梯（来自 {os.path.basename(spec)}）: {sorted(ramp)}")

    # 渲染目录可能是 <name>.png/<name>.png 的嵌套结构
    def find_png(stem):
        for pat in (f"{stem}.png", f"{stem}/*.png", f"**/{stem}.png"):
            hit = [p for p in glob.glob(os.path.join(render_dir, pat), recursive=True)
                   if os.path.isfile(p)]
            if hit:
                return hit[0]
        return None

    bad = 0
    for svg in sorted(glob.glob(os.path.join(svg_dir, "*.svg"))):
        stem = os.path.splitext(os.path.basename(svg))[0]
        print(f"\n=== {stem} ===")
        root = ET.parse(svg).getroot()

        used, off = check_typescale(root, ramp)
        line = "  ".join(f"{k}×{v}" for k, v in sorted(used.items()))
        if off:
            bad += len(off)
            print(f"  [字号] {line}   ⚠️ 越出阶梯: {off}")
        else:
            print(f"  [字号] {line}   OK（{len(used)} 档）")

        cov = check_backdrop(root)
        if cov is None:
            print("  [底图] 无图片")
        else:
            ok = cov >= 90.0
            if not ok:
                bad += 1
            print(f"  [底图] 覆盖画布 {cov:.1f}%  {'OK' if ok else '⚠️ 未铺满，不是底图'}")

        dups = check_dup_images(root)
        if dups:
            bad += len(dups)
            for d in dups:
                print(f"  [重影] 同一张源图用了两次：{d}  →  一页只保留一个图位")
        else:
            print("  [重影] OK（每张源图仅一次）")

        ov = check_overflow(root)
        if ov:
            bad += len(ov)
            for i in ov:
                print(f"  [溢出] {i}")
        else:
            print("  [溢出] OK")

        col = check_line_collisions(root)
        if col:
            bad += len(col)
            for c in col[:8]:
                print(f"  [压行] {c}")
        else:
            print("  [压行] OK")

        png = find_png(stem)
        if not png:
            print("  [渲染] 未找到对应 PNG，跳过面板/对比度检查")
            continue
        img = Image.open(png)

        ps = panels_of(root)
        if not ps:
            print("  [面板] 无独立图片面板")
        for name, x, y, w, h in ps:
            line = check_panel(img, (x, y, w, h), name)
            print(f"  [面板] {line}")
            if "⚠️" in line:
                bad += 1

        rows = check_contrast(img, root)
        if not rows:
            print("  [对比] 无可测文本")
        else:
            rows.sort()
            worst = rows[0]
            fails = [r for r in rows if r[0] < WCAG_MIN]
            print(f"  [对比] 最低 {worst[0]:.1f}:1  «{worst[1][:20]}»  "
                  f"| 不达标 {len(fails)}/{len(rows)}")
            for r, t, s in fails[:6]:
                print(f"          {r:.1f}:1  «{t[:26]}» ({s:.0f}px)")
                bad += 1

    print("\n" + "=" * 60)
    print("ALL CLEAR ✅" if bad == 0 else f"待修 {bad} 项 ⚠️")
    return 0 if bad == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
