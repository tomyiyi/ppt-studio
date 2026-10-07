#!/usr/bin/env python3
"""模板驱动 SVG 渲染器 v3：flat 模式兼容 + 严格文本边界。"""
from pathlib import Path
import html
import re

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
    "steps": {
        "with_image": ("presentation_core", "14_process_timeline.svg"),
        "without_image": ("presentation_core", "14_process_timeline.svg"),
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


def fit_title(title, max_chars=18):
    """标题太长则截断，保证不溢出"""
    if len(title) <= max_chars:
        return title
    # 尽量在标点处截断
    for sep in "：，、 ":
        if sep in title[:max_chars]:
            idx = title[:max_chars].rfind(sep)
            return title[:idx]
    return title[:max_chars]


def bullets_to_svg(bullets, x, y, font_size, fill, line_h, max_chars=18, max_items=2):
    out = []
    cy = y
    for b in bullets[:max_items]:
        b = b.strip()
        if len(b) > 44:
            b = b[:41] + "…"
        lines = wrap_text(b, max_chars)
        for li, line in enumerate(lines[:2]):
            prefix = "• " if li == 0 else "  "
            out.append(
                '<text x="%d" y="%d" fill="%s" font-family="Arial, Microsoft YaHei, sans-serif" '
                'font-size="%d">%s</text>'
                % (x, cy, fill, font_size, esc(prefix + line))
            )
            cy += line_h
        cy += 8
    return "\n".join(out)


def render_page(page, images_dir):
    layout = page.get("layout", "bullets")
    title = fit_title(page.get("title", ""))
    bullets = page.get("bullets", [])
    image_file = page.get("image_file")

    mapping = LAYOUT_MAP.get(layout, LAYOUT_MAP["bullets"])
    has_img = bool(image_file) and (images_dir / image_file).exists()
    family, tpl_file = mapping["with_image"] if has_img else mapping["without_image"]

    svg = (TEMPLATE_ROOT / family / "templates" / tpl_file).read_text(encoding="utf-8")
    svg = svg.replace('width="1280" height="720"', 'width="1920" height="1080"', 1)

    # 背景图 slot 的 bounds 会与文字重叠（设计使然），先去掉避免 QA 误报
    # 注意：必须在 strip_flat_forbidden 之前，此时 placeholder 属性还在
    svg = re.sub(r'(<g[^>]*data-pptx-placeholder="picture"[^>]*?)\s+data-pptx-bounds="[^"]*"', r"\g<1>", svg)
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

    reps = {
        "{{TITLE}}": esc(title),
        "{{PAGE_TITLE}}": esc(title),
        "{{SUBTITLE}}": esc(page.get("subtitle", "")),
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
        reps.update(
            {
                "{{LEFT_TITLE}}": esc(fit_title(l.get("title", ""), 12)),
                "{{RIGHT_TITLE}}": esc(fit_title(r.get("title", ""), 12)),
                "{{LEFT_CONTENT}}": esc(" / ".join(l.get("items", [])[:2])),
                "{{RIGHT_CONTENT}}": esc(" / ".join(r.get("items", [])[:2])),
            }
        )
    if layout == "steps":
        steps = page.get("steps", bullets)
        for i in range(1, 5):
            s = steps[i - 1] if i - 1 < len(steps) else ""
            reps["{{STEP_%d}}" % i] = esc(fit_title(s, 16))
        reps["{{KEY_MESSAGE}}"] = esc(fit_title(page.get("takeaway", ""), 30))
    if layout == "cover":
        reps["{{KEY_MESSAGE}}"] = esc(title)
        reps["{{SUPPORT_TEXT}}"] = esc(fit_title(page.get("subtitle", ""), 30))

    for k, v in reps.items():
        svg = svg.replace(k, v)
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
