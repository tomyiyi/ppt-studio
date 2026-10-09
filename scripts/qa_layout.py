#!/usr/bin/env python3
"""
qa_layout.py — PPT Master SVG 版面客观复核（不看图也能判断）

三项检查：
  1. overflow  : 文本是否超出画布安全区（正确处理 text-anchor=start/middle/end）
  2. panel     : 图片面板区域是否真的有内容（不为纯色/不为空白）
  3. contrast  : 渲染后文字区域是否满足 WCAG 4.5:1
                 （2026-10-08 起：Otsu 二分类定背景/笔画，不再用写死的 20/99.5 分位）

2026-10-08 三处误判修正（用户授权，带回归对账）：
  A. check_line_collisions 旧版拿 `x` 属性差 ≤24 当"同列"，既不解析 text-anchor
     （middle/end 下 x 只是锚点不是左边界），也漏判长文本尾巴压邻段 → 改判"渲染盒
     水平 + 垂直双向重叠"。
  B. panels_of 旧版只认 clipPath 里的 `<rect>`；而 vendor 门禁明写"局部/偏移裁切必须
     用 `<path>`/`<polygon>`，`<rect>` 只允许覆盖整幅" → 合规写法反被报"无独立图片面板"。
  C. check_contrast 旧版用固定分位（背景=20 分位、笔画=99.5 分位）代理"背景 vs 笔画"，
     大字号细笔画时墨量占比 <20%，两类同时落在背景上 → 96px «不等于设计» 被误判 1.4:1。

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
DEFAULT_MARGIN = 76
MARGIN = DEFAULT_MARGIN
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

def anchor_left(x, w, anchor):
    """text-anchor → 渲染盒左边界。三处检查共用，别再各写一遍。"""
    if anchor == "middle":
        return x - w / 2
    if anchor == "end":
        return x - w
    return x

def text_span(t, anc):
    """一个 <text> 的渲染盒信息；空文本返回 None。
    返回 (left, width, baseline_y, size, txt)。"""
    txt = "".join(t.itertext()).strip()
    if not txt:
        return None
    x = float(t.get("x", 0) or 0)
    y = float(t.get("y", 0) or 0)
    size = inherited_font_size(t, anc)
    mono = mono_family(t.get("font-family", "") or t.get("style", ""))
    ls = float(t.get("letter-spacing", 0) or 0)
    w = text_width(txt, size, mono, ls)
    return anchor_left(x, w, t.get("text-anchor", "start")), w, y, size, txt

# ---------------------------------------------------------------- 溢出
def check_overflow(root, margin=MARGIN):
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
        left = anchor_left(x, w, anchor)
        right = left + w
        if right > CANVAS_W - margin + 1:
            issues.append(f"右溢出 {right - (CANVAS_W - margin):.0f}px  «{txt[:24]}»")
        if left < margin - 1:
            issues.append(f"左溢出 {(margin - left):.0f}px  «{txt[:24]}»")
    return issues

# ---------------------------------------------------------------- 面板
DEFAULT_RAMP = {11, 13, 16, 20, 24, 32, 44, 56, 96, 160}


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


def _bbox_of_numbers(s):
    """从 path `d` / polygon `points` 取包围盒。
    只对**绝对坐标的直角路径**（M/L/H/V/Z，面板裁切全是这一类）保证准确：
    H/V 的单数字会与下一个值配对，但极值仍落在真包围盒内。
    含曲线/弧命令时控制点可能越出实际轮廓 → 结果是**偏大**的保守盒。"""
    vals = re.findall(r"[-+0-9.eE]+", s or "")
    if len(vals) < 2:
        return None
    nums = [float(v) for v in vals]
    xs, ys = nums[0::2], nums[1::2]
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

def panels_of(root):
    """返回 (id, x, y, w, h) —— 带 clip-path 的 <image>，即独立图片面板"""
    out = []
    clips = {}
    for cp in root.iter(NS + "clipPath"):
        cid = cp.get("id")
        if not cid:
            continue
        r = cp.find(NS + "rect")
        if r is not None:
            clips[cid] = tuple(float(r.get(k, 0) or 0) for k in ("x", "y", "width", "height"))
            continue
        # 2026-10-08 修正 B：vendor 门禁要求局部裁切必须用 <path>/<polygon>
        # （<rect> 只允许覆盖整幅），旧版只认 rect → 合规写法反被报"无独立图片面板"。
        for el in list(cp):
            tag = el.tag.rsplit("}", 1)[-1]
            src = el.get("d") if tag == "path" else (
                el.get("points") if tag == "polygon" else None)
            if src is None:
                continue
            bb = _bbox_of_numbers(src)
            if bb:
                clips[cid] = bb
                break
    for im in root.iter(NS + "image"):
        ref = im.get("clip-path", "")
        m = re.search(r"url\(#([^)]+)\)", ref)
        if not m:
            continue
        geo = clips.get(m.group(1))
        if not geo:
            continue
        # 与 <image> 自身矩形求交：裁切盒越界（曲线控制点外扩）时收敛回真实可见区
        cx, cy, cw, ch = geo
        try:
            ix = float(im.get("x", 0) or 0); iy = float(im.get("y", 0) or 0)
            iw = float(im.get("width", 0) or 0); ih = float(im.get("height", 0) or 0)
        except ValueError:
            iw = ih = 0
        if iw > 0 and ih > 0:
            x0, y0 = max(cx, ix), max(cy, iy)
            x1, y1 = min(cx + cw, ix + iw), min(cy + ch, iy + ih)
            if x1 > x0 and y1 > y0:
                geo = (x0, y0, x1 - x0, y1 - y0)
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
    """改版式挪动文字后，相邻两行可能压到一起。
    2026-10-08 修正 A：判据从"`x` 属性差 ≤24 视为同列"换成"**渲染盒**双向重叠"。
    旧判据不解析 text-anchor（middle/end 下 x 只是锚点），实测把徽标圆内的
    middle 数字与旁边的节点名误判成压行；同时它还会漏判
    "x 差得远但长文本尾巴压到邻段"。workflow_full 18 页里这类误报共 29 条。
    行框 = [baseline - 0.80*size, baseline + 0.25*size]；列框 = 按 anchor 展开后的 [left, left+w]。
    同一基线（|Δbaseline| ≤ 0.30×字号）的两段是**行内并排**（项目符号 + 正文、
    数字 + 单位），本就应当首尾相接，且测宽是启发式、有几像素误差 → 这一类要求
    横向重叠 ≥8px 才算撞；跨行堆叠的仍是 ≥4px。"""
    boxes = []
    for t, anc in _iter_with_parents(root):
        if t.tag != NS + "text":
            continue
        sp = text_span(t, anc)
        if sp is None:
            continue
        left, w, y, size, txt = sp
        boxes.append((left, left + w, y - 0.80 * size, y + 0.25 * size, y, size, txt))
    out = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a_l, a_r, a_t, a_b, a_y, a_s, a_x = boxes[i]
            b_l, b_r, b_t, b_b, b_y, b_s, b_x = boxes[j]
            hov = min(a_r, b_r) - max(a_l, b_l)
            ov = min(a_b, b_b) - max(a_t, b_t)
            same_line = abs(a_y - b_y) <= 0.30 * max(a_s, b_s)
            if hov >= (8.0 if same_line else 4.0) and ov > 2:
                out.append(f"压行 横向{hov:.0f}px×纵向{ov:.0f}px «{a_x[:14]}» × «{b_x[:14]}»")
    return out


def _otsu_threshold(vals):
    """Otsu 二分类阈值（只用 numpy，不引 scipy）。返回灰度值。"""
    hist, edges = np.histogram(vals, bins=64, range=(0.0, 256.0))
    centers = (edges[:-1] + edges[1:]) / 2
    p = hist / max(1, int(hist.sum()))
    w = np.cumsum(p)
    s = np.cumsum(p * centers)
    denom = w * (1.0 - w)
    np.seterr(invalid="ignore")
    var = np.where(denom > 0, (s[-1] * w - s) ** 2 / np.where(denom > 0, denom, 1), -1.0)
    return float(centers[int(np.argmax(var))])

DECOR = set("✓✗!+·—→·※◆■●○①②③④⑤⑥⑦⑧⑨⑩")

def _weight_of(t) -> int:
    """取 <text> 的有效字重：属性优先，其次 style:font-weight，再继承父 g。默认 400。"""
    w = t.get("font-weight")
    if w is None:
        m = re.search(r"font-weight\s*:\s*(\d+)", t.get("style", "") or "")
        w = m.group(1) if m else None
    return int(w) if w and str(w).isdigit() else 400

def wcag_need(size: float, weight: int, text: str) -> float:
    """对比度门槛分档：正文 4.5；大字 3.0（size>=32，或 size>=24 且 weight>=700）；
    单字符装饰符号按非文本图形 3.0，不豁免。"""
    body = "".join(ch for ch in text if ch.strip())
    if len(body) == 1:
        return 3.0
    if size >= 32 or (size >= 24 and weight >= 700):
        return 3.0
    return WCAG_MIN

def check_scale(root, ramp: set) -> list[str]:
    """同屏相邻层级必须跨 >=2 档且尺度差 >=2.5x；一级标题字号同屏只能出现一次。"""
    sizes: dict[int, int] = {}
    for t, anc in _iter_with_parents(root):
        if t.tag != NS + "text":
            continue
        sp = text_span(t, anc)
        if sp is None:
            continue
        sizes[int(round(sp[3]))] = sizes.get(int(round(sp[3])), 0) + 1
    used = {s: c for s, c in sizes.items() if c > 0}
    bad = []
    # 一级标题字号同屏只能出现一次
    n_l1 = sum(c for s, c in used.items() if s >= 44)
    if n_l1 > 1:
        bad.append(f"一级标题字号同屏出现 {n_l1} 次（应仅 1 处断言）")
    # 相邻层级跨档检查
    ordered = sorted(s for s in used if s in ramp)
    if len(ordered) < 2:
        return bad
    big = [s for s in ordered if s >= 44]
    for a, b in zip(ordered, ordered[1:]):
        # 只约束"相邻层级"，同属大字号之间不算；
        # 仅当较大尺寸 ≥44（一级标题档）时才检查过渡是否充分
        if b < 44:
            continue
        if a in big and b in big:
            continue
        if a in big or b in big:
            idx_a = big.index(a) if a in big else -1
            idx_b = big.index(b) if b in big else -1
            if idx_a >= 0 and idx_b >= 0 and idx_b - idx_a < 2 and b / a < 2.5:
                bad.append(f"{a}px→{b}px 未跨 2 档且尺度差 {b/a:.2f}<2.5")
            elif (idx_a >= 0) != (idx_b >= 0) and b / a < 2.0:
                bad.append(f"{a}px→{b}px 未跨 2 档且尺度差 {b/a:.2f}<2.0")
    return bad

def check_grid_step(root, step: int = 8, tol: float = 1.0) -> list[str]:
    """元素 y 坐标应落 step 步进（warn 用，不 blocking）。"""
    off = []
    for t, anc in _iter_with_parents(root):
        if t.tag not in (NS + "text", NS + "rect", NS + "line"):
            continue
        raw = t.get("y") if t.tag == NS + "text" else t.get("y", t.get("y1"))
        if raw is None:
            continue
        try:
            y = float(re.match(r"[-\d.]+", str(raw)).group(0))
        except Exception:
            continue
        if abs(y / step - round(y / step)) * step > tol:
            off.append(f"{t.tag.split('}')[-1]} y={y:g}")
    return off

def check_contrast(img, root):
    """对每段文本，取渲染图中文字包围盒，判 WCAG 对比度。
    2026-10-08 修正 C：背景/笔画改用 Otsu 二分类 + 少数类"核心端"取色。
    旧版写死 背景=20 分位 / 笔画=99.5 分位，隐含假设墨量占比 ≈20%；
    大字号细笔画（96px 中文）墨量只有百分之几，两个分位同时落在背景上 →
    «不等于设计» 被误判 1.4:1（像素统计证明底是 242、字是 6）。"""
    rgb = np.asarray(img.convert("RGB"), dtype=np.float64)
    g = rgb.mean(axis=2)
    rows = []
    for t, anc in _iter_with_parents(root):
        if t.tag != NS + "text":
            continue
        sp = text_span(t, anc)
        if sp is None:
            continue
        left, w, y, size, txt = sp
        x0 = int(max(0, left)); x1 = int(min(img.width, left + w))
        y0 = int(max(0, y - size * 0.85)); y1 = int(min(img.height, y + size * 0.25))
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        reg = g[y0:y1, x0:x1]
        area = rgb[y0:y1, x0:x1]
        if reg.size < 30 or (reg.max() - reg.min()) < 2:
            continue                      # 区域几乎单色：没有字，或框没套住字
        thr = _otsu_threshold(reg)
        lo, hi = reg <= thr, reg > thr
        if not lo.any() or not hi.any():
            continue
        if lo.sum() > hi.sum():           # 暗像素占多数 → 暗底亮字
            bg_m = lo
            q = np.quantile(reg[hi], 0.75)
            st_m = hi & (reg >= q)        # 最亮的一档才是笔画核心，抗锯齿边缘不计入
        else:                             # 亮底暗字
            bg_m = hi
            q = np.quantile(reg[lo], 0.25)
            st_m = lo & (reg <= q)
        if not st_m.any():
            continue
        bg = area[bg_m].mean(axis=0)
        gl = area[st_m].mean(axis=0)
        L1, L2 = lum(gl), lum(bg)
        if L1 < L2:
            L1, L2 = L2, L1
        ratio = (L1 + 0.05) / (L2 + 0.05)
        rows.append((ratio, txt, size, wcag_need(size, _weight_of(t), txt)))
    return rows

# ---------------------------------------------------------------- main
def main():
    global MARGIN, DEFAULT_RAMP
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    svg_dir, render_dir = sys.argv[1], sys.argv[2]
    # spec_lock 在 <project>/spec_lock.md，svg_dir 是 <project>/svg_output
    spec = os.path.join(os.path.dirname(os.path.abspath(svg_dir)), "spec_lock.md")

    # 尝试从 spec_tokens 读取版式常量
    try:
        import spec_tokens as ST
        tok = ST.load(spec)
        MARGIN = tok.margin
        DEFAULT_RAMP = set(tok.ramp)
        print(f"[tokens] margin={tok.margin} ramp={sorted(tok.ramp)}")
    except Exception as e:
        print(f"[tokens][警告] 未读到 spec_lock，用兜底 margin={MARGIN} ramp={sorted(DEFAULT_RAMP)}：{e}")

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

        ov = check_overflow(root, margin=MARGIN)
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

        sv = check_scale(root, DEFAULT_RAMP)
        for s in sv:
            print(f"    [尺度] {s}")
        bad += len(sv)
        if not sv:
            print("  [尺度] OK")

        tok_step = 8
        try:
            import spec_tokens as ST
            tok = ST.load(spec)
            tok_step = tok.baseline_step
        except Exception:
            pass
        gt = check_grid_step(root, step=tok_step)
        if gt:
            print(f"    [网格][warn] {len(gt)} 处未落 {tok_step}px 步进：" + "; ".join(gt[:4]))
        else:
            print(f"  [网格] OK（{tok_step}px 步进）")

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
            fails = [r for r in rows if r[0] < (r[3] if len(r) > 3 else WCAG_MIN)]
            print(f"  [对比] 最低 {worst[0]:.1f}:1  «{worst[1][:20]}»  "
                  f"| 不达标 {len(fails)}/{len(rows)}")
            for r in fails[:6]:
                ratio, t, s = r[0], r[1], r[2]
                print(f"          {ratio:.1f}:1  «{t[:26]}» ({s:.0f}px)")
                bad += 1

    print("\n" + "=" * 60)
    print("ALL CLEAR ✅" if bad == 0 else f"待修 {bad} 项 ⚠️")
    return 0 if bad == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
