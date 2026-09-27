#!/usr/bin/env python3
"""Orchestrate the four verified content derivation gates."""
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
STAGES=(
    ("ir",REPO/"scripts/qa_content_ir_rederive.py",False),
    ("svg",REPO/"scripts/qa_content_svg_rederive.py",False),
    ("html",REPO/"scripts/qa_content_html_rederive.py",False),
    ("pptx",REPO/"scripts/qa_content_pptx_rederive.py",True),
)
def run(argv): return subprocess.run(argv,cwd=REPO,check=True)
def qa(bundle:Path,config:Path):
    receipt=json.loads((bundle/"build_receipt.json").read_text(encoding="utf-8"))
    for name,script,needs_config in STAGES:
        argv=[sys.executable,str(script),str(bundle)]
        if needs_config: argv += ["--toolchain-config",str(config)]
        try: run(argv)
        except subprocess.CalledProcessError as exc: raise ValueError(f"content derivation QA failed: {name}") from exc
    print(f"CONTENT_DERIVATION_QA_ALL_CLEAR slides={receipt['slides']} ir=1 svg=1 html=1 pptx=1")
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("bundle_root",type=Path); p.add_argument("--toolchain-config",required=True,type=Path); a=p.parse_args(argv)
    try: qa(a.bundle_root.resolve(),a.toolchain_config.resolve())
    except (OSError,ValueError,json.JSONDecodeError,subprocess.CalledProcessError) as exc: print(f"ERROR: {exc}",file=sys.stderr); return 2
    return 0
if __name__=="__main__": raise SystemExit(main())
