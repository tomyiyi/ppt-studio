#!/usr/bin/env python3
"""
qa_layout.py — PPT Master SVG 版面客观复核（不看图也能判断）

八项检查：
  1. overflow  : 文本是否超出画布安全区（正确处理 text-anchor=start/middle/end）
  2. panel     : 图片面板区域是否真的有内容（不为纯色/不为空白）
  3. contrast  : 渲染后文字区域是否满足 WCAG 4.5:1（背景=区域20分位，笔画=99.5分位）
  4. typescale : 所有字号是否合规于 spec_lock.md 阶梯
  5. backdrop  : 底图是否铺满画布（≥90%）
  6. dup_images: 同一源图是否在单页出现两次
  7. collision : 相邻文本行是否压行/碰撞
  8. statement : 跨正文页主句 (statement) 字号是否绝对统一，防范"一时大一时小"

用法：
  python3 qa_layout.py [target] [render_dir] [--spec spec_lock.md]
例：
  python3 qa_layout.py .
  python3 qa_layout.py projects/agentflow-os-launch
  python3 qa_layout.py projects/agentflow-os-launch/svg_output projects/agentflow-os-launch/render
"""
import os
import re
import sys
import glob
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from collections import Counter
import xml.etree.ElementTree as ET

# 确保在未显式激活 .venv 时也能从项目内 .venv 加载依赖
try:
    import numpy as np
    from PIL import Image
except ImportError:
    repo_root = Path(__file__).resolve().parent.parent
    for site_pkg in repo_root.glob(".venv/lib/python*/site-packages"):
        if site_pkg.is_dir() and str(site_pkg) not in sys.path:
            sys.path.insert(0, str(site_pkg))
    import numpy as np
    from PIL import Image

NS = "{http://www.w3.org/2000/svg}"
CANVAS_W, CANVAS_H = 1280, 720
MARGIN = 60
_CANVAS_OVERRIDDEN = False  # --canvas explicit => True, skip spec auto-read
WCAG_MIN = 4.5

# 检查项严重度（借鉴 ppt-master：只有客观失败算 error，品味问题算 warning）
# final 阶段要求 0 error；early 阶段 error 即阻塞继续生成
SEVERITY = {
    "overflow": "error",    # 文本溢出画布：客观失败
    "collision": "error",   # 压行碰撞：客观失败
    "contrast": "error",    # 对比度不足：客观失败
    "dup_images": "error",  # 同图重影：客观失败
    "typescale": "warning", # 字号偏离阶梯：可修
    "backdrop": "warning",  # 底图未铺满：风格选择
    "panel": "warning",     # 面板墨量不足：可调
    "statement": "warning", # 主句跨页不一致：需人工判断
    "role_discipline": "warning", # breathing 页多卡片：违反版式角色纪律
}

# role 纪律：breathing 页最多允许的卡片数（ppt-master 差距3）
BREATHING_MAX_CARDS = 2

# ---------------------------------------------------------------- 基础数值解析
def parse_num(val, default: float = 0.0) -> float:
    """安全解析可能包含单位 (如 px) 或空白的数值字符串。"""
    if val is None:
        return float(default)
    s = str(val).strip()
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            pass
    return float(default)


# ---------------------------------------------------------------- 文本测宽
def char_w(ch, mono=False):
    o = ord(ch)
    if o > 0x2E80:          # CJK / 全角
        return 1.0
    if mono:
        return 0.60
    return 0.52             # 拉丁字母比例字体近似

def text_width(s, size, mono=False, ls=0.0, family=None):
    """文本宽度：优先 PIL 实测（text_measure），失败回退字符启发式。"""
    try:
        from text_measure import measure as _pil_measure
        w = _pil_measure(s, int(round(size)), family)
        if w is not None:
            return w + ls * max(0, len(s) - 1)
    except Exception:
        pass
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
        x = parse_num(t.get("x", 0))
        size = inherited_font_size(t, anc)
        ls = parse_num(t.get("letter-spacing", 0))
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
DEFAULT_RAMP = {11, 13, 16, 20, 24, 32, 44, 56, 96}


