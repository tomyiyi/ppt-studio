#!/usr/bin/env python3
"""Create a deterministic acceptance report for a Deep-QA-passed bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEEP_QA = REPO / "scripts" / "qa_content_bundle.py"
SCHEMA = "ppt-studio-content-release-report/v1"


def run_deep_qa(bundle: Path) -> None:
    subprocess.run([sys.executable, str(DEEP_QA), str(bundle)], cwd=REPO, check=True)


def valid_head(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 40:
        raise ValueError(f"invalid {label}")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"invalid {label}") from exc
    return value


def build_report(bundle: Path) -> dict:
    receipt_bytes = (bundle / "build_receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes.decode("utf-8"))
    slides = receipt.get("slides")
    if not isinstance(slides, int) or slides < 1:
        raise ValueError("invalid receipt slides")
    inputs = receipt.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("missing receipt inputs")
    required_inputs = ("markdown_sha256", "spec_sha256", "slide_plan_sha256", "layout_intent_sha256")
    for key in required_inputs:
        value = inputs.get(key)
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"invalid input hash: {key}")
        try:
            int(value, 16)
        except ValueError as exc:
            raise ValueError(f"invalid input hash: {key}") from exc
    toolchain = receipt.get("toolchain")
    if not isinstance(toolchain, dict):
        raise ValueError("missing receipt toolchain")
    report = {
        "schema": SCHEMA,
        "slides": slides,
        "build_receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "inputs": {key: inputs[key] for key in required_inputs},
        "toolchain": {
            "ppt_studio_head": valid_head(toolchain.get("ppt_studio_head"), "ppt-studio HEAD"),
            "ppt_master_head": valid_head(toolchain.get("ppt_master_head"), "ppt-master HEAD"),
        },
        "qa": {
            "bundle_integrity": "PASS",
            "html_preview": "PASS",
            "native_pptx": "PASS",
        },
    }
    return report


def report(bundle: Path, output: Path) -> None:
    bundle = bundle.resolve()
    output = output.resolve()
    if not bundle.is_dir():
        raise ValueError(f"missing bundle: {bundle}")
    if output.exists():
        raise ValueError(f"output must be absent: {output}")
    run_deep_qa(bundle)
    payload = build_report(bundle)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    print(f"CONTENT_RELEASE_REPORTED slides={payload['slides']}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_root", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report(args.bundle_root, args.output)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
