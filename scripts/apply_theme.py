#!/usr/bin/env python3
import argparse, json, re, shutil
from pathlib import Path

HEX = re.compile(r"#[0-9A-Fa-f]{6}")
TAG = re.compile(r"<[^>]+>")
COLOR_ATTR = re.compile(r'(\b(?:fill|stroke|stop-color)\s*=\s*["\'])(#[0-9A-Fa-f]{6})(["\'])', re.I)
ROOT_SVG = re.compile(r'<svg\b[^>]*>', re.I)
ROOT_FONT = re.compile(r'\sfont-family\s*=\s*("[^"]*"|\'[^\']*\')', re.I)
GRID_GROUP = re.compile(r'<g\b([^>]*\bdata-grid-role\s*=\s*["\']lower-row["\'][^>]*)>', re.I)

def transform_svg(text, mapping, role_mapping):
    def transform_tag(match):
        tag = match.group(0)
        role_match = re.search(r'\bdata-theme-role\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        role_colors = role_mapping.get(role_match.group(1), {}) if role_match else {}
        def replace_color(color_match):
            source = color_match.group(2).upper()
            target = role_colors.get(source, mapping.get(source, source))
            return color_match.group(1) + target + color_match.group(3)
        return COLOR_ATTR.sub(replace_color, tag)
    return TAG.sub(transform_tag, text)

def apply_root_font_family(text, root_font_family):
    if not root_font_family:
        return text
    def replace_root(match):
        tag = match.group(0)
        value = 'font-family="' + root_font_family.replace('&', '&amp;').replace('"', '&quot;') + '"'
        if ROOT_FONT.search(tag):
            return ROOT_FONT.sub(' ' + value, tag, count=1)
        return tag[:-1].rstrip() + ' ' + value + '>'
    return ROOT_SVG.sub(replace_root, text, count=1)

def apply_grid_layout(text, row_gap, column_gap):
    if row_gap is None and column_gap is None:
        return text
    def move_group(match):
        attrs = match.group(1)
        base_match = re.search(r'\bdata-grid-base-gap\s*=\s*["\']([0-9]+(?:\.[0-9]+)?)["\']', attrs, re.I)
        base_column = re.search(r'\bdata-grid-base-column-gap\s*=\s*["\']([0-9]+(?:\.[0-9]+)?)["\']', attrs, re.I)
        column_role = re.search(r'\bdata-grid-column-role\s*=\s*["\']right["\']', attrs, re.I)
        if not base_match and not base_column:
            return match.group(0)
        dx = 0.0
        dy = 0.0
        if row_gap is not None and base_match:
            dy = float(row_gap) - float(base_match.group(1))
        if column_gap is not None and base_column and column_role:
            dx = float(column_gap) - float(base_column.group(1))
        if dx == 0 and dy == 0:
            return match.group(0)
        transform = re.search(r'\btransform\s*=\s*(["\'][^"\']*["\'])', attrs, re.I)
        if transform:
            return match.group(0)
        return '<g' + attrs + ' transform="translate(' + f'{dx:g} {dy:g}' + ')">'
    return GRID_GROUP.sub(move_group, text)

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("source_svg", type=Path)
    p.add_argument("output_svg", type=Path)
    p.add_argument("--theme", required=True, type=Path)
    p.add_argument("--spec-in", type=Path)
    p.add_argument("--spec-out", type=Path)
    a = p.parse_args(argv)
    theme = json.loads(a.theme.read_text(encoding="utf-8"))
    palette = theme["colors"]
    mapping = {k.upper(): v.upper() for k, v in palette.items()}
    role_mapping = {role: {k.upper(): v.upper() for k, v in colors.items()} for role, colors in theme.get("role_colors", {}).items()}
    typography = theme.get("typography", {})
    root_font_family = typography.get("root_font_family")
    grid = theme.get("grid", {})
    row_gap = grid.get("row_gap")
    column_gap = grid.get("column_gap")
    a.output_svg.mkdir(parents=True, exist_ok=True)
    for src in sorted(a.source_svg.glob("*.svg")):
        text = src.read_text(encoding="utf-8")
        text = transform_svg(text, mapping, role_mapping)
        text = apply_root_font_family(text, root_font_family)
        text = apply_grid_layout(text, row_gap, column_gap)
        (a.output_svg / src.name).write_text(text, encoding="utf-8")
    if a.spec_in and a.spec_out:
        spec = a.spec_in.read_text(encoding="utf-8")
        for old, new in mapping.items():
            spec = spec.replace(old, new).replace(old.lower(), new)
        if root_font_family:
            for key in ("font_family", "title_family", "body_family"):
                spec = re.sub(rf"(?m)^(- {key}: ).*$", rf"\g<1>{root_font_family}", spec)
        a.spec_out.write_text(spec, encoding="utf-8")
    print(f"THEME_APPLIED name={theme['name']} files={len(list(a.output_svg.glob('*.svg')))}")

if __name__ == "__main__":
    main()