def load_canvas_from_spec(spec_lock_path):
    """Read viewBox: 0 0 W H from spec_lock.md ## canvas. Returns (w,h) or (None,None)."""
    try:
        from pathlib import Path as _P
        txt = _P(spec_lock_path).read_text(encoding="utf-8")
    except OSError:
        return None, None
    m = re.search(r"viewBox\s*:\s*0\s+0\s+(\d+)\s+(\d+)", txt)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def load_margin_from_spec(spec_lock_path):
    """Read margin: Npx from spec_lock.md. Returns int or None."""
    try:
        from pathlib import Path as _P
        txt = _P(spec_lock_path).read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"margin\s*[:\uff1a]\s*(\d+)\s*px", txt)
    return int(m.group(1)) if m else None


def load_ramp(spec_lock_path):
    """从 spec_lock.md 读字号阶梯（单一事实源）。
    支持 `- role: 数字`、`- sizes: [11, 13, ...]` 两种规范格式，支持行内注释。"""
    try:
        with open(spec_lock_path, encoding="utf-8") as f:
            txt = f.read()
    except OSError:
        return set(DEFAULT_RAMP)

    out = set()
    # 格式 1: - sizes: [11, 13, 16, 20, 24, 32, 44, 56, 96]
    m_sizes = re.search(r"-\s*sizes:\s*\[([0-9,\s]+)\]", txt)
    if m_sizes:
        for x in m_sizes.group(1).split(","):
            s = x.strip()
            if s.isdigit():
                out.add(int(s))

    # 格式 2: ## typography 段下的 - role: 数字
    m = re.search(r"^##\s+typography\s*$(.*?)(?=^##\s|\Z)", txt, re.S | re.M)
    if m:
        for line in m.group(1).splitlines():
            line = line.split("#")[0].strip()
            if not line:
                continue
            mm = re.match(r"^-\s*\w+\s*:\s*(\d+)\s*$", line)
            if mm:
                out.add(int(mm.group(1)))

    return out or set(DEFAULT_RAMP)


def load_spec_roles(spec_lock_path):
    """从 spec_lock.md 的 ## typography 段读取 (role -> font_size) 映射。"""
    try:
        with open(spec_lock_path, encoding="utf-8") as f:
            txt = f.read()
    except OSError:
        return {}
    m = re.search(r"^##\s+typography\s*$(.*?)(?=^##\s|\Z)", txt, re.S | re.M)
    if not m:
        return {}
    roles = {}
    for line in m.group(1).splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        mm = re.match(r"^-\s*(\w+)\s*:\s*(\d+)\s*$", line)
        if mm:
            roles[mm.group(1)] = int(mm.group(2))
    return roles


