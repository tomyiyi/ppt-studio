#!/usr/bin/env python3
"""Verify a published content build against its provenance receipt."""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path

SCHEMA = "ppt-studio-content-build-receipt/v1"

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def require_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"invalid SHA-256: {label}")
    try: int(value, 16)
    except ValueError as exc: raise ValueError(f"invalid SHA-256: {label}") from exc
    return value

def require_basename(value: object) -> str:
    if not isinstance(value, str) or not value or Path(value).name != value:
        raise ValueError("unsafe SVG filename")
    return value

def verify(root: Path, markdown: Path) -> int:
    receipt_path = root / "build_receipt.json"
    if not root.is_dir() or not receipt_path.is_file():
        raise ValueError("missing build root or build_receipt.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema") != SCHEMA:
        raise ValueError("unsupported receipt schema")
    slides = receipt.get("slides")
    if not isinstance(slides, int) or slides < 1:
        raise ValueError("invalid slides")
    inputs = receipt.get("inputs")
    artifacts = receipt.get("artifacts")
    if not isinstance(inputs, dict) or not isinstance(artifacts, dict):
        raise ValueError("receipt inputs/artifacts must be objects")
    bundled_source = root / "source.md"
    if bundled_source.is_file():
        if sha256(bundled_source) != require_hash(inputs.get("markdown_sha256"), "markdown"):
            raise ValueError("input mismatch: markdown_sha256")
        if markdown is not None and (not markdown.is_file() or sha256(markdown) != sha256(bundled_source)):
            raise ValueError("input mismatch: markdown_sha256")
    elif markdown is not None:
        if not markdown.is_file() or sha256(markdown) != require_hash(inputs.get("markdown_sha256"), "markdown"):
            raise ValueError("markdown SHA-256 mismatch")
    else:
        raise ValueError("missing bundled source.md; provide --markdown for legacy bundle")
    for key, rel in (("spec_sha256", "spec_lock.md"), ("slide_plan_sha256", "slide_plan.json"), ("layout_intent_sha256", "layout_intent.json")):
        path = root / rel
        if not path.is_file() or sha256(path) != require_hash(inputs.get(key), key):
            raise ValueError(f"{key} mismatch")
    toolchain = receipt.get("toolchain")
    if not isinstance(toolchain, dict) or not isinstance(toolchain.get("ppt_master_head"), str) or len(toolchain["ppt_master_head"]) != 40:
        raise ValueError("missing toolchain HEAD")
    try: int(toolchain["ppt_master_head"], 16)
    except ValueError as exc: raise ValueError("invalid toolchain HEAD") from exc
    plan = json.loads((root / "slide_plan.json").read_text(encoding="utf-8"))
    if not isinstance(plan.get("slides"), list) or len(plan["slides"]) != slides:
        raise ValueError("slide plan count mismatch")
    svg_map = artifacts.get("svg")
    if not isinstance(svg_map, dict) or len(svg_map) != slides:
        raise ValueError("SVG receipt does not match slide count")
    names = {require_basename(name) for name in svg_map}
    actual_names = {p.name for p in (root / "svg_output").glob("*.svg")}
    if names != actual_names:
        raise ValueError("SVG roster mismatch")
    for name in sorted(names):
        path = root / "svg_output" / name
        if not path.is_file() or sha256(path) != require_hash(svg_map[name], f"svg:{name}"):
            raise ValueError(f"SVG mismatch: {name}")
    for key, rel in (("html_sha256", "preview/content-deck.html"), ("svg_quality_report_sha256", "validation/svg_quality_report.json"), ("pptx_sha256", "output/content-deck.pptx")):
        path = root / rel
        if not path.is_file() or sha256(path) != require_hash(artifacts.get(key), key):
            raise ValueError(f"artifact mismatch: {key}")
    print(f"CONTENT_BUILD_VERIFIED slides={slides}")
    return 0

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--markdown", type=Path)
    args = p.parse_args(argv)
    try: return verify(args.root, args.markdown)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 2

if __name__ == "__main__": raise SystemExit(main())
