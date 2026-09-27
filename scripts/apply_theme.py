#!/usr/bin/env python3
import argparse, json, re, shutil
from pathlib import Path

HEX = re.compile(r"#[0-9A-Fa-f]{6}")
TAG = re.compile(r"<[^>]+>")
COLOR_ATTR = re.compile(r'(\b(?:fill|stroke|stop-color)\s*=\s*["\'])(#[0-9A-Fa-f]{6})(["\'])', re.I)

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
    a.output_svg.mkdir(parents=True, exist_ok=True)
    for src in sorted(a.source_svg.glob("*.svg")):
        text = src.read_text(encoding="utf-8")
        text = transform_svg(text, mapping, role_mapping)
        (a.output_svg / src.name).write_text(text, encoding="utf-8")
    if a.spec_in and a.spec_out:
        spec = a.spec_in.read_text(encoding="utf-8")
        for old, new in mapping.items():
            spec = spec.replace(old, new).replace(old.lower(), new)
        a.spec_out.write_text(spec, encoding="utf-8")
    print(f"THEME_APPLIED name={theme['name']} files={len(list(a.output_svg.glob('*.svg')))}")

if __name__ == "__main__":
    main()
