#!/usr/bin/env python3
"""Read-only re-derivation check for the canonical content IR."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERIFY = REPO / "scripts" / "verify_content_build.py"
PLANNER = REPO / "scripts" / "plan_markdown.py"
ASSIGNER = REPO / "scripts" / "assign_layout_intent.py"


def run(argv: list[str]) -> None:
    subprocess.run(argv, cwd=REPO, check=True)


def git_output(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True).stdout.strip()


def rederive(bundle: Path) -> None:
    bundle = bundle.resolve()
    if not bundle.is_dir():
        raise ValueError(f"missing bundle: {bundle}")
    run([sys.executable, str(VERIFY), str(bundle)])
    receipt = json.loads((bundle / "build_receipt.json").read_text(encoding="utf-8"))
    expected = receipt.get("toolchain", {}).get("ppt_studio_head")
    if git_output("rev-parse", "HEAD") != expected:
        raise ValueError("bundle builder HEAD does not match current ppt-studio HEAD")
    try:
        subprocess.run(["git", "-C", str(REPO), "diff", "--quiet"], check=True)
        subprocess.run(["git", "-C", str(REPO), "diff", "--cached", "--quiet"], check=True)
    except subprocess.CalledProcessError as exc:
        raise ValueError("ppt-studio tracked worktree is dirty") from exc
    for name in ("source.md", "slide_plan.json", "layout_intent.json"):
        if not (bundle / name).is_file():
            raise ValueError(f"bundle file is missing: {name}")
    with tempfile.TemporaryDirectory(prefix="content-ir-rederive-") as tmp:
        root = Path(tmp)
        shutil.copyfile(bundle / "source.md", root / "source.md")
        run([sys.executable, str(PLANNER), str(root / "source.md"), "-o", str(root / "slide_plan.json")])
        if (root / "slide_plan.json").read_bytes() != (bundle / "slide_plan.json").read_bytes():
            raise ValueError("slide_plan.json re-derivation mismatch")
        run([sys.executable, str(ASSIGNER), str(root / "slide_plan.json"), "-o", str(root / "layout_intent.json")])
        if (root / "layout_intent.json").read_bytes() != (bundle / "layout_intent.json").read_bytes():
            raise ValueError("layout_intent.json re-derivation mismatch")
    print(f"CONTENT_IR_REDERIVED slides={receipt['slides']} plan=PASS intent=PASS")


def main(argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument("bundle_root", type=Path); args = parser.parse_args(argv)
    try: rederive(args.bundle_root)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 2
    return 0


if __name__ == "__main__": raise SystemExit(main())
