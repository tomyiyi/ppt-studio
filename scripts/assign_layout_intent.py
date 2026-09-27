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
    has_risk = False
    has_decision = False
    has_faq = False
    has_image = False
    has_code = False
    code_count = 0
    has_metrics = False
    has_milestones = False
    has_funnel = False
    has_layers = False
    has_bars = False
    has_tasks = False
    has_hierarchy = False
    has_swimlane = False
    has_trend = False
    has_composition = False
    has_waterfall = False
    has_grouped_bar = False
    has_cycle = False
    has_scatter = False
    has_gantt = False
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
        if block.get("type") == "risk-register":
            has_risk = True
            continue
        if block.get("type") == "decision-matrix":
            has_decision = True
            continue
        if block.get("type") == "faq":
            has_faq = True
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
        if block.get("type") == "funnel-stages":
            has_funnel = True
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
        if block.get("type") == "hierarchy-tree":
            has_hierarchy = True
            continue
        if block.get("type") == "swimlane-handoff":
            has_swimlane = True
            continue
        if block.get("type") == "trend-series":
            has_trend = True
            continue
        if block.get("type") == "composition-data":
            has_composition = True
            continue
        if block.get("type") == "waterfall-data":
            has_waterfall = True
            continue
        if block.get("type") == "grouped-bar-data":
            has_grouped_bar = True
            continue
        if block.get("type") == "cycle-stages":
            has_cycle = True
            continue
        if block.get("type") == "scatter-data":
            has_scatter = True
            continue
        if block.get("type") == "gantt-schedule":
            has_gantt = True
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
    if has_funnel:
        if paragraph_count > 1 or has_bullets or has_steps or has_quote or has_table or has_image or has_milestones:
            raise ValueError("mixed funnel-stages blocks are not supported in v1")
        return "funnel-stages"
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
    if has_hierarchy:
        if paragraph_count > 1 or len([b for b in blocks if b.get("type")=="hierarchy-tree"]) != 1 or any(b.get("type") not in {"hierarchy-tree","paragraph"} for b in blocks): raise ValueError("mixed hierarchy-tree blocks are not supported in v1")
        return "hierarchy-tree"
    if has_swimlane:
        if len([b for b in blocks if b.get("type")=="swimlane-handoff"]) != 1 or any(b.get("type") != "swimlane-handoff" for b in blocks): raise ValueError("mixed swimlane-handoff blocks are not supported in v1")
        return "swimlane-handoff"
    if has_trend:
        if len([b for b in blocks if b.get("type")=="trend-series"]) != 1 or any(b.get("type") not in {"trend-series","paragraph"} for b in blocks) or paragraph_count > 1: raise ValueError("mixed trend-line-chart blocks are not supported in v1")
        return "trend-line-chart"
    if has_composition:
        if len([b for b in blocks if b.get("type")=="composition-data"]) != 1 or any(b.get("type") != "composition-data" for b in blocks): raise ValueError("mixed composition-bar blocks are not supported in v1")
        return "composition-bar"
    if has_grouped_bar:
        if len([b for b in blocks if b.get("type")=="grouped-bar-data"]) != 1 or any(b.get("type") not in {"grouped-bar-data","paragraph"} for b in blocks) or paragraph_count > 1:
            raise ValueError("mixed grouped-bar-comparison blocks are not supported in v1")
        return "grouped-bar-comparison"
    if has_waterfall:
        if len([b for b in blocks if b.get("type")=="waterfall-data"]) != 1 or any(b.get("type") not in {"waterfall-data","paragraph"} for b in blocks) or paragraph_count > 1: raise ValueError("mixed waterfall-change blocks are not supported in v1")
        return "waterfall-change"
    if has_cycle:
        if len([b for b in blocks if b.get("type")=="cycle-stages"]) != 1 or any(b.get("type") not in {"cycle-stages","paragraph"} for b in blocks) or paragraph_count > 1: raise ValueError("mixed cycle-loop blocks are not supported in v1")
        return "cycle-loop"
    if has_scatter:
        if len([b for b in blocks if b.get("type")=="scatter-data"]) != 1 or any(b.get("type") not in {"scatter-data","paragraph"} for b in blocks) or paragraph_count > 1:
            raise ValueError("mixed scatter-plot blocks are not supported in v1")
        return "scatter-plot"
    if has_gantt:
        if len([b for b in blocks if b.get("type")=="gantt-schedule"]) != 1 or any(b.get("type") not in {"gantt-schedule","paragraph"} for b in blocks) or paragraph_count > 1:
            raise ValueError("mixed gantt-schedule blocks are not supported in v1")
        return "gantt-schedule"
    if has_risk:
        if paragraph_count or has_steps or has_quote or has_table or has_image or has_bullets:
            raise ValueError("mixed risk-register blocks are not supported in v1")
        return "risk-register"
    if has_decision:
        if paragraph_count or has_steps or has_quote or has_table or has_image or has_bullets or has_risk:
            raise ValueError("mixed decision-matrix blocks are not supported in v1")
        return "decision-matrix"
    if has_faq:
        if paragraph_count or has_steps or has_quote or has_table or has_image or has_bullets or has_risk or has_decision:
            raise ValueError("mixed faq and other block types are not supported in v1")
        return "faq"
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
