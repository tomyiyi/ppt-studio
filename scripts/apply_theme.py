#!/usr/bin/env python3
import argparse, json, re, shutil
from pathlib import Path

HEX = re.compile(r"#[0-9A-Fa-f]{6}")

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("source_svg", type=Path)
    p.add_argument("output_svg", type=Path)
    p.add_argument("--theme", required=True, type=Path)
    p.add_argument("--spec-in", type=Path)
    p.add_argument("--spec-out", type=Path)
    a = p.parse_args(argv)
    palette = json.loads(a.theme.read_text(encoding="utf-8"))["colors"]
    mapping = {k.upper(): v.upper() for k, v in palette.items()}
    a.output_svg.mkdir(parents=True, exist_ok=True)
    for src in sorted(a.source_svg.glob("*.svg")):
        text = src.read_text(encoding="utf-8")
        text = HEX.sub(lambda m: mapping.get(m.group(0).upper(), m.group(0)), text)
        (a.output_svg / src.name).write_text(text, encoding="utf-8")
    if a.spec_in and a.spec_out:
        spec = a.spec_in.read_text(encoding="utf-8")
        for old, new in mapping.items():
            spec = spec.replace(old, new).replace(old.lower(), new)
        a.spec_out.write_text(spec, encoding="utf-8")
    print(f"THEME_APPLIED name={json.loads(a.theme.read_text())['name']} files={len(list(a.output_svg.glob('*.svg')))}")

if __name__ == "__main__":
    main()
