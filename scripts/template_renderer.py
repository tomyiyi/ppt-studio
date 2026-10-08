#!/usr/bin/env python3
"""模板驱动 SVG 渲染器 v3：flat 模式兼容 + 严格文本边界。"""
from pathlib import Path
import html
import re
import sys

try:
    from cover_v2 import fit_font_size, split_cover_title, disp_width, get_cover_font_family, detect_mood, COVER_VARIANTS, generate_cover_copy
    HAS_COVER_V2 = True
except ImportError:
    HAS_COVER_V2 = False
try:
    from table_layout import parse_md_table, render_table_svg
    HAS_TABLE = True
except ImportError:
    HAS_TABLE = False
try:
    from cover_v2 import detect_mood
    HAS_MOOD = True
except ImportError:
    HAS_MOOD = False
try:
    from agnes_color import get_accent_color
    HAS_ACCENT = True
except ImportError:
    HAS_ACCENT = False

TEMPLATE_ROOT = Path(
    "/Volumes/3TB_DATA/05-开发项目/ppt/tools/ppt-master/skills/ppt-master/templates/layouts"
)

LAYOUT_MAP = {
    "cover": {
        "with_image": ("editorial_bleed", "01_hero_full.svg"),
        "without_image": ("presentation_core", "01_title_slide.svg"),
    },
    "bullets": {
        "with_image": ("editorial_bleed", "02_hero_side_scrim.svg"),
        "without_image": ("presentation_core", "02_title_content.svg"),
    },
    "compare": {
        "with_image": ("presentation_core", "05_comparison.svg"),
        "without_image": ("presentation_core", "05_comparison.svg"),
    },
    "table": {  # 数据表：空白底，标题+真表格全自绘
        "with_image": ("presentation_core", "07_blank.svg"),
        "without_image": ("presentation_core", "07_blank.svg"),
    },
    "steps": {
        "with_image": ("presentation_core", "14_process_timeline.svg"),
        "without_image": ("presentation_core", "14_process_timeline.svg"),
    },
    # === 专题设计规范 v1：阅读功能版式 ===
    "statement": {  # 金句页：一句话观点，居中放大
        "with_image": ("editorial_bleed", "09_full_statement.svg"),
        "without_image": ("presentation_core", "10_hero_statement.svg"),
    },
    "fact": {  # 大数字页：KPI 式数据展示
        "with_image": ("presentation_core", "13_kpi_dashboard.svg"),
        "without_image": ("presentation_core", "13_kpi_dashboard.svg"),
    },
    "quote": {  # 引用页
        "with_image": ("editorial_bleed", "06_quote_over_image.svg"),
        "without_image": ("presentation_core", "10_hero_statement.svg"),
    },
    "section": {  # 章节页：引子/过渡
        "with_image": ("editorial_bleed", "05_chapter_full.svg"),
        "without_image": ("presentation_core", "03_section_header.svg"),
    },
    "closing": {  # 收束页：金句 + CTA
        "with_image": ("editorial_bleed", "10_closing_full.svg"),
        "without_image": ("editorial_bleed", "10_closing_full.svg"),
    },
}

# flat 模式禁用的属性（模板自带，需剥离）
FLAT_FORBIDDEN = [
    "data-pptx-master",
    "data-pptx-master-name",
    "data-pptx-layout",
    "data-pptx-layout-name",
    "data-pptx-carrier",
    "data-pptx-layer",
    "data-pptx-placeholder",
    "data-pptx-editable",
    "data-pptx-idx",
]


def esc(s):
    return html.escape(str(s), quote=False)


def strip_flat_forbidden(svg):
    for attr in FLAT_FORBIDDEN:
        svg = re.sub(r'\s+' + attr + r'="[^"]*"', "", svg)
    return svg


def wrap_text(text, max_chars):
    """断行：优先在标点/空格处断，但超过 max_chars+4 必须硬断。

    旧实现只在标点处断，中英混排的无标点串（如 0→0.92 / 0.45→0.80）会一路加宽，
    实测画到 676px 而槽位只有 640px，门禁按 horizontal overflow 判 error。
    """
    if len(text) <= max_chars:
        return [text]
    lines = []
    cur = ""
    for ch in text:
        cur += ch
        if len(cur) >= max_chars and (ch in "，。；：、） " or len(cur) >= max_chars + 4):
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    return lines or [text]


