#!/usr/bin/env python3
"""Run integrity, HTML QA, and PPTX QA over one published content bundle."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
VERIFY = SCRIPTS / "verify_content_build.py"


def run_verify(bundle: Path) -> None:
    subprocess.run([sys.executable, str(VERIFY), str(bundle)], cwd=REPO, check=True)


def deep_qa(bundle: Path, verbose: bool = True) -> bool:
    bundle = bundle.resolve()
    if not bundle.is_dir():
        raise ValueError(f"missing bundle: {bundle}")
    run_verify(bundle)
    receipt = json.loads((bundle / "build_receipt.json").read_text(encoding="utf-8"))
    slides = receipt.get("slides")
    if not isinstance(slides, int) or slides < 1:
        raise ValueError("invalid receipt slides")

    sys.path.insert(0, str(SCRIPTS))
    import qa_preview
    import qa_pptx
    plan = json.loads((bundle / "slide_plan.json").read_text(encoding="utf-8"))
    expected_media = sum(1 for slide in plan.get("slides", []) for block in slide.get("blocks", []) if block.get("type") == "image")

    html_ok = qa_preview.run_qa_single_preview(bundle / "preview" / "content-deck.html", verbose=verbose)
    if not html_ok:
        raise ValueError("deep QA failed")
    pptx_ok = qa_pptx.run_qa_pptx(
        bundle / "output" / "content-deck.pptx",
        spec_path=bundle / "spec_lock.md",
        expected_slides=slides,
        expected_media=expected_media,
        verbose=verbose,
    )
    if not html_ok or not pptx_ok:
        raise ValueError("deep QA failed")
    print(f"CONTENT_BUNDLE_QA_ALL_CLEAR slides={slides} preview=1 pptx=1")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_root", type=Path)
    args = parser.parse_args(argv)
    try:
        deep_qa(args.bundle_root)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
