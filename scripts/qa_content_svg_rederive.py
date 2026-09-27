#!/usr/bin/env python3
"""Read-only re-derivation check for canonical SVG artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERIFY = REPO / "scripts" / "verify_content_build.py"
MATERIALIZE = REPO / "scripts" / "materialize_content_project.py"


def run(argv: list[str]) -> None:
    subprocess.run(argv, cwd=REPO, check=True)


def git_output(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True).stdout.strip()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rederive(bundle: Path) -> None:
    bundle = bundle.resolve()
    if not bundle.is_dir(): raise ValueError(f"missing bundle: {bundle}")
    run([sys.executable, str(VERIFY), str(bundle)])
    receipt = json.loads((bundle / "build_receipt.json").read_text(encoding="utf-8"))
    if git_output("rev-parse", "HEAD") != receipt.get("toolchain", {}).get("ppt_studio_head"):
        raise ValueError("bundle builder HEAD does not match current ppt-studio HEAD")
    try:
        subprocess.run(["git", "-C", str(REPO), "diff", "--quiet"], check=True)
        subprocess.run(["git", "-C", str(REPO), "diff", "--cached", "--quiet"], check=True)
    except subprocess.CalledProcessError as exc:
        raise ValueError("ppt-studio tracked worktree is dirty") from exc
    required=("slide_plan.json","layout_intent.json","spec_lock.md")
    for name in required:
        if not (bundle/name).is_file(): raise ValueError(f"bundle file is missing: {name}")
    expected=receipt.get("artifacts",{}).get("svg")
    if not isinstance(expected,dict): raise ValueError("receipt artifacts.svg must be an object")
    with tempfile.TemporaryDirectory(prefix="content-svg-rederive-") as tmp:
        root=Path(tmp); plan=root/"slide_plan.json"; intent=root/"layout_intent.json"; spec=root/"spec_lock.md"; out=root/"svg_output"; out.mkdir()
        for src,dst in ((bundle/"slide_plan.json",plan),(bundle/"layout_intent.json",intent),(bundle/"spec_lock.md",spec)): shutil.copyfile(src,dst)
        run([sys.executable,str(MATERIALIZE),str(plan),str(intent),"--spec",str(spec),"-o",str(out)])
        actual={p.name:sha(p) for p in sorted(out.glob("*.svg"))}
        if set(actual)!=set(expected): raise ValueError("rederived SVG roster mismatch")
        for name in sorted(expected):
            if actual[name]!=expected[name]: raise ValueError(f"rederived SVG mismatch: {name}")
    print(f"CONTENT_SVG_REDERIVED slides={receipt['slides']} svg=PASS")


def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("bundle_root",type=Path); a=p.parse_args(argv)
    try: rederive(a.bundle_root)
    except (OSError,ValueError,json.JSONDecodeError,subprocess.CalledProcessError) as exc: print(f"ERROR: {exc}",file=sys.stderr); return 2
    return 0


if __name__=="__main__": raise SystemExit(main())