def split_title(title, max_chars=14):
    """标题分行，不截断。返回行列表。中英混排时英文按单词断。"""
    # 计算显示宽度：中文算1，英文算0.6
    def disp_w(s):
        w = 0
        for ch in s:
            w += 1 if ord(ch) > 127 else 0.6
        return w
    if disp_w(title) <= max_chars:
        return [title]
    lines, cur, cur_w = [], "", 0
    # 按词切分（保留分隔符）
    import re as _re
    tokens = _re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+|.", title)
    for tok in tokens:
        tw = disp_w(tok)
        if cur_w + tw > max_chars and cur:
            lines.append(cur); cur, cur_w = "", 0
        cur += tok; cur_w += tw
    if cur: lines.append(cur)
    if len(lines) > 3:
        lines = lines[:2] + ["".join(lines[2:])]
    return lines


def _slot_bounds(svg, pos, default=(80.0, 356.0, 640.0, 200.0)):
    """取 pos 之前最近一个带 data-pptx-bounds 的 <g>，即该文本所属槽位 (x, y, w, h)。
    槽位几何才是文字能占的真实空间：写死的 540 对 hero-side(底 556) 与
    title-content(底 632) 都偏浅，会静默丢掉尾部 bullet。"""
    best = None
    for mm in re.finditer(r'<g\b([^>]*)>', svg[:pos]):
        bb = re.search(r'data-pptx-bounds="([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"', mm.group(1))
        if bb:
            best = tuple(float(v) for v in bb.groups())
    return best or default


def _slot_bottom(svg, pos, default=540):
    x, y, w, h = _slot_bounds(svg, pos)
    return y + h if h else default


FIT_SIZES = (22, 20, 16)   # 降档阶梯；20/16 即 spec_lock 的 lead / body 档