def check_statement_consistency(svg_slides: list[tuple[str, ET.Element]], expected_sz: int = 56) -> tuple[bool, str]:
    """验证正文页页面主句 (statement) 字号在跨页翻阅时是否严格一致。
    防范事故：主句在不同页被随手写成 44/56/72，导致翻页时字号'一时大一时小'。"""
    content_slides = [
        (stem, root) for stem, root in svg_slides
        if not (stem.startswith("01") or "cover" in stem.lower())
    ]
    if len(content_slides) < 2:
        return True, "页数较少，跳过跨页主句一致性比对"

    statement_slides = {}
    for stem, root in content_slides:
        sizes = []
        for t, anc in _iter_with_parents(root):
            if t.tag != NS + "text":
                continue
            if t.get("data-decorative") == "true":
                continue  # 装饰性水印（如 225px 页码）不是主句，不参与跨页一致性比对
            txt = "".join(t.itertext()).strip()
            if not txt:
                continue
            s = int(round(inherited_font_size(t, anc)))
            sizes.append((s, txt))
        if not sizes:
            continue
        large_sizes = [s for s, _ in sizes if s >= 40]
        if not large_sizes:
            continue
        top_sz = max(large_sizes)
        top_txt = next(txt for s, txt in sizes if s == top_sz)
        statement_slides[stem] = (top_sz, top_txt)

    if not statement_slides:
        return True, "未检测到正文页主句"

    counts = Counter(sz for sz, _ in statement_slides.values())
    target_sz = expected_sz if expected_sz in counts else counts.most_common(1)[0][0]

    drifts = []
    aligned = []
    for stem, (sz, txt) in sorted(statement_slides.items()):
        if sz != target_sz:
            drifts.append(f"{stem} ({sz}px: «{txt[:16]}»)")
        else:
            aligned.append(stem)

    if drifts:
        return False, f"发现主句字号漂移 (预期 {target_sz}px，漂移页: {', '.join(drifts)})"

    aligned_labels = ", ".join(s.split("_")[0] for s in aligned)
    return True, f"各正文页主句字号严格对齐 ({target_sz}px) · 页面 [{aligned_labels}] 无漂移"


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
    v = t.get("font-size")
    if v:
        s = parse_num(v, -1.0)
        if s > 0:
            return s
    for a in reversed(anc):
        v = a.get("font-size")
        if v:
            s = parse_num(v, -1.0)
            if s > 0:
                return s
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
        w = parse_num(im.get("width", 0))
        h = parse_num(im.get("height", 0))
        if w > 0 and h > 0:
            areas.append(w * h)
    if not areas:
        return None
    return 100.0 * max(areas) / (CANVAS_W * CANVAS_H)


def check_dup_images(root):
    """同一张源图在一页里出现两次 = 同一个图形被画了两遍，视觉上是"重影"。
    典型事故：全幅铺底用 xxx_bg.png，右半面板又用 xxx_bg_panel.png。"""
    srcs = []
    for im in root.iter(NS + "image"):
        href = im.get("href") or im.get("{http://www.w3.org/1999/xlink}href") or ""
        if not href:
            continue
        h = os.path.basename(href)
        # 去除扩展名，并去除 _panel 后缀以对齐源图名称
        stem = Path(h).stem
        normalized = re.sub(r"_panel$", "", stem)
        if normalized:
            srcs.append(normalized)
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
            clips[cid] = tuple(parse_num(r.get(k, 0)) for k in ("x", "y", "width", "height"))
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

def check_role_discipline(root, page_id, page_map, canvas_w, canvas_h):
    """breathing 节奏页禁止多卡片网格（role 纪律）。

    page_map: {P01: {role, rhythm}}；rhythm=breathing 的页卡片数 ≤ BREATHING_MAX_CARDS。
    卡片启发式：非背景 rect（宽150-800、高100-600、有填充）。
    返回 (ok, msg)。
    """
    rhythm = (page_map.get(page_id) or {}).get("rhythm", "")
    if rhythm != "breathing":
        return True, "非 breathing 页，跳过"
    cards = 0
    for r in root.iter("{http://www.w3.org/2000/svg}rect"):
        try:
            w = float(r.get("width", 0)); h = float(r.get("height", 0))
        except ValueError:
            continue
        if not (150 <= w <= 800 and 100 <= h <= 600):
            continue
        if r.get("fill", "") in ("none", "transparent"):
            continue
        # 排除铺满画布的背景
        if w * h > canvas_w * canvas_h * 0.8:
            continue
        cards += 1
    ok = cards <= BREATHING_MAX_CARDS
    msg = "breathing 页卡片 %d 个%s" % (
        cards, " OK" if ok else " > %d，违反 role 纪律（应留白呼吸）" % BREATHING_MAX_CARDS)
    return ok, msg


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
        if t.get("data-decorative") == "true":
            continue  # 装饰性水印不参与对比度门禁
        txt = "".join(t.itertext()).strip()
        if not txt:
            continue
        x = parse_num(t.get("x", 0)); y = parse_num(t.get("y", 0))
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


def spec_polarity(spec_path):
    """从 spec_lock 的 background 颜色判定文字采样极性。"""
    if not spec_path:
        return "dark"
    try:
        text = Path(spec_path).read_text(encoding="utf-8")
    except OSError:
        return "dark"
    m = re.search(r"^\s*-\s*background:\s*(#[0-9A-Fa-f]{6})", text, re.M)
    if not m:
        return "dark"
    h = m.group(1)
    rgb = tuple(int(h[i:i+2], 16) for i in (1, 3, 5))
    return "light" if lum(rgb) >= 0.5 else "dark"


