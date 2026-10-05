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

def main(argv=None, base_dir: str | Path | None = None) -> int:
    p = argparse.ArgumentParser(description="根据 theme.json 主题色配置替换 SVG 及 spec 中的颜色值")
    p.add_argument("source_svg", type=Path)
    p.add_argument("output_svg", type=Path)
    p.add_argument("--theme", required=True, type=Path)
    p.add_argument("--spec-in", type=Path)
    p.add_argument("--spec-out", type=Path)
    a = p.parse_args(argv)

    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    source_svg = (base / a.source_svg).resolve() if not a.source_svg.is_absolute() else a.source_svg.resolve()
    output_svg = (base / a.output_svg).resolve() if not a.output_svg.is_absolute() else a.output_svg.resolve()
    theme_path = (base / a.theme).resolve() if not a.theme.is_absolute() else a.theme.resolve()

    theme = json.loads(theme_path.read_text(encoding="utf-8"))
    palette = theme["colors"]
    mapping = {k.upper(): v.upper() for k, v in palette.items()}
    role_mapping = {role: {k.upper(): v.upper() for k, v in colors.items()} for role, colors in theme.get("role_colors", {}).items()}
    output_svg.mkdir(parents=True, exist_ok=True)
    for src in sorted(source_svg.glob("*.svg")):
        text = src.read_text(encoding="utf-8")
        text = transform_svg(text, mapping, role_mapping)
        (output_svg / src.name).write_text(text, encoding="utf-8")
    if a.spec_in and a.spec_out:
        spec_in = (base / a.spec_in).resolve() if not a.spec_in.is_absolute() else a.spec_in.resolve()
        spec_out = (base / a.spec_out).resolve() if not a.spec_out.is_absolute() else a.spec_out.resolve()
        spec = spec_in.read_text(encoding="utf-8")
        for old, new in mapping.items():
            spec = spec.replace(old, new).replace(old.lower(), new)
        spec_out.write_text(spec, encoding="utf-8")
    print(f"THEME_APPLIED name={theme['name']} files={len(list(output_svg.glob('*.svg')))}")
    return 0

if __name__ == "__main__":
    main()
