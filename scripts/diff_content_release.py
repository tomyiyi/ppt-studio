#!/usr/bin/env python3
"""Create a deterministic diff between two independently verified releases."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERIFY = REPO / "scripts" / "verify_content_release.py"
SCHEMA = "ppt-studio-content-release-diff/v1"
INPUT_KEYS = ("markdown_sha256", "spec_sha256", "slide_plan_sha256", "layout_intent_sha256")
TOOLCHAIN_KEYS = ("ppt_studio_head", "ppt_master_head")
ARTIFACT_SCALARS = ("html_sha256", "svg_quality_report_sha256", "pptx_sha256")


def verify_release(bundle: Path, report: Path) -> None:
    subprocess.run([sys.executable, str(VERIFY), str(bundle), str(report)], cwd=REPO, check=True)


def change(before: object, after: object) -> dict:
    return {"changed": before != after, "before": before, "after": after}


def svg_changes(before: dict, after: dict) -> dict:
    return {
        "added": sorted(set(after) - set(before)),
        "removed": sorted(set(before) - set(after)),
        "modified": sorted(name for name in set(before) & set(after) if before[name] != after[name]),
    }


def build_diff(receipt_a: dict, receipt_b: dict) -> dict:
    inputs_a, inputs_b = receipt_a["inputs"], receipt_b["inputs"]
    tool_a, tool_b = receipt_a["toolchain"], receipt_b["toolchain"]
    art_a, art_b = receipt_a["artifacts"], receipt_b["artifacts"]
    svg_a, svg_b = art_a.get("svg", {}), art_b.get("svg", {})
    artifacts = {key: change(art_a.get(key), art_b.get(key)) for key in ARTIFACT_SCALARS}
    svg_delta = svg_changes(svg_a, svg_b)
    artifacts["svg"] = {"changed": bool(any(svg_delta.values())), **svg_delta}
    identity_values = [receipt_a.get("slides") == receipt_b.get("slides")]
    identity_values += [inputs_a.get(k) == inputs_b.get(k) for k in INPUT_KEYS]
    identity_values += [tool_a.get(k) == tool_b.get(k) for k in TOOLCHAIN_KEYS]
    identity_values += [art_a.get(k) == art_b.get(k) for k in ARTIFACT_SCALARS]
    identity_values.append(svg_a == svg_b)
    payload = {
        "schema": SCHEMA,
        "same_release_identity": all(identity_values),
        "changes": {
            "slides": change(receipt_a.get("slides"), receipt_b.get("slides")),
            "inputs": {key: change(inputs_a.get(key), inputs_b.get(key)) for key in INPUT_KEYS},
            "toolchain": {key: change(tool_a.get(key), tool_b.get(key)) for key in TOOLCHAIN_KEYS},
            "artifacts": artifacts,
        },
    }
    leaves = [payload["changes"]["slides"]["changed"]]
    leaves += [payload["changes"]["inputs"][key]["changed"] for key in INPUT_KEYS]
    leaves += [payload["changes"]["toolchain"][key]["changed"] for key in TOOLCHAIN_KEYS]
    leaves += [payload["changes"]["artifacts"][key]["changed"] for key in ARTIFACT_SCALARS]
    leaves += [len(payload["changes"]["artifacts"]["svg"][key]) > 0 for key in ("added", "removed", "modified")]
    payload["changes_count"] = sum(leaves)
    return payload


def run(bundle_a: Path, report_a: Path, bundle_b: Path, report_b: Path, output: Path) -> None:
    if output.exists():
        raise ValueError(f"output must be absent: {output}")
    for bundle, report in ((bundle_a, report_a), (bundle_b, report_b)):
        verify_release(bundle.resolve(), report.resolve())
    receipt_a = json.loads((bundle_a / "build_receipt.json").read_text(encoding="utf-8"))
    receipt_b = json.loads((bundle_b / "build_receipt.json").read_text(encoding="utf-8"))
    payload = build_diff(receipt_a, receipt_b)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    print(f"CONTENT_RELEASE_DIFF changes={payload['changes_count']}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_a", type=Path)
    parser.add_argument("report_a", type=Path)
    parser.add_argument("bundle_b", type=Path)
    parser.add_argument("report_b", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        run(args.bundle_a, args.report_a, args.bundle_b, args.report_b, args.output)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