def check_contrast(img, root, polarity="dark"):
    """对每段文本，取渲染图中文字包围盒：背景=20分位亮度，笔画=99.5分位亮度"""
    rgb = np.asarray(img.convert("RGB"), dtype=np.float64)
    g = rgb.mean(axis=2)
    rows = []
    for t, anc in _iter_with_parents(root):
        if t.tag != NS + "text":
            continue
        if t.get("data-decorative") == "true":
            continue  # 装饰性水印不参与对比度门禁
        txt = "".join(t.itertext()).strip()
        if not txt:
            continue
        x = parse_num(t.get("x", 0))
        y = parse_num(t.get("y", 0))
        size = inherited_font_size(t, anc)
        anchor = t.get("text-anchor", "start")
        mono = mono_family(t.get("font-family", "") or t.get("style", ""))
        ls = parse_num(t.get("letter-spacing", 0))
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
        gray = reg
        if polarity == "light":
            stroke_t = np.percentile(gray, 0.5)
            bg_t = np.percentile(gray, 80)
            stroke_mask = gray <= stroke_t
            bg_mask = gray >= bg_t
        else:
            bg_t = np.percentile(gray, 20)
            stroke_t = np.percentile(gray, 99.5)
            bg_mask = gray <= bg_t
            stroke_mask = gray >= stroke_t
        if not bg_mask.any() or not stroke_mask.any():
            continue
        bg = rgb[y0:y1, x0:x1][bg_mask].mean(axis=0)
        gl = rgb[y0:y1, x0:x1][stroke_mask].mean(axis=0)
        L1, L2 = lum(gl), lum(bg)
        if L1 < L2:
            L1, L2 = L2, L1
        ratio = (L1 + 0.05) / (L2 + 0.05)
        rows.append((ratio, txt, size))
    return rows

