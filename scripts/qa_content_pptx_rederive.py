#!/usr/bin/env python3
"""Re-derive native PPTX and compare slide XML payloads only."""
from __future__ import annotations
import argparse, json, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
VERIFY=REPO/"scripts/verify_content_build.py"; QA=REPO/"scripts/qa_pptx.py"

def run(argv): subprocess.run(argv,cwd=REPO,check=True)
def git(*args): return subprocess.run(["git","-C",str(REPO),*args],check=True,capture_output=True,text=True).stdout.strip()
def slides(path):
    with zipfile.ZipFile(path) as z:
        names=sorted(n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
        return {n:z.read(n) for n in names}

def rederive(bundle:Path, config:Path):
    bundle=bundle.resolve(); config=config.resolve()
    if not bundle.is_dir() or not config.is_file(): raise ValueError("bundle or toolchain config is missing")
    run([sys.executable,str(VERIFY),str(bundle)])
    receipt=json.loads((bundle/"build_receipt.json").read_text()); cfg=json.loads(config.read_text())
    expected_studio=receipt.get("toolchain",{}).get("ppt_studio_head"); expected_master=receipt.get("toolchain",{}).get("ppt_master_head")
    if git("rev-parse","HEAD")!=expected_studio: raise ValueError("bundle builder HEAD does not match current ppt-studio HEAD")
    try:
        subprocess.run(["git","-C",str(REPO),"diff","--quiet"],check=True); subprocess.run(["git","-C",str(REPO),"diff","--cached","--quiet"],check=True)
    except subprocess.CalledProcessError as exc: raise ValueError("ppt-studio tracked worktree is dirty") from exc
    if cfg.get("schema")!="ppt-studio-toolchain/v1" or cfg.get("ppt_master_expected_head")!=expected_master: raise ValueError("ppt-master HEAD mismatch")
    master=Path(cfg["ppt_master_root"]); py=cfg["ppt_master_python"]
    if git_master:=subprocess.run(["git","-C",str(master),"rev-parse","HEAD"],check=True,capture_output=True,text=True).stdout.strip():
        if git_master!=expected_master: raise ValueError("ppt-master HEAD mismatch")
    with tempfile.TemporaryDirectory(prefix="content-pptx-rederive-") as tmp:
        root=Path(tmp); svg=root/"svg_output"; out=root/"output"; svg.mkdir(); out.mkdir(); (root/"validation").mkdir(); spec=root/"spec_lock.md"
        shutil.copyfile(bundle/"spec_lock.md",spec)
        shutil.copyfile(bundle/"validation/svg_quality_report.json",root/"validation/svg_quality_report.json")
        names=receipt.get("artifacts",{}).get("svg",{})
        for name in names: shutil.copyfile(bundle/"svg_output"/name,svg/name)
        pptx=out/"content-deck.pptx"; converter=master/"skills/ppt-master/scripts/svg_to_pptx.py"
        run([py,str(converter),str(root),"-o",str(pptx)])
        run([sys.executable,str(QA),str(pptx),"--spec",str(bundle/"spec_lock.md"),"--expected-slides",str(receipt["slides"]),"--expected-media","0"])
        a,b=slides(bundle/"output/content-deck.pptx"),slides(pptx)
        if list(a)!=list(b): raise ValueError("rederived PPTX slide XML roster mismatch")
        for name in a:
            if a[name]!=b[name]: raise ValueError(f"rederived PPTX slide XML mismatch: {name}")
    print(f"CONTENT_PPTX_REDERIVED slides={receipt['slides']} native_slides=PASS")

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("bundle_root",type=Path); p.add_argument("--toolchain-config",required=True,type=Path); a=p.parse_args(argv)
    try: rederive(a.bundle_root,a.toolchain_config)
    except (OSError,ValueError,json.JSONDecodeError,subprocess.CalledProcessError,zipfile.BadZipFile) as exc: print(f"ERROR: {exc}",file=sys.stderr); return 2
    return 0
if __name__=="__main__": raise SystemExit(main())
