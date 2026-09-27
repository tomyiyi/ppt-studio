#!/usr/bin/env python3
"""Verify a deterministic release report against a currently Deep-QA-passed bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEEP_QA = REPO / "scripts" / "qa_content_bundle.py"
SCHEMA = "ppt-studio-content-release-report/v1"
REPORT_KEYS = {"schema", "slides", "build_receipt_sha256", "inputs", "toolchain", "qa"}
QA_PASS = {"bundle_integrity": "PASS", "html_preview": "PASS", "native_pptx": "PASS"}


def run_deep_qa(bundle: Path) -> None:
    subprocess.run([sys.executable, str(DEEP_QA), str(bundle)], cwd=REPO, check=True)


def verify(bundle: Path, report_path: Path) -> None:
    bundle = bundle.resolve()
    report_path = report_path.resolve()
    if not bundle.is_dir():
        raise ValueError(f"missing bundle: {bundle}")
    if not report_path.is_file():
        raise ValueError(f"missing release report: {report_path}")
    run_deep_qa(bundle)
    receipt_bytes = (bundle / "build_receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes.decode("utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if set(report) != REPORT_KEYS or report.get("schema") != SCHEMA:
        raise ValueError("release report schema mismatch")
    if report.get("slides") != receipt.get("slides"):
        raise ValueError("release report mismatch: slides")
    expected_receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    if report.get("build_receipt_sha256") != expected_receipt_sha:
        raise ValueError("release report mismatch: build_receipt_sha256")
    report_inputs = report.get("inputs")
    receipt_inputs = receipt.get("inputs")
    if not isinstance(report_inputs, dict) or not isinstance(receipt_inputs, dict):
        raise ValueError("release report mismatch: inputs")
    if set(report_inputs) != set(receipt_inputs):
        raise ValueError("release report mismatch: inputs")
    for key in sorted(receipt_inputs):
        if report_inputs.get(key) != receipt_inputs.get(key):
            raise ValueError(f"release report mismatch: inputs.{key}")
    receipt_toolchain = receipt.get("toolchain")
    report_toolchain = report.get("toolchain")
    if not isinstance(receipt_toolchain, dict) or not isinstance(report_toolchain, dict):
        raise ValueError("release report mismatch: toolchain")
    for key in ("ppt_studio_head", "ppt_master_head"):
        value = receipt_toolchain.get(key)
        if not isinstance(value, str) or len(value) != 40:
            raise ValueError(f"invalid receipt toolchain: {key}")
        try:
            int(value, 16)
        except ValueError as exc:
            raise ValueError(f"invalid receipt toolchain: {key}") from exc
    if set(report_toolchain) != {"ppt_studio_head", "ppt_master_head"} or report_toolchain != {
        key: receipt_toolchain[key] for key in ("ppt_studio_head", "ppt_master_head")
    }:
        raise ValueError("release report mismatch: toolchain")
    if report.get("qa") != QA_PASS:
        raise ValueError("release report mismatch: qa")
    print(f"CONTENT_RELEASE_VERIFIED slides={receipt['slides']}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_root", type=Path)
    parser.add_argument("release_report", type=Path)
    args = parser.parse_args(argv)
    try:
        verify(args.bundle_root, args.release_report)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