# ---------------------------------------------------------------- main
def qa_single_layout(
    svg_dir_or_file: Path | str | None,
    render_dir: Path | str | None = None,
    spec_path: Path | str | None = None,
    verbose: bool = True,
    stage: str | None = None,
    early_n: int = 5,
) -> bool:
    """对单个 SVG 文件或 SVG 目录执行客观版面门禁复核。"""
    def _log(msg: str = "", file=sys.stdout) -> None:
        if verbose:
            print(msg, file=file)

    if svg_dir_or_file is None:
        _log("[!] 未提供有效的目标路径", file=sys.stderr)
        return False

    target = Path(svg_dir_or_file).resolve()
    if not target.exists():
        _log(f"[!] 指定的目标路径不存在: {target}", file=sys.stderr)
        return False

    if target.is_file():
        if target.suffix.lower() != ".svg":
            _log(f"[!] 指定文件不是 SVG 文件: {target}", file=sys.stderr)
            return False
        svg_files = [target]
        svg_dir = target.parent
    else:
        # 如果 target 包含 svg_output 子目录且当前目录无 svg，则自动切入 svg_output
        if not list(target.glob("*.svg")) and (target / "svg_output").is_dir():
            svg_dir = (target / "svg_output").resolve()
        else:
            svg_dir = target
        svg_files = sorted(svg_dir.glob("*.svg"))

    if stage == "early":
        # 只取前 N 页做方法样本（按文件名页码排序）
        def _page_key(p):
            m = re.match(r"(\d+)_", p.stem)
            return int(m.group(1)) if m else 9999
        svg_files = sorted(svg_files, key=_page_key)[:early_n]
        _log("[stage=early] 方法样本：前 %d 页 %s" % (
            early_n, [p.stem for p in svg_files]))

    if not svg_files:
        _log("[!] 在 %s 未找到任何 .svg 文件" % svg_dir, file=sys.stderr)
        return False

    # 查找 spec（版本感知：同目录 spec_lock_vN.md 优先于 spec_lock.md，见 spec_resolve）
    if spec_path:
        spec = Path(spec_path).resolve()
        if not spec.exists():
            _log(f"[warn] 找不到指定的 spec_lock.md ({spec})，用默认阶梯", file=sys.stderr)
            spec = None
    else:
        from scripts.spec_resolve import find_spec

        spec = find_spec(svg_dir)
        if spec:
            _log(f"[i] 采用 spec: {spec}", file=sys.stderr)

    ramp = load_ramp(str(spec)) if spec else DEFAULT_RAMP

    # canvas auto-read: unless --canvas given, read viewBox from spec_lock.md
    if not _CANVAS_OVERRIDDEN and spec:
        _cw, _ch = load_canvas_from_spec(str(spec))
        if _cw and _ch:
            global CANVAS_W, CANVAS_H, MARGIN
            CANVAS_W, CANVAS_H = _cw, _ch
            _sm = load_margin_from_spec(str(spec))
            MARGIN = _sm if _sm else round(60 * _cw / 1280)
            _log(f"[canvas] from spec {_cw}x{_ch}, MARGIN={MARGIN}")
    roles = load_spec_roles(str(spec)) if spec else {}
    expected_stmt_sz = roles.get("statement", 56)

    # page_map 加载（role 纪律检查用）
    page_map = {}
    if spec:
        try:
            from check_page_map import parse_page_map
            page_map = parse_page_map(Path(str(spec)))
        except Exception:
            page_map = {}

    # 自动查找 render_dir (若未提供)
    if render_dir:
        resolved_render = Path(render_dir).resolve()
    else:
        resolved_render = None
        for candidate in [
            svg_dir.parent / "render",
            svg_dir.parent / "qa_render",
            svg_dir.parent / "render_cards",
            svg_dir / "render",
        ]:
            if candidate.is_dir():
                resolved_render = candidate.resolve()
                break

    _log("=" * 60)
    _log("🔍 运行 PPT-Studio SVG 版面客观复核与质量门禁")
    _log(f"   目标位置: {target}")
    _log(f"   渲染目录: {resolved_render if resolved_render else '未提供（跳过渲染面板/对比度复核）'}")
    _log(f"   规范配置: {spec if spec else '默认阶梯'}")
    _log("=" * 60)
    _log(f"字号阶梯: {sorted(ramp)}")
    if "statement" in roles:
        _log(f"跨页主句预期字号: {expected_stmt_sz}px (来自 {spec.name})")

    # 渲染目录可能是 <name>.png/<name>.png 的嵌套结构
    def find_png(stem):
        if not resolved_render or not resolved_render.is_dir():
            return None
        for pat in (f"{stem}.png", f"{stem}/*.png", f"**/{stem}.png"):
            hit = [p for p in glob.glob(os.path.join(str(resolved_render), pat), recursive=True)
                   if os.path.isfile(p)]
            if hit:
                return hit[0]
        return None

    bad = 0
    svg_slides = []
    for svg_path in svg_files:
        stem = svg_path.stem
        try:
            root = ET.parse(svg_path).getroot()
        except Exception as e:
            _log(f"\n=== {stem} ===")
            _log(f"  [XML] ⚠️ 无法解析 SVG 文件: {e}")
            bad += 1
            continue
        svg_slides.append((stem, root))

        _log(f"\n=== {stem} ===")

        used, off = check_typescale(root, ramp)
        line = "  ".join(f"{k}×{v}" for k, v in sorted(used.items()))
        if off:
            bad += len(off)
            _log(f"  [字号] {line}   ⚠️ 越出阶梯: {off}")
        else:
            _log(f"  [字号] {line}   OK（{len(used)} 档）")

        # role 纪律：breathing 页禁止多卡片网格
        page_id = stem[:3].upper() if stem[:1].isdigit() else stem.split("_")[0].upper()
        if page_id[:1].isdigit():
            page_id = "P" + page_id[:2].zfill(2) if len(page_id) >= 2 else page_id
        ok_role, msg_role = check_role_discipline(root, page_id, page_map, CANVAS_W, CANVAS_H)
        if not ok_role:
            bad += 1
        _log(f"  [角色] {msg_role}")

        cov = check_backdrop(root)
        if cov is None:
            _log("  [底图] 无图片")
        else:
            ok = cov >= 90.0
            if not ok:
                bad += 1
            _log(f"  [底图] 覆盖画布 {cov:.1f}%  {'OK' if ok else '⚠️ 未铺满，不是底图'}")

        dups = check_dup_images(root)
        if dups:
            bad += len(dups)
            for d in dups:
                _log(f"  [重影] 同一张源图用了两次：{d}  →  一页只保留一个图位")
        else:
            _log("  [重影] OK（每张源图仅一次）")

        ov = check_overflow(root)
        if ov:
            bad += len(ov)
            for i in ov:
                _log(f"  [溢出] {i}")
        else:
            _log("  [溢出] OK")

        col = check_line_collisions(root)
        if col:
            bad += len(col)
            for c in col[:8]:
                _log(f"  [压行] {c}")
        else:
            _log("  [压行] OK")

        png = find_png(stem)
        if not png:
            _log("  [渲染] 未找到对应 PNG，跳过面板/对比度检查")
            continue
        img = Image.open(png)

        ps = panels_of(root)
        if not ps:
            _log("  [面板] 无独立图片面板")
        for name, x, y, w, h in ps:
            line = check_panel(img, (x, y, w, h), name)
            _log(f"  [面板] {line}")
            if "⚠️" in line:
                bad += 1

        rows = check_contrast(img, root, polarity=spec_polarity(spec))
        if not rows:
            _log("  [对比] 无可测文本")
        else:
            rows.sort()
            worst = rows[0]
            fails = [r for r in rows if r[0] < WCAG_MIN]
            _log(f"  [对比] 最低 {worst[0]:.1f}:1  «{worst[1][:20]}»  "
                 f"| 不达标 {len(fails)}/{len(rows)}")
            for r, t, s in fails[:6]:
                _log(f"          {r:.1f}:1  «{t[:26]}» ({s:.0f}px)")
                bad += 1

    # 跨页主句一致性检查（多页时执行）
    if len(svg_slides) > 1:
        _log("\n=== 跨页一致性 ===")
        ok_stmt, msg_stmt = check_statement_consistency(svg_slides, expected_stmt_sz)
        if ok_stmt:
            _log(f"  [主句] OK  {msg_stmt}")
        else:
            bad += 1
            _log(f"  [主句] ⚠️  {msg_stmt}")

    _log("\n" + "=" * 60)
    _log("ALL CLEAR ✅" if bad == 0 else f"待修 {bad} 项 ⚠️")
    return bad == 0


