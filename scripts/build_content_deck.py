#!/usr/bin/env python3
"""Atomically build the validated V1 Markdown content deck."""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

def run(argv: list[str], cwd: Path = REPO) -> None:
    subprocess.run(argv, cwd=cwd, check=True)

def validate_tools(root: Path, py: Path) -> None:
    if not py.is_file() or not os.access(py, os.X_OK):
        raise ValueError(f"ppt-master Python is not executable: {py}")
    for name in ("svg_quality_checker.py", "svg_to_pptx.py"):
        path = root / "skills/ppt-master/scripts" / name
        if not path.is_file(): raise ValueError(f"missing ppt-master tool: {path}")

def build(args: argparse.Namespace) -> None:
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise ValueError(f"output must be absent or empty: {output}")
        output.rmdir()
    source = args.source.resolve(); spec = args.spec.resolve()
    if not source.is_file(): raise ValueError(f"missing source: {source}")
    if not spec.is_file(): raise ValueError(f"missing spec: {spec}")
    master_root = args.ppt_master_root.resolve()
    master_py = args.ppt_master_python.expanduser()
    if not master_py.is_absolute(): master_py = (Path.cwd() / master_py).absolute()
    validate_tools(master_root, master_py)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}.staging-", dir=output.parent) as name:
        stage = Path(name)
        (stage / "preview").mkdir(); (stage / "output").mkdir()
        shutil.copy2(spec, stage / "spec_lock.md")
        plan = stage / "slide_plan.json"; intent = stage / "layout_intent.json"
        python = str(master_py)
        run([python, str(REPO / "scripts/plan_markdown.py"), str(source), "-o", str(plan)])
        run([python, str(REPO / "scripts/assign_layout_intent.py"), str(plan), "-o", str(intent)])
        run([python, str(REPO / "scripts/materialize_content_project.py"), str(plan), str(intent), "--spec", str(stage / "spec_lock.md"), "-o", str(stage / "svg_output")])
        title = args.title or source.stem
        run([python, str(REPO / "scripts/build_preview.py"), str(stage / "svg_output"), str(stage / "preview/content-deck.html"), title, "--check"])
        quality = master_root / "skills/ppt-master/scripts/svg_quality_checker.py"
        run([str(master_py), str(quality), str(stage), "--canonical-authoring", "--stage", "final", "--json"])
        report = stage / "validation/svg_quality_report.json"
        if not report.is_file(): raise ValueError(f"quality report missing: {report}")
        data=json.loads(report.read_text(encoding="utf-8"))
        if data.get("blocking", 0) != 0 or data.get("errors", 0) != 0: raise ValueError("quality gate has blocking/errors")
        pptx = stage / "output/content-deck.pptx"
        run([str(master_py), str(master_root / "skills/ppt-master/scripts/svg_to_pptx.py"), str(stage), "-o", str(pptx)])
        slides = len(json.loads(plan.read_text(encoding="utf-8"))["slides"])
        run([python, str(REPO / "scripts/qa_pptx.py"), str(pptx), "--spec", str(stage / "spec_lock.md"), "--expected-slides", str(slides), "--expected-media", "0"])
        required=[stage/"spec_lock.md",plan,intent,stage/"preview/content-deck.html",report,pptx]
        required += sorted((stage/"svg_output").glob("*.svg"))
        if not all(p.is_file() and p.stat().st_size for p in required): raise ValueError("final artifact set incomplete")
        os.replace(stage, output)
    print(f"CONTENT_DECK_BUILT slides={slides} html=1 pptx=1")

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("source",type=Path); p.add_argument("--spec",required=True,type=Path); p.add_argument("--ppt-master-root",required=True,type=Path); p.add_argument("--ppt-master-python",required=True,type=Path); p.add_argument("-o","--output",required=True,type=Path); p.add_argument("--title"); a=p.parse_args(argv)
    try: build(a)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc: print(f"ERROR: {exc}",file=sys.stderr); return 2
    return 0
if __name__ == "__main__": raise SystemExit(main())
