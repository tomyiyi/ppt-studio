#!/usr/bin/env python3
"""Assign a deterministic, content-free layout intent to a slide plan."""

import argparse
import hashlib
import json
from pathlib import Path


def assign_layout(slide: dict) -> str:
    if slide.get("kind") == "cover":
        return "cover"
    if slide.get("kind") != "content":
        raise ValueError("unsupported slide kind")
    blocks = slide.get("blocks")
    if not isinstance(blocks, list):
        raise ValueError("slide blocks must be a list")
    if not blocks:
        return "section-divider"
    has_bullets = False
    has_steps = False
    has_quote = False
    has_table = False
    has_image = False
    has_code = False
    code_count = 0
    has_metrics = False
    has_milestones = False
    has_layers = False
    has_bars = False
    has_tasks = False
    image_count = 0
    paragraph_count = 0
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError("slide block must be an object")
        if block.get("type") == "bullets":
            has_bullets = True
            continue
        if block.get("type") == "steps":
            has_steps = True
            continue
        if block.get("type") == "quote":
            has_quote = True
            continue
        if block.get("type") == "comparison-table":
            has_table = True
            continue
        if block.get("type") == "image":
            has_image = True
            image_count += 1
            continue
        if block.get("type") == "code":
            has_code = True
            code_count += 1
            continue
        if block.get("type") == "metric-list":
            has_metrics = True
            continue
        if block.get("type") == "milestone-list":
            has_milestones = True
            continue
        if block.get("type") == "layer-list":
            has_layers = True
            continue
        if block.get("type") == "bar-data":
            has_bars = True
            continue
        if block.get("type") == "task-list":
            has_tasks = True
            continue
        if block.get("type") != "paragraph":
            raise ValueError("unsupported block type")
        paragraph_count += 1
    if has_code:
        if code_count != 1 or paragraph_count > 1 or has_bullets or has_steps or has_quote or has_table or has_image:
            raise ValueError("mixed code blocks are not supported in v1")
        return "code-callout"
    if has_metrics:
        if paragraph_count > 1 or has_bullets or has_steps or has_quote or has_table or has_image:
            raise ValueError("mixed metric-list blocks are not supported in v1")
        return "metric-highlights"
    if has_milestones:
        if paragraph_count or has_bullets or has_steps or has_quote or has_table or has_image:
            raise ValueError("mixed milestone-list blocks are not supported in v1")
        return "milestone-timeline"
    if has_layers:
        if paragraph_count > 1 or has_bullets or has_steps or has_quote or has_table or has_image:
            raise ValueError("mixed structured blocks are not supported in v1")
        return "architecture-stack"
    if has_bars:
        if paragraph_count > 1 or has_bullets or has_steps or has_quote or has_table or has_image or has_metrics:
            raise ValueError("mixed bar-data blocks are not supported in v1")
        return "bar-chart"
    if has_tasks:
        if paragraph_count > 1 or has_bullets or has_steps or has_quote or has_table or has_image or has_metrics or has_layers:
            raise ValueError("mixed task-list blocks are not supported in v1")
        return "checklist-status"
    if has_image:
        if image_count not in {1, 2} or paragraph_count > 1 or has_bullets or has_steps or has_quote or has_table:
            raise ValueError("mixed image blocks are not supported in v1")
        paths = [block.get("path") for block in blocks if block.get("type") == "image"]
        if image_count == 2 and (not all(isinstance(path, str) and path for path in paths) or len(set(paths)) != 2):
            raise ValueError("image paths must be distinct in v1")
        return "image-comparison" if image_count == 2 else "image-callout"
    if has_bullets:
        if has_steps: raise ValueError("mixed bullets and ordered steps are not supported in v1")
        if has_quote: raise ValueError("mixed quote and bullets are not supported in v1")
        if has_table: raise ValueError("mixed comparison table blocks are not supported in v1")
        return "statement-list"
    if has_table:
        if paragraph_count or has_steps or has_quote: raise ValueError("mixed comparison table blocks are not supported in v1")
        return "comparison-table"
    if has_steps:
        if has_quote: raise ValueError("mixed quote and ordered steps are not supported in v1")
        return "process-steps"
    if has_quote:
        if paragraph_count: raise ValueError("mixed paragraph and quote are not supported in v1")
        return "quote-callout"
    if paragraph_count == 3:
        return "three-card"
    if paragraph_count > 3:
        raise ValueError("content slide supports at most 3 paragraph blocks in v1")
    if paragraph_count == 2:
        return "statement-split"
    return "statement"


def build_intent(plan: dict, source_bytes: bytes) -> dict:
    if plan.get("schema") != "ppt-studio-slide-plan/v1":
        raise ValueError("unsupported slide plan schema")
    slides = plan.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValueError("slide plan must contain a non-empty slides list")
    output = []
    expected_ids = [f"{index:02d}" for index in range(1, len(slides) + 1)]
    actual_ids = [slide.get("id") if isinstance(slide, dict) else None for slide in slides]
    if actual_ids != expected_ids:
        raise ValueError("slide ids must be unique and contiguous 01..NN")
    for slide in slides:
        if not isinstance(slide, dict) or not isinstance(slide.get("id"), str):
            raise ValueError("slide must contain a string id")
        output.append({"id": slide["id"], "layout": assign_layout(slide)})
    return {
        "schema": "ppt-studio-layout-intent/v1",
        "source_plan_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "slides": output,
    }


def write_intent(intent: dict, output: Path) -> None:
    output.write_text(json.dumps(intent, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Assign deterministic layout intent to a slide plan")
    parser.add_argument("source", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        source_bytes = args.source.read_bytes()
        plan = json.loads(source_bytes.decode("utf-8"))
        write_intent(build_intent(plan, source_bytes), args.output)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