def run_qa_layout(
    target: Path | str | None = None,
    render_dir: Path | str | None = None,
    spec_path: Path | str | None = None,
    verbose: bool = True,
    stage: str | None = None,
    early_n: int = 5,
) -> bool:
    """运行 PPT-Studio SVG 版面客观质量门禁。

    支持输入单个 SVG 文件路径、SVG 目录、包含 svg_output 的项目目录，或留空默认自发现。
    支持 Path、str 或 None 输入。
    """
    try:
        targets = resolve_layout_dirs(target)
    except (FileNotFoundError, ValueError) as err:
        if verbose:
            print(f"[!] {err}", file=sys.stderr)
        return False

    if not targets:
        if verbose:
            print("[!] 未找到任何待质检的 SVG 目标", file=sys.stderr)
        return False

    all_ok = True
    for i, t in enumerate(targets):
        ok = qa_single_layout(t, render_dir=render_dir, spec_path=spec_path,
                              verbose=verbose, stage=stage, early_n=early_n)
        if not ok:
            all_ok = False
        if verbose and i < len(targets) - 1:
            print()
    return all_ok


qa_layout = run_qa_layout
run_qa_single_layout = qa_single_layout


def resolve_layout_dirs(
    target_arg: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> list[Path]:
    """自适应解析待质检的 SVG 目录或文件。

    1. 若显式指定非 '.' 的 target_arg：
       - 转换为绝对路径并校验存在性，若不存在抛出 FileNotFoundError；
       - 若 target 为文件：若是 SVG 文件，返回 [target.resolve()]；否则抛出 ValueError；
       - 若 target 为目录：
         * 若 (target / "svg_output").is_dir() 且包含 *.svg，返回 [(target / "svg_output").resolve()]；
         * 若 target 包含 *.svg，返回 [target.resolve()]；
         * 若 target 包含 projects/ 目录或自身名为 projects，从中安全发现包含 svg_output/ 或 *.svg 的项目；
         * 否则抛出 FileNotFoundError；
    2. 若未显式指定 target_arg 或为 '.'：
       - 探测 base_dir：
         * 若 (base / "svg_output").is_dir() 且包含 *.svg，返回 [(base / "svg_output").resolve()]；
         * 若 base 包含 *.svg 且 base.name != "ppt-studio"，返回 [base.resolve()]；
       - 从 base/projects 或仓库根目录 projects/ 探测：
         * 收集所有包含 svg_output/ 且有 *.svg 的项目；
         * 若唯一匹配，返回 [唯一目录]；
         * 若有多个匹配，抛出 ValueError；
         * 若未发现匹配，抛出 FileNotFoundError。
    """
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    is_default = (target_arg is None or str(target_arg).strip() in ("", "."))

    if not is_default:
        p = Path(target_arg)
        if not p.is_absolute():
            p = (base / p).resolve()
        else:
            p = p.resolve()

        if not p.exists():
            raise FileNotFoundError(f"指定的目标路径不存在: {target_arg}")

        if p.is_file():
            if p.suffix.lower() == ".svg":
                return [p]
            raise ValueError(f"指定的 target 文件不是 SVG 文件: {target_arg}")

        svg_sub = p / "svg_output"
        if svg_sub.is_dir() and list(svg_sub.glob("*.svg")):
            return [svg_sub.resolve()]

        if list(p.glob("*.svg")):
            return [p.resolve()]

        candidate_projects_dirs: list[Path] = []
        if (p / "projects").is_dir():
            candidate_projects_dirs.append(p / "projects")
        elif p.name == "projects":
            candidate_projects_dirs.append(p)

        p_subprojects: list[Path] = []
        for s_dir in candidate_projects_dirs:
            for sub in sorted(s_dir.iterdir()):
                if sub.is_dir():
                    s_sub = sub / "svg_output"
                    if s_sub.is_dir() and list(s_sub.glob("*.svg")):
                        p_subprojects.append(s_sub.resolve())
                    elif list(sub.glob("*.svg")):
                        p_subprojects.append(sub.resolve())

        if len(p_subprojects) == 1:
            return p_subprojects
        elif len(p_subprojects) > 1:
            names = ", ".join(d.parent.name if d.name == "svg_output" else d.name for d in p_subprojects)
            raise ValueError(
                f"发现多个包含 SVG 的项目 ({names})，无法安全确定，请显式指定 target 参数"
            )

        raise FileNotFoundError(f"在目录 {target_arg} 下未找到有效 SVG 文件或 svg_output/ 子目录")

    # 默认/自适应探测
    if (base / "svg_output").is_dir() and list((base / "svg_output").glob("*.svg")):
        return [(base / "svg_output").resolve()]
    if base.name != "ppt-studio" and list(base.glob("*.svg")):
        return [base.resolve()]

    candidate_projects_dirs = []
    if base.is_dir() and base.name == "projects":
        candidate_projects_dirs.append(base)
    elif (base / "projects").is_dir():
        candidate_projects_dirs.append(base / "projects")
    elif base_dir is None:
        repo_root = Path(__file__).resolve().parent.parent
        p_cand = repo_root / "projects"
        if p_cand.is_dir():
            candidate_projects_dirs.append(p_cand)

    found_svgs: list[Path] = []
    seen: set[Path] = set()
    for p_dir in candidate_projects_dirs:
        for sub in sorted(p_dir.iterdir()):
            if sub.is_dir():
                s_dir = sub / "svg_output"
                if s_dir.is_dir() and list(s_dir.glob("*.svg")):
                    r = s_dir.resolve()
                    if r not in seen:
                        seen.add(r)
                        found_svgs.append(r)
                elif list(sub.glob("*.svg")):
                    r = sub.resolve()
                    if r not in seen:
                        seen.add(r)
                        found_svgs.append(r)
        if found_svgs:
            break

    if len(found_svgs) == 1:
        return found_svgs
    elif len(found_svgs) > 1:
        names = ", ".join(d.parent.name if d.name == "svg_output" else d.name for d in found_svgs)
        raise ValueError(
            f"发现多个包含 SVG 的项目 ({names})，无法安全确定，请显式指定 target 参数"
        )

    raise FileNotFoundError("在当前目录或 projects/ 下未找到有效 SVG 文件")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PPT-Studio SVG 版面客观复核与质量门禁")
    parser.add_argument("target", nargs="?", default=".", help="SVG 目录、项目目录或单文件路径（默认当前目录）")
    parser.add_argument("render_dir", nargs="?", default=None, help="可选渲染图 PNG 目录（缺省时自动查找 render/ 或 qa_render/）")
    parser.add_argument("--spec", help="可选指定 spec_lock.md 路径")
    parser.add_argument("--verbose", "-v", action="store_true", default=True, help="详细日志输出（默认开启）")
    parser.add_argument("--quiet", "-q", action="store_true", help="静默模式（仅通过退出码返回）")
    parser.add_argument("--canvas", default=None, help="画布尺寸 WxH（默认 1280x720；v4 起 1920x1080），覆盖内置常量")
    parser.add_argument("--stage", choices=["early", "final"], default=None,
                        help="early=只查前 N 页（方法样本），error 即阻塞；final=全量，0 error 才通过；不传=传统行为")
    parser.add_argument("--early-n", type=int, default=5, help="early 阶段检查的前 N 页（默认 5）")
    args = parser.parse_args(argv)

    if args.canvas:
        global CANVAS_W, CANVAS_H, MARGIN, _CANVAS_OVERRIDDEN
        _CANVAS_OVERRIDDEN = True
        m = re.match(r"\s*(\d+)\s*[x\u00d7]\s*(\d+)\s*", args.canvas)
        if m:
            CANVAS_W, CANVAS_H = int(m.group(1)), int(m.group(2))
            # margin 优先从 spec 读取（如 "margin: 144px"），读不到才按比例缩放
            spec_margin = None
            if args.spec:
                try:
                    sm = re.search(r"margin\s*[:：]\s*(\d+)\s*px",
                                   Path(args.spec).read_text(encoding="utf-8"))
                    if sm:
                        spec_margin = int(sm.group(1))
                except Exception:
                    pass
            MARGIN = spec_margin if spec_margin else round(60 * CANVAS_W / 1280)
            print(f"[画布] {CANVAS_W}x{CANVAS_H}，MARGIN={MARGIN}")
        else:
            print(f"[warn] --canvas 格式错误 ({args.canvas})，沿用默认 1280x720", file=sys.stderr)

    verbose = not args.quiet if args.quiet else args.verbose
    spec_path = Path(args.spec).resolve() if args.spec else None
    render_dir = Path(args.render_dir).resolve() if args.render_dir else None

    # 如果显式传入两个目录 (target, render_dir)
    if args.render_dir:
        t_path = Path(args.target).resolve()
        if not t_path.exists():
            if verbose:
                print(f"[!] 指定的目标路径不存在: {args.target}", file=sys.stderr)
            return 1
        svg_dir = (t_path / "svg_output").resolve() if (t_path / "svg_output").is_dir() else t_path
        success = qa_single_layout(svg_dir, render_dir, spec_path, verbose=verbose,
                                   stage=args.stage, early_n=args.early_n)
        return 0 if success else 1

    ok = run_qa_layout(args.target, render_dir=render_dir, spec_path=spec_path,
                       verbose=verbose, stage=args.stage, early_n=args.early_n)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