def _fit_plan(items, slot_w, y, max_y, font_size):
    """在字号阶梯上找第一个能把全部条目装进 [y, max_y] 的档位。

    每行字符数由槽位宽度反推（中文一个字符约占字号那么多像素），
    条目总高 = 行数*行高 + 条目间距。放不下返回 None，由调用方换版式或硬失败。
    """
    fallback = None
    for size in [s for s in FIT_SIZES if s <= font_size] or [font_size]:
        lh = max(int(size * 1.3), 20)
        # 一个中文字约等于字号宽，实测字体略宽 -> 取 1.15 安全系数；
        # 再扣掉首行圆点偏移与续行缩进（合计约 2.2 个字号）。
        mc = max(12, int((slot_w - size * 2.2) / (size * 1.15)))
        per = [wrap_text(b, mc) for b in items]
        need = sum(len(ls) * lh + lh // 2 + 8 for ls in per)
        if need <= (max_y - y) + lh:
            return size, lh, mc, per
        if fallback is None:
            fallback = (size, lh, mc, per)
    return None


def bullets_to_svg(bullets, x, y, font_size, fill, line_h, max_chars=22, max_items=0,
                   max_y=540, accent=None, slot_w=640):
    """Bullets 渲染：字号按槽位几何自适应降档，必须把条目全画出来。

    放不下返回 None。历史上这里写死 font-size=22 / 单条 3 行 / 最多 4 条，
    hero-side 的 200px 槽只够 2 条，其余条目被无声吃掉。
    """
    items = [b.strip() for b in bullets if b and b.strip()]
    if max_items:
        items = items[:max_items]
    if not items:
        return ""
    plan = _fit_plan(items, slot_w, y, max_y, font_size)
    if plan is None:
        return None
    font_size, line_h, max_chars, per_lines = plan
    out = []
    cy = y
    for lines in per_lines:
        for li, line in enumerate(lines):
            if li == 0 and accent:
                # 首行 • 标记用 agnes 强调色
                out.append(
                    '<text x="%d" y="%d" fill="%s" font-family="Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif" '
                    'font-size="%d">%s</text>'
                    % (x, cy, accent, font_size, esc("\u2022 "))
                )
                out.append(
                    '<text x="%d" y="%d" fill="%s" font-family="Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif" '
                    'font-size="%d">%s</text>'
                    % (x + int(font_size * 0.9), cy, fill, font_size, esc(line))
                )
            else:
                prefix = "  "
                out.append(
                    '<text x="%d" y="%d" fill="%s" font-family="Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif" '
                    'font-size="%d">%s</text>'
                    % (x, cy, fill, font_size, esc(prefix + line))
                )
            cy += line_h
        cy += line_h // 2  # 条目间距
        cy += 8
    return "\n".join(out)



# ---- scrim 自适应：文字在底图上始终够对比度，同时不把图压成灰板 ----
SCRIM_TARGET_L = 0.183   # 带图页文字为纯白(L=1.0)，4.5:1 要求背景相对亮度 <= 0.183
SCRIM_MIN_A = 0.10       # 底图本身够暗时的遮罩下限（再低等于不加遮罩）
SCRIM_MAX_A = 0.90       # 再高左半就糊成纯黑，等于没图


def _body_slot_frac(svg):
    """正文槽在画面中的归一化矩形 (x0, y0, x1, y1)，模板坐标系 1280x720。"""
    m = re.search(r'<g\b[^>]*data-pptx-placeholder="body"[^>]*data-pptx-bounds='
                  r'"([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"', svg)
    if not m:
        return 80 / 1280.0, 356 / 720.0, 720 / 1280.0, 556 / 720.0
    x, y, w, h = (float(m.group(i)) for i in range(1, 5))
    return x / 1280.0, y / 720.0, (x + w) / 1280.0, (y + h) / 720.0


def _band_luminance(image_path, x0, y0, x1, y1):
    """底图在文字带上的平均相对亮度（sRGB，gamma 2.2 近似）。"""
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        im = Image.open(image_path).convert("L").resize((64, 36))
        px = im.load()
        c0, c1 = max(0, int(x0 * 64)), max(1, int(x1 * 64))
        r0, r1 = max(0, int(y0 * 36)), max(1, int(y1 * 36))
        vals = [(px[c, r] / 255.0) ** 2.2 for c in range(c0, c1) for r in range(r0, r1)]
    except Exception:
        return None
    return sum(vals) / len(vals) if vals else None


def tune_scrim_to_image(svg, images_dir, image_file):
    """按底图实测亮度等比缩放每个 scrim 渐变的不透明度（保留模板的渐变形状）。

    锚点取「文字右边缘正下方那个 stop」：遮罩自左向右衰减，最右端是文字最吃紧处，
    该处需要多强，整条渐变就按同一比例放大或缩小。
    """
    if not image_file:
        return svg
    path = Path(images_dir) / image_file
    if not path.exists():
        return svg
    x0, y0, x1, y1 = _body_slot_frac(svg)
    lum = _band_luminance(path, x0, y0, x1, y1)
    if lum is None:
        return svg
    need = min(SCRIM_MAX_A, max(SCRIM_MIN_A, 1.0 - SCRIM_TARGET_L / max(lum, 1e-4)))
    if lum > 0.40:
        # 亮底图 + 压得够深的遮罩 = 图没了。这页真正该改的是图，不是遮罩。
        sys.stderr.write("[WARN] %s 文字带亮度 %.2f 偏高：遮罩需压到 %.2f 才够 4.5:1，"
                         "底图会被压死。建议重出图时在 prompt 里指定 dark/low-key 背景。\n"
                         % (image_file, lum, need))

    def _fix(gm):
        head, inner, tail = gm.group(1), gm.group(2), gm.group(3)
        gid = re.search(r'id="([^"]+)"', head).group(1)
        rw = 1280.0   # 遮罩矩形宽度：渐变 offset 是按它铺的，不等于整幅画布宽
        for _rm in re.finditer(r'<rect\b[^>]*>', svg):
            if 'url(#%s)' % gid in _rm.group(0):
                _wm = re.search(r'width="([\d.]+)"', _rm.group(0))
                if _wm:
                    rw = float(_wm.group(1))
                break
        stops = re.findall(r'offset="([\d.]+)"[^>]*?stop-opacity="([\d.]+)"', inner)
        solid = [(float(o), v) for o, v in stops if float(v) > 0]
        if not solid:
            return gm.group(0)
        in_text = [s for s in solid if s[0] * rw / 1280.0 <= x1 + 0.08]
        k = need / float((in_text or solid)[-1][1])
        out = inner
        for _o, val_s in stops:
            new = round(min(SCRIM_MAX_A, max(0.0, float(val_s) * k)), 2)
            if abs(new - float(val_s)) < 0.005:
                continue
            out = out.replace('stop-opacity="%s"' % val_s, 'stop-opacity="%s"' % new, 1)
        sys.stderr.write("[SCRIM] %s 文字带亮度 %.3f -> 渐变整体 x%.2f\n"
                         % (gid, lum, k))
        return head + out + tail

    return re.sub(r'(<linearGradient\b[^>]*scrim[^>]*>)(.*?)(</linearGradient>)',
                  _fix, svg, flags=re.S)


def render_page(page, images_dir):
    layout = page.get("layout", "bullets")
    _raw_title = page.get("title", "")
    _title_lines = split_title(_raw_title)
    title = _raw_title  # 完整标题，分行在占位符替换时处理
    bullets = page.get("bullets", [])
    image_file = page.get("image_file")

    mapping = LAYOUT_MAP.get(layout, LAYOUT_MAP["bullets"])
    has_img = bool(image_file) and (images_dir / image_file).exists()
    family, tpl_file = mapping["with_image"] if has_img else mapping["without_image"]
    _cover_variant = page.get("cover_variant", "hero_full") if layout == "cover" else None
    if layout == "cover" and HAS_COVER_V2:
        _vspec = COVER_VARIANTS.get(_cover_variant or "hero_full", COVER_VARIANTS["hero_full"])
        family, tpl_file = _vspec["template"]
        if not _vspec["use_image"]:
            has_img = False  # minimal 纯文字构图，不用底图

    svg = (TEMPLATE_ROOT / family / "templates" / tpl_file).read_text(encoding="utf-8")
    # CJK 字体优先：Noto Sans SC > PingFang SC > Microsoft YaHei > Arial
    svg = svg.replace('font-family="Arial, Microsoft YaHei, sans-serif"',
                      'font-family="Noto Sans SC, PingFang SC, Microsoft YaHei, Arial, sans-serif"')
    # agnes 配色注入：mood -> 强调色
    _mood = detect_mood(_raw_title, page.get("subtitle", "")) if HAS_MOOD else ""
    _accent = get_accent_color(_mood) if HAS_ACCENT else None
    svg = svg.replace('width="1280" height="720"', 'width="1920" height="1080"', 1)

    # 背景图 slot 的 bounds 会与文字重叠（设计使然），先去掉避免 QA 误报
    # 注意：必须在 strip_flat_forbidden 之前，此时 placeholder 属性还在
    svg = re.sub(r'(<g[^>]*data-pptx-placeholder="picture"[^>]*?)\s+data-pptx-bounds="[^"]*"', r"\g<1>", svg)
    # scrim 强度按底图实测亮度自适应（不再写死 0.55/0.35）
    if has_img:
        svg = tune_scrim_to_image(svg, images_dir, image_file)
    # 剥离 flat 禁用属性
    svg = strip_flat_forbidden(svg)

    if has_img:
        rel = "../images/" + image_file
        # image 标签跨多行，DOTALL 匹配；剥离后 carrier 属性没了，用 id 匹配
        svg2 = re.sub(
            r'(<image\s[^>]*?id="[^"]*picture-carrier"[^>]*?href=")[^"]*(")',
            r"\g<1>" + rel + r"\g<2>",
            svg,
            count=1,
            flags=re.DOTALL,
        )
        if "../images/" not in svg2:
            # editorial_bleed hero 的 image slot
            svg2 = re.sub(
                r'(<image\s[^>]*?href=")data:image[^"]*(")',
                r"\g<1>" + rel + r"\g<2>",
                svg,
                count=1,
                flags=re.DOTALL,
            )
        svg = svg2
        # 规范化 image 标签为单行（svg_to_pptx 兼容性）：href 优先
        def _norm_img(m):
            tag = m.group(0)
            href = re.search(r'href="([^"]*)"', tag, re.DOTALL)
            x = re.search(r'x="([^"]*)"', tag); y = re.search(r'y="([^"]*)"', tag)
            w = re.search(r'width="([^"]*)"', tag); h = re.search(r'height="([^"]*)"', tag)
            par = re.search(r'preserveAspectRatio="([^"]*)"', tag)
            if not href: return tag
            return '<image href="%s" x="%s" y="%s" width="%s" height="%s" preserveAspectRatio="%s"/>' % (
                href.group(1), x.group(1) if x else "0", y.group(1) if y else "0",
                w.group(1) if w else "1280", h.group(1) if h else "720",
                par.group(1) if par else "xMidYMid slice")
        svg = re.sub(r'<image\s[^>]*?/>', _norm_img, svg, flags=re.DOTALL)
        # 把 image 提升到顶层（svg_to_pptx 只处理顶层 image）
        m_img = re.search(r'<image\s[^>]*?/>', svg, flags=re.DOTALL)
        if m_img:
            img_tag = m_img.group(0)
            svg = svg.replace(img_tag, "", 1)
            # z-order 修正：图必须在 master-background 之上，否则被不透明底色盖住。
            # （旧逻辑插到 defs/<svg> 之后 = 背景之前，v4 封面图实际不可见）
            _bgm = re.search(r'<rect[^>]*id="master-background"[^>]*/>', svg)
            if _bgm:
                svg = svg.replace(_bgm.group(0), _bgm.group(0) + img_tag, 1)
            elif "<defs>" in svg:
                svg = svg.replace("</defs>", "</defs>" + img_tag, 1)
            else:
                svg = re.sub(r'(<svg[^>]*>)', r"\g<1>" + img_tag, svg, count=1)

    # 标题分行：找到 title carrier，替换为多行 text
    title_lines = split_title(_raw_title, max_chars=12)
    # 先占位，后面统一处理
    reps = {
        "{{TITLE}}": "__TITLE_MULTILINE__",
        "{{PAGE_TITLE}}": "__TITLE_MULTILINE__",
        "{{SUBTITLE}}": esc(page.get("subtitle", "")),
        "__TITLE_LINES__": title_lines,
    }

    if "{{CONTENT_AREA}}" in svg and layout != "cover":
        m = re.search(
            r'<text[^>]*x="(\d+)" y="(\d+)"[^>]*fill="([^"]+)"[^>]*font-size="(\d+)"[^>]*>\{\{CONTENT_AREA\}\}</text>',
            svg,
        )
        if m:
            x, y, fill, fs = int(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4))
            _sx, _sy, _sw, _sh = _slot_bounds(svg, m.start())
            if has_img:
                fill = "#FFFFFF"   # 底图上浅灰字对比度不够，纯白可让遮罩少压 ~15%
            multi = bullets_to_svg(bullets, x, y, fs, fill, fs + 16,
                                   max_y=_sy + _sh, accent=_accent, slot_w=_sw)
            if multi is None:
                raise OverflowError("bullets 放不下：槽位 %dx%d，%d 条 / %d 字"
                                    % (int(_sw), int(_sh), len(bullets),
                                       sum(len(b) for b in bullets)))
            svg = svg.replace(m.group(0), multi)
        else:
            if len(bullets) > 2:
                print("[WARN] CONTENT_AREA 文本元素未被匹配，%d 条只并入前 2 条（模板属性顺序变了？）"
                      % len(bullets), file=sys.stderr)
            reps["{{CONTENT_AREA}}"] = esc(" / ".join(bullets[:2]))
    if "{{BODY_TEXT}}" in svg and layout != "cover":
        m = re.search(r'<text[^>]*>\{\{BODY_TEXT\}\}</text>', svg)
        if m:
            cm = re.search(r'x="(\d+)" y="(\d+)"[^>]*font-size="(\d+)"', m.group(0))
            if cm:
                x, y, fs = int(cm.group(1)), int(cm.group(2)), int(cm.group(3))
                fillm = re.search(r'fill="([^"]+)"', m.group(0))
                fill = fillm.group(1) if fillm else "#334155"
                multi = bullets_to_svg(bullets, x, y, fs, fill, fs + 16, max_chars=26,
                                       max_y=_slot_bottom(svg, m.start()), accent=_accent)
                svg = svg.replace(m.group(0), multi)

    if layout == "compare":
        l = page.get("left", {})
        r = page.get("right", {})
        if not l and not r:
            # 回退：从 bullets 解析表格，或前后对半分
            _tbl = [b for b in bullets if b.strip().startswith("|") and "---" not in b]
            if len(_tbl) >= 2:
                # Markdown 表格：跳过表头，取数据行
                _rows = []
                for row in _tbl[1:]:
                    cells = [c.strip() for c in row.strip("|").split("|")]
                    if cells and cells[0]:
                        _rows.append(cells)
                if _rows:
                    _mid = (len(_rows) + 1) // 2
                    l = {"title": "前半", "items": ["%s：%s" % (r[0][:8], r[1][:16]) for r in _rows[:_mid]]}
                    r = {"title": "后半", "items": ["%s：%s" % (r[0][:8], r[1][:16]) for r in _rows[_mid:]]}
            if not l:
                _mid = (len(bullets) + 1) // 2
                l = {"title": "要点", "items": bullets[:_mid]}
                r = {"title": "续", "items": bullets[_mid:]}
        reps.update(
            {
                "{{LEFT_TITLE}}": esc(l.get("title", "")[:12]),
                "{{RIGHT_TITLE}}": esc(r.get("title", "")[:12]),
                "{{LEFT_CONTENT}}": esc(" / ".join(l.get("items", [])[:2])[:60]),
                "{{RIGHT_CONTENT}}": esc(" / ".join(r.get("items", [])[:2])[:60]),
            }
        )
    if layout == "table" and HAS_TABLE:
        # 数据表：解析 Markdown 表格，生成真表格 SVG
        _th, _trs = parse_md_table(bullets)
        if _th and _trs:
            reps["__TABLE_SVG__"] = render_table_svg(_th, _trs, title=page.get("title", ""))
            # 清空 bullets，避免模板再画一遍
            reps["{{BULLETS}}"] = ""
            reps["{{LEFT_CONTENT}}"] = ""
            reps["{{RIGHT_CONTENT}}"] = ""
    
    if layout == "steps":
        steps = page.get("steps", bullets)
        for i in range(1, 5):
            s = steps[i - 1] if i - 1 < len(steps) else ""
            reps["{{STEP_%d}}" % i] = esc(s[:16])
        reps["{{KEY_MESSAGE}}"] = esc(page.get("takeaway", "")[:30])
    # === 专题设计规范 v1：阅读功能版式填充 ===
    if layout == "statement":
        reps["{{KEY_MESSAGE}}"] = esc(_raw_title)
        reps["{{SUPPORT_TEXT}}"] = esc(" / ".join(bullets[:2])[:60])
        reps["{{SUBTITLE}}"] = esc(" / ".join(bullets[:2])[:60])
    if layout == "fact":
        reps["{{PAGE_TITLE}}"] = "__TITLE_MULTILINE__"
        # 从 bullets 提取数字
        kpis = []
        for b in bullets[:4]:
            m = re.search(r"(\d+[%倍]?)", b)
            num = m.group(1) if m else ""
            kpis.append((num, b[:30]))
        for i in range(1, 5):
            if i - 1 < len(kpis):
                reps["{{KPI_%d}}" % i] = esc(kpis[i-1][0][:12])
            else:
                reps["{{KPI_%d}}" % i] = ""
        reps["{{CONTENT_AREA}}"] = esc(bullets[0][:30] if bullets else "")
    if layout == "quote":
        reps["{{QUOTE_TEXT}}"] = esc(_raw_title)
        reps["{{ATTRIBUTION}}"] = esc(" / ".join(bullets[:1])[:40])
    if layout == "section":
        reps["{{CHAPTER_TITLE}}"] = "__TITLE_MULTILINE__"
        reps["{{CHAPTER_DESC}}"] = esc(" / ".join(bullets[:1])[:30])
    if layout == "closing":
        # 收束页：CLOSING_MESSAGE 是标题，CONTACT_LINE 放金句+总结
        reps["{{CLOSING_MESSAGE}}"] = esc(_raw_title[:24])
        # 两条合成一句，不断章：取第一条金句 + 第二条前40字
        _parts = []
        if bullets:
            _parts.append(bullets[0][:20])
        if len(bullets) > 1:
            _parts.append(bullets[1][:40])
        _cl = "——".join(_parts)[:36]
        reps["{{CONTACT_LINE}}"] = esc(_cl)
    if layout == "cover":
        # 封面文案：agnes copy_templates 公式（hook > 公式改写 > 原标题）
        _mood = detect_mood(_raw_title, page.get("subtitle", ""))
        _copy = generate_cover_copy(_raw_title, _mood, page.get("hook"),
                                    page.get("subtitle", "")) if HAS_COVER_V2 else None
        _hook = _copy["title"] if _copy else re.split(r"[：:——]", _raw_title)[0].strip()[:20]
        _cover_sub = _copy["subtitle"] if _copy else page.get("subtitle", "")[:30]
        reps["{{KEY_MESSAGE}}"] = "__TITLE_MULTILINE__"
        _variant = page.get("cover_variant", "hero_full")
        if HAS_COVER_V2:
            _vspec = COVER_VARIANTS.get(_variant, COVER_VARIANTS["hero_full"])
            reps["__TITLE_LINES__"] = split_cover_title(_hook, max_lines=_vspec["max_lines"])
            reps["__COVER_V2__"] = True
            reps["__COVER_CW__"] = str(_vspec["container_width"])
            reps["__COVER_FONTCAP__"] = str(_vspec["font_cap"])
            if _vspec.get("centered"):
                # minimal 居中：标题与副标题锚点移到中央
                svg = re.sub(r'(<text[^>]*id="hero-statement-title-carrier"[^>]*?)x="96"',
                             r'\1x="640" text-anchor="middle"', svg, count=1)
                svg = re.sub(r'(<text[^>]*id="hero-statement-subtitle-carrier"[^>]*?)x="96"',
                             r'\1x="640" text-anchor="middle"', svg, count=1)
        else:
            reps["__TITLE_LINES__"] = split_title(_hook, max_chars=10)
        reps["{{SUPPORT_TEXT}}"] = esc(_cover_sub)
        reps["{{SUBTITLE}}"] = esc(_cover_sub)  # hero_full 模板用 {{SUBTITLE}}
        if _variant == "split":
            # split 左文：CONTENT_AREA 放副标题纯文本（无 bullet 前缀）
            reps["{{CONTENT_AREA}}"] = esc(_cover_sub[:60])

    # 多行标题：找到包含 __TITLE_MULTILINE__ 的 text，展开为多行
    title_lines = reps.pop("__TITLE_LINES__", [])
    _cover_v2_flag = reps.pop("__COVER_V2__", False)
    _cover_cw = reps.pop("__COVER_CW__", None)
    _cover_fontcap = reps.pop("__COVER_FONTCAP__", None)
    _table_svg = reps.pop("__TABLE_SVG__", "")
    for k, v in reps.items():
        svg = svg.replace(k, v)
    if _table_svg:
        # 表格注入到内容区（</svg> 前）
        svg = svg.replace("</svg>", _table_svg + "\n</svg>", 1)
    if layout == "cover" and _accent:
        # agnes 细规线：标题槽位下方 3px 强调色线条
        import re as _re
        _tm = _re.search(r'<g id="[^"]*title-slot"[^>]*data-pptx-bounds="([\d ]+)"', svg)
        if _tm:
            _bx = [int(v) for v in _tm.group(1).split()]
            # bounds: x y w h -> 规线在 y+h+16 处，宽 64px
            _rx, _ry = _bx[0], _bx[1] + _bx[3] + 16
            _rule = ('<rect id="agnes-accent-rule" x="%d" y="%d" width="64" height="4" fill="%s" '
                     'data-pptx-role="decoration" data-agnes-accent="true"/>'
                     % (_rx, _ry, _accent))
            svg = svg.replace("</svg>", _rule + "\n</svg>", 1)
    if "__TITLE_MULTILINE__" in svg and title_lines:
        m = re.search(r'<text([^>]*?)>__TITLE_MULTILINE__</text>', svg, re.DOTALL)
        if m:
            attrs, x, y, fs = m.group(1), 0, 0, 44
            xm = re.search(r'x="(\d+)"', attrs); ym = re.search(r'y="(\d+)"', attrs)
            fm = re.search(r'font-size="(\d+)"', attrs)
            if xm: x = int(xm.group(1))
            if ym: y = int(ym.group(1))
            if fm: fs = int(fm.group(1))
            # 长标题对齐 spec_lock 声明档位，避免溢出槽位
            # 档位: subtitle 24 / title 32 / headline 44 / statement 56 / cover 96
            _n = len(title_lines[:3])
            _is_cover = (layout == "cover")
            # Cover v2 (neo式): 每行字号自适应铺满
            _cover_v2 = _is_cover and HAS_COVER_V2 and _cover_v2_flag
            if _cover_v2:
                # 容器宽度：按 variant 规格（hero_full 1120 / split 480 / minimal 1088）
                _cw = int(_cover_cw) if _cover_cw else 1000
                _fcap = int(_cover_fontcap) if _cover_fontcap else 72
                # 每行独立计算字号
                _sizes = [fit_font_size(l, _cw, base_size=_fcap) for l in title_lines[:3]]
                fs = _sizes[0] if _sizes else 96
                _lh = fs + 10
                _n = len(title_lines[:3])
                if _n > 1:
                    y = y - (_n - 1) * _lh // 2
                # 衬线字体
                _mood = detect_mood(page.get("title", ""), page.get("subtitle", ""))
                _serif = get_cover_font_family(_mood)
            if not _cover_v2 and _n == 3:
                fs = 44 if _is_cover else 24
                _lh = fs + 6
                y = y - (_n - 1) * _lh // 2
            elif not _cover_v2 and _n == 2:
                # 有图 hero 版槽位更矮，用 32
                fs = 32 if _is_cover else 32
                _lh = fs + 8
                y = y - _lh // 2 - (10 if _is_cover else 0)
            else:
                # 单行也对齐档位：模板自带的 36 不在 spec_lock 声明中
                if not _is_cover:
                    fs = 32  # title 档
                _lh = fs + 12
            fill = re.search(r'fill="([^"]+)"', attrs)
            fill = fill.group(1) if fill else "#FFFFFF"
            multi = []
            for i, line in enumerate(title_lines[:3]):
                _sync = attrs
                _sz = _sizes[i] if (_cover_v2 and i < len(_sizes)) else fs
                _sync = __import__("re").sub('font-size="[0-9]+"', 'font-size="%d"' % _sz, _sync)
                _sync = __import__("re").sub('y="[0-9]+"', "", _sync)
                if _cover_v2:
                    _sync = __import__("re").sub('font-family="[^"]+"', 'font-family="%s"' % _serif, _sync)
                _lh_i = _sz + 10 if _cover_v2 else _lh
                multi.append('<text%s y="%d">%s</text>' % (_sync, y + i * _lh_i, esc(line)))
            svg = svg.replace(m.group(0), "\n".join(multi))
            if len(multi) > 1:
                # 多行标题：id 去重 + 把标题槽 bounds 扩到能装下（下方 object 槽从 176 起，封顶 136）
                for _i in range(1, len(multi)):
                    multi[_i] = multi[_i].replace('id="title-content-title-carrier"',
                                                  'id="title-content-title-carrier-%d"' % (_i + 1))
                _need_h = (y + _lh * (len(multi) - 1)) + int(fs * 0.35) - 40
                _need_h = max(72, min(136, int(_need_h)))
                # 封顶不能写死：要以「下一个槽位的上边界」为限，否则标题槽会压进
                # 正文槽（hero-side_scrim 的 body 槽从 356 起，136 会溢出 16px）。
                _ts = re.search(r'<g\b[^>]*title-slot[^>]*data-pptx-bounds='
                                r'"([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"', svg)
                if _ts:
                    _ty = float(_ts.group(2))
                    _below = [float(mm.group(2)) for mm in re.finditer(
                        r'<g\b[^>]*data-pptx-bounds="([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"', svg)
                        if float(mm.group(2)) > _ty]
                    if _below:
                        _need_h = max(64, min(_need_h, int(min(_below) - _ty - 4)))
                svg = re.sub(r'(<g id="[^"]*title-slot"[^>]*data-pptx-bounds=")(\d+) (\d+) (\d+) (\d+)(")',
                             lambda mm: '%s%s %s %s %d%s' % (mm.group(1), mm.group(2), mm.group(3),
                                                             mm.group(4), _need_h, mm.group(6)),
                             svg, count=1)
    svg = re.sub(r"\{\{[A-Z_0-9]+\}\}", "", svg)
    return svg


