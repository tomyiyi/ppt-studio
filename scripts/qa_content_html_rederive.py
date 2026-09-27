#!/usr/bin/env python3
"""Read-only re-derivation check for the canonical HTML preview."""
from __future__ import annotations
import argparse, json, shutil, subprocess, sys, tempfile
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
VERIFY=REPO/"scripts/verify_content_build.py"
PREVIEW=REPO/"scripts/build_preview.py"

def run(argv): subprocess.run(argv,cwd=REPO,check=True)
def git_output(*args): return subprocess.run(["git","-C",str(REPO),*args],check=True,capture_output=True,text=True).stdout.strip()

def rederive(bundle: Path):
    bundle=bundle.resolve()
    if not bundle.is_dir(): raise ValueError(f"missing bundle: {bundle}")
    run([sys.executable,str(VERIFY),str(bundle)])
    receipt=json.loads((bundle/"build_receipt.json").read_text(encoding="utf-8"))
    if git_output("rev-parse","HEAD") != receipt.get("toolchain",{}).get("ppt_studio_head"):
        raise ValueError("bundle builder HEAD does not match current ppt-studio HEAD")
    try:
        subprocess.run(["git","-C",str(REPO),"diff","--quiet"],check=True)
        subprocess.run(["git","-C",str(REPO),"diff","--cached","--quiet"],check=True)
    except subprocess.CalledProcessError as exc: raise ValueError("ppt-studio tracked worktree is dirty") from exc
    svg= bundle/"svg_output"; bundled=bundle/"preview/content-deck.html"
    if not svg.is_dir() or not bundled.is_file(): raise ValueError("bundle preview inputs are missing")
    with tempfile.TemporaryDirectory(prefix="content-html-rederive-") as tmp:
        root=Path(tmp); svg_copy=root/"svg_output"; preview=root/"preview/content-deck.html"; svg_copy.mkdir(); preview.parent.mkdir()
        receipt_svg=receipt.get("artifacts",{}).get("svg",{})
        for name in sorted(receipt_svg): shutil.copyfile(svg/name,svg_copy/name)
        run([sys.executable,str(PREVIEW),str(svg_copy),str(preview),"source","--check"])
        if preview.read_bytes()!=bundled.read_bytes(): raise ValueError("rederived HTML mismatch: preview/content-deck.html")
    print(f"CONTENT_HTML_REDERIVED slides={receipt['slides']} html=PASS")

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("bundle_root",type=Path); a=p.parse_args(argv)
    try: rederive(a.bundle_root)
    except (OSError,ValueError,json.JSONDecodeError,subprocess.CalledProcessError) as exc: print(f"ERROR: {exc}",file=sys.stderr); return 2
    return 0
if __name__=="__main__": raise SystemExit(main())
