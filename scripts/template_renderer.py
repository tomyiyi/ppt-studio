#!/usr/bin/env python3
"""模板驱动 SVG 渲染器 v3：flat 模式兼容 + 严格文本边界。"""
from pathlib import Path
import html
import re

try:
    from cover_v2 import fit_font_size, split_cover_title, disp_width, get_cover_font_family
    HAS_COVER_V2 = True
except ImportError:
    HAS_COVER_V2 = False
try:
    from table_layout import parse_md_table, render_table_svg
    HAS_TABLE = True
except ImportError:
    HAS_TABLE = False

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
    if len(text) <= max_chars:
        return [text]
    lines = []
    cur = ""
    for ch in text:
        cur += ch
        if len(cur) >= max_chars and ch in "，。；：、） ":
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


def bullets_to_svg(bullets, x, y, font_size, fill, line_h, max_chars=22, max_items=4,
                   max_y=540):
    """Bullets 渲染：不硬截断，换行显示，垂直空间内尽量放。
    max_chars=28（中文14字/行），max_y 防止溢出槽位。"""
    out = []
    cy = y
    for b in bullets[:max_items]:
        b = b.strip()
        # 不再用 … 截断：换行显示完整内容
        lines = wrap_text(b, max_chars)[:3]  # 单条最多3行
        # 整条放不下就不放，避免断句
        need_h = len(lines) * line_h + line_h // 2
        if cy + need_h > max_y + line_h:
            break
        for li, line in enumerate(lines):
            prefix = "• " if li == 0 else "  "
            out.append(
                '<text x="%d" y="%d" fill="%s" font-family="Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif" '
                'font-size="%d">%s</text>'
                % (x, cy, fill, font_size, esc(prefix + line))
            )
            cy += line_h
        cy += line_h // 2  # 条目间距
        cy += 8
    return "\n".join(out)


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

    svg = (TEMPLATE_ROOT / family / "templates" / tpl_file).read_text(encoding="utf-8")
    # CJK 字体优先：Noto Sans SC > PingFang SC > Microsoft YaHei > Arial
    svg = svg.replace('font-family="Arial, Microsoft YaHei, sans-serif"',
                      'font-family="Noto Sans SC, PingFang SC, Microsoft YaHei, Arial, sans-serif"')
    svg = svg.replace('width="1280" height="720"', 'width="1920" height="1080"', 1)

    # 背景图 slot 的 bounds 会与文字重叠（设计使然），先去掉避免 QA 误报
    # 注意：必须在 strip_flat_forbidden 之前，此时 placeholder 属性还在
    svg = re.sub(r'(<g[^>]*data-pptx-placeholder="picture"[^>]*?)\s+data-pptx-bounds="[^"]*"', r"\g<1>", svg)
    # 减轻 scrim（模板默认 0.88 太重，图被压没了）：降到 0.55/0.35
    svg = re.sub(r'stop-opacity="0\.88"', 'stop-opacity="0.55"', svg)
    svg = re.sub(r'stop-opacity="0\.62"', 'stop-opacity="0.35"', svg)
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
            # 插到 <svg...> 之后（若有 defs 则插到 defs 之后）
            if "<defs>" in svg:
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

    if "{{CONTENT_AREA}}" in svg:
        m = re.search(
            r'<text[^>]*x="(\d+)" y="(\d+)"[^>]*fill="([^"]+)"[^>]*font-size="(\d+)"[^>]*>\{\{CONTENT_AREA\}\}</text>',
            svg,
        )
        if m:
            x, y, fill, fs = int(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4))
            multi = bullets_to_svg(bullets, x, y, fs, fill, fs + 16)
            svg = svg.replace(m.group(0), multi)
        else:
            reps["{{CONTENT_AREA}}"] = esc(" / ".join(bullets[:2]))
    if "{{BODY_TEXT}}" in svg:
        m = re.search(r'<text[^>]*>\{\{BODY_TEXT\}\}</text>', svg)
        if m:
            cm = re.search(r'x="(\d+)" y="(\d+)"[^>]*font-size="(\d+)"', m.group(0))
            if cm:
                x, y, fs = int(cm.group(1)), int(cm.group(2)), int(cm.group(3))
                fillm = re.search(r'fill="([^"]+)"', m.group(0))
                fill = fillm.group(1) if fillm else "#334155"
                multi = bullets_to_svg(bullets, x, y, fs, fill, fs + 16, max_chars=26)
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
        # 收束页：标题是金句，CONTACT_LINE 放完整总结（不断章）
        reps["{{CLOSING_MESSAGE}}"] = esc(_raw_title[:24])
        _cl = bullets[0][:36] if bullets else ""
        # 第二条总结放到 SUPPORT（如果模板有）
        if len(bullets) > 1:
            reps["{{SUPPORT_TEXT}}"] = esc(bullets[1][:60])
        reps["{{CONTACT_LINE}}"] = esc(_cl)
    if layout == "cover":
        # 封面是钩子：取冒号前的核心标题，避免长标题堆砌溢出
        _hook = re.split(r"[：:——]", _raw_title)[0].strip()
        if len(_hook) > 20:
            _hook = _hook[:20]
        reps["{{KEY_MESSAGE}}"] = "__TITLE_MULTILINE__"
        if HAS_COVER_V2:
            reps["__TITLE_LINES__"] = split_cover_title(_hook)
            reps["__COVER_V2__"] = True
        else:
            reps["__TITLE_LINES__"] = split_title(_hook, max_chars=10)
        reps["{{SUPPORT_TEXT}}"] = esc(page.get("subtitle", "")[:30])

    # 多行标题：找到包含 __TITLE_MULTILINE__ 的 text，展开为多行
    title_lines = reps.pop("__TITLE_LINES__", [])
    _cover_v2_flag = reps.pop("__COVER_V2__", False)
    _table_svg = reps.pop("__TABLE_SVG__", "")
    for k, v in reps.items():
        svg = svg.replace(k, v)
    if _table_svg:
        # 表格注入到内容区（</svg> 前）
        svg = svg.replace("</svg>", _table_svg + "\n</svg>", 1)
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
                # 容器宽度估算：从 attrs 或默认 1000
                _cw = 1000
                _wm = __import__("re").search(r'width="([0-9]+)"', attrs)
                # 每行独立计算字号
                _sizes = [fit_font_size(l, _cw) for l in title_lines[:3]]
                fs = _sizes[0] if _sizes else 96
                _lh = fs + 10
                _n = len(title_lines[:3])
                if _n > 1:
                    y = y - (_n - 1) * _lh // 2
                # 衬线字体
                _serif = get_cover_font_family()
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
    for i, pg in enumerate(pages):
        name = "%02d_%s.svg" % (i, pg.get("layout", "bullets"))
        (out / name).write_text(render_page(pg, imgd), encoding="utf-8")
    print("done: %d pages -> %s" % (len(pages), out))


if __name__ == "__main__":
    main()