def main():
    import argparse
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--images", required=True)
    a = ap.parse_args()

    raw = json.loads(Path(a.pages).read_text(encoding="utf-8"))
    pages = raw["pages"] if isinstance(raw, dict) and "pages" in raw else raw
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    imgd = Path(a.images)
    failed = []
    for i, pg in enumerate(pages):
        name = "%02d_%s.svg" % (i, pg.get("layout", "bullets"))
        try:
            svg = render_page(pg, imgd)
        except OverflowError as e:
            # 内容优先于装饰：带图版式装不下就弃底图，改用同版式的纯文字模板重试
            if pg.get("image_file"):
                print("[INFO] p%02d 条目超出带图槽位，弃底图改纯文字版式重试（%s）"
                      % (i, e), file=sys.stderr)
                _plain = dict(pg)
                _plain["image_file"] = None
                try:
                    svg = render_page(_plain, imgd)
                except OverflowError as e2:
                    failed.append("p%02d %s（换纯文字版式仍放不下）" % (i, e2))
                    continue
            else:
                failed.append("p%02d %s" % (i, e))
                continue
        (out / name).write_text(svg, encoding="utf-8")
    if failed:
        print("[FAIL] %d 页条目溢出，请回 md_to_pages 拆页或精简原文：" % len(failed),
              file=sys.stderr)
        for f in failed:
            print("   - " + f, file=sys.stderr)
        return 1
    print("done: %d pages -> %s" % (len(pages), out))
    return 0


if __name__ == "__main__":
    main()
