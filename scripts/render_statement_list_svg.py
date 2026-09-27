#!/usr/bin/env python3
"""Materialize deterministic v1 statement-list slides."""
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
    colors: dict[str, str] = {}
    for name in ("background", "primary_text", "secondary_text", "tertiary_text", "accent"):
        match = re.search(rf"^\s*-\s*{re.escape(name)}:\s*(#[0-9A-Fa-f]{{6}})(?:\s+#.*)?$", text, re.MULTILINE)
        if not match:
            fail(f"spec_lock missing colors.{name}")
        colors[name] = match.group(1)
    sizes: dict[str, int] = {}
    for name in ("kicker", "statement", "body", "caption"):
        match = re.search(rf"^\s*-\s*{re.escape(name)}:\s*(\d+)\s*$", text, re.MULTILINE)
        if not match:
            fail(f"spec_lock missing typography.{name}")
        sizes[name] = int(match.group(1))
    family = re.search(r"^\s*-\s*font_family:\s*(.+?)\s*$", text, re.MULTILINE)
    if not family:
        fail("spec_lock missing typography.font_family")
    return {"colors": colors, "sizes": sizes, "font_family": family.group(1).strip()}


def validate(plan: dict, plan_bytes: bytes, intent: dict) -> list[dict]:
    if plan.get("schema") != "ppt-studio-slide-plan/v1":
        fail("unsupported slide plan schema")
    if intent.get("schema") != "ppt-studio-layout-intent/v1":
        fail("unsupported layout intent schema")
    if intent.get("source_plan_sha256") != hashlib.sha256(plan_bytes).hexdigest():
        fail("source_plan_sha256 mismatch")
    slides, intents = plan.get("slides"), intent.get("slides")
    if not isinstance(slides, list) or not isinstance(intents, list) or len(slides) != len(intents) or not slides:
        fail("plan and intent slides must be non-empty lists of equal length")
    if [s.get("id") for s in slides] != [i.get("id") for i in intents]:
        fail("plan and intent slide IDs mismatch")
    selected: list[dict] = []
    for slide, intent_slide in zip(slides, intents):
        if intent_slide.get("layout") != "statement-list":
            continue
        if slide.get("kind") != "content":
            fail("statement-list layout requires content slide")
        blocks = slide.get("blocks", [])
        if not isinstance(blocks, list):
            fail("statement-list blocks must be a list")
        paragraphs = [b for b in blocks if isinstance(b, dict) and b.get("type") == "paragraph"]
        bullets = [b for b in blocks if isinstance(b, dict) and b.get("type") == "bullets"]
        if len(paragraphs) > 1 or len(bullets) != 1 or len(bullets) != sum(isinstance(b, dict) and b.get("type") == "bullets" for b in blocks):
            fail("statement-list requires optional 0-1 paragraph and exactly 1 bullets block")
        if any(not isinstance(b.get("text"), str) for b in paragraphs):
            fail("statement-list paragraph must be text")
        items = bullets[0].get("items")
        if not isinstance(items, list) or not 2 <= len(items) <= 4 or any(not isinstance(item, str) for item in items):
            fail("statement-list requires 2-4 bullet items")
        title = slide.get("title")
        if not isinstance(title, str) or not title.strip():
            fail("statement-list title must be non-empty")
        if len(title) > 28:
            fail("statement-list title exceeds v1 single-line budget")
        if paragraphs and len(paragraphs[0]["text"]) > 52:
            fail("statement-list paragraph exceeds v1 budget")
        if any(len(item) > 24 for item in items):
            fail("statement-list bullet exceeds v1 single-line budget")
        selected.append({"id": slide["id"], "title": title, "paragraph": paragraphs[0]["text"] if paragraphs else None, "items": items})
    if not selected:
        fail("no statement-list slides found")
    return selected


def render_slide(slide: dict, total: int, spec: dict) -> str:
    c, s = spec["colors"], spec["sizes"]
    font = escape(spec["font_family"], {'"': '&quot;'})
    page = f'{slide["id"]} / {total:02d}'
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',
        f'  <g id="background"><rect x="0" y="0" width="1280" height="720" fill="{c["background"]}"/></g>',
        f'  <g id="page-kicker"><text x="80" y="100" fill="{c["accent"]}" font-family="{font}" font-size="{s["kicker"]}">智流 OS</text></g>',
        f'  <g id="statement"><text x="80" y="210" fill="{c["primary_text"]}" font-family="{font}" font-size="{s["statement"]}">{escape(slide["title"])}</text></g>',
        '  <g id="statement-body">',
    ]
    if slide["paragraph"] is not None:
        lines.append(f'    <text x="80" y="315" fill="{c["secondary_text"]}" font-family="{font}" font-size="{s["body"]}">{escape(slide["paragraph"])}</text>')
    lines.append('  </g>')
    lines.append('  <g id="bullet-list">')
    first_y = 390
    for index, item in enumerate(slide["items"]):
        y = first_y + index * 54
        lines.append(f'    <circle cx="88" cy="{y - 6}" r="4" fill="{c["accent"]}"/>')
        lines.append(f'    <text x="112" y="{y}" fill="{c["secondary_text"]}" font-family="{font}" font-size="{s["body"]}">{escape(item)}</text>')
    lines.extend([
        '  </g>',
        f'  <g id="footer"><line x1="80" y1="608" x2="1200" y2="608" stroke="{c["accent"]}"/><text x="1200" y="648" text-anchor="end" fill="{c["secondary_text"]}" font-family="{font}" font-size="{s["caption"]}">{page}</text></g>',
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
    selected = validate(plan, plan_bytes, intent)
    spec = load_spec(args.spec)
    args.output.mkdir(parents=True, exist_ok=True)
    for slide in selected:
        (args.output / f'{slide["id"]}_statement_list.svg').write_text(render_slide(slide, len(plan["slides"]), spec), encoding="utf-8")
    print(f"STATEMENT_LIST_SVG_WRITTEN slides={','.join(s['id'] for s in selected)} layout=statement-list")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
