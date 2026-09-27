#!/usr/bin/env python3
"""Materialize the v1 cover slide from a slide plan and layout intent."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    try:
        value = json.loads(data)
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON: {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"invalid JSON object: {path}")
    return value, data


def load_spec(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    required = ["background", "primary_text", "secondary_text", "accent"]
    colors: dict[str, str] = {}
    for name in required:
        match = re.search(rf"^\s*-\s*{re.escape(name)}:\s*(#[0-9A-Fa-f]{{6}})\s*$", text, re.MULTILINE)
        if not match:
            fail(f"spec_lock missing colors.{name}")
        colors[name] = match.group(1)
    sizes: dict[str, int] = {}
    for name in ("cover", "subtitle", "body", "caption"):
        match = re.search(rf"^\s*-\s*{re.escape(name)}:\s*(\d+)\s*$", text, re.MULTILINE)
        if not match:
            fail(f"spec_lock missing typography.{name}")
        sizes[name] = int(match.group(1))
    family = re.search(r"^\s*-\s*font_family:\s*(.+?)\s*$", text, re.MULTILINE)
    if not family:
        fail("spec_lock missing typography.font_family")
    return {"colors": colors, "sizes": sizes, "font_family": family.group(1).strip()}


def validate_inputs(plan: dict, plan_bytes: bytes, intent: dict) -> dict:
    if plan.get("schema") != "ppt-studio-slide-plan/v1":
        fail("unsupported slide plan schema")
    if intent.get("schema") != "ppt-studio-layout-intent/v1":
        fail("unsupported layout intent schema")
    if intent.get("source_plan_sha256") != hashlib.sha256(plan_bytes).hexdigest():
        fail("source_plan_sha256 mismatch")
    slides = plan.get("slides")
    intents = intent.get("slides")
    if not isinstance(slides, list) or not isinstance(intents, list) or not slides:
        fail("plan and intent slides must be non-empty lists")
    if [item.get("id") for item in slides] != [item.get("id") for item in intents]:
        fail("plan and intent slide IDs mismatch")
    cover = slides[0]
    cover_intent = intents[0]
    if cover.get("id") != "01" or cover.get("kind") != "cover" or cover_intent.get("layout") != "cover":
        fail("slide 01 must be a cover with cover layout")
    blocks = cover.get("blocks", [])
    if not isinstance(blocks, list) or len(blocks) > 2:
        fail("cover supports 0-2 paragraph blocks")
    paragraphs: list[str] = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "paragraph" or not isinstance(block.get("text"), str):
            fail("cover layout does not support bullets in v1")
        paragraphs.append(block["text"])
    return {"title": cover.get("title"), "paragraphs": paragraphs}


def render_cover(plan: dict, spec: dict) -> str:
    title = plan.get("title")
    if not isinstance(title, str) or not title.strip():
        fail("cover title must be non-empty")
    paragraphs = plan["paragraphs"]
    c, s = spec["colors"], spec["sizes"]
    font = escape(spec["font_family"], {'"': '&quot;'})
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',
        f'  <g id="background"><rect x="0" y="0" width="1280" height="720" fill="{c["background"]}"/></g>',
        f'  <rect x="0" y="0" width="1280" height="5" fill="{c["accent"]}"/>',
        f'  <g id="cover-title"><text x="80" y="290" fill="{c["primary_text"]}" font-family="{font}" font-size="{s["cover"]}">{escape(title)}</text></g>',
    ]
    if paragraphs:
        lines.append(f'  <g id="cover-claim"><text x="80" y="475" fill="{c["secondary_text"]}" font-family="{font}" font-size="{s["subtitle"]}">{escape(paragraphs[0])}</text></g>')
    if len(paragraphs) == 2:
        lines.append(f'  <text x="80" y="450" fill="{c["secondary_text"]}" font-family="{font}" font-size="{s["body"]}">{escape(paragraphs[1])}</text>')
    lines.extend([
        f'  <g id="cover-footer"><line x1="80" y1="608" x2="1200" y2="608" stroke="{c["accent"]}"/><text x="1200" y="648" text-anchor="end" fill="{c["secondary_text"]}" font-family="{font}" font-size="{s["caption"]}">01</text></g>',
        '</svg>',
    ])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("intent", type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args(argv)
    plan, plan_bytes = load_json(args.plan)
    intent, _ = load_json(args.intent)
    content = validate_inputs(plan, plan_bytes, intent)
    content["paragraphs"] = content.pop("paragraphs")
    svg = render_cover(content, load_spec(args.spec))
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / "01_cover.svg"
    target.write_text(svg, encoding="utf-8")
    print("COVER_SVG_WRITTEN slide=01 layout=cover")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
