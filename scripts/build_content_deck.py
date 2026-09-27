#!/usr/bin/env python3
"""Atomically build the validated V1 Markdown content deck."""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

def sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run(argv: list[str], cwd: Path = REPO) -> None:
    subprocess.run(argv, cwd=cwd, check=True)

def validate_tools(root: Path, py: Path) -> None:
    if not py.is_file() or not os.access(py, os.X_OK):
        raise ValueError(f"ppt-master Python is not executable: {py}")
    for name in ("svg_quality_checker.py", "svg_to_pptx.py"):
        path = root / "skills/ppt-master/scripts" / name
        if not path.is_file(): raise ValueError(f"missing ppt-master tool: {path}")

def resolve_toolchain(args: argparse.Namespace) -> tuple[Path, Path, str | None]:
    if bool(args.toolchain_config) == bool(args.ppt_master_root or args.ppt_master_python):
        raise ValueError("use either --toolchain-config or both explicit ppt-master paths")
    if args.toolchain_config:
        try: data = json.loads(args.toolchain_config.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc: raise ValueError(f"invalid toolchain config: {exc}")
        if not isinstance(data, dict) or data.get("schema") != "ppt-studio-toolchain/v1": raise ValueError("unsupported toolchain config schema")
        for key in ("ppt_master_root", "ppt_master_python", "ppt_master_expected_head"):
            if not isinstance(data.get(key), str) or not data[key]: raise ValueError(f"missing toolchain field: {key}")
        root, py, expected = Path(data["ppt_master_root"]).expanduser(), Path(data["ppt_master_python"]).expanduser(), data["ppt_master_expected_head"]
    else:
        if args.ppt_master_root is None or args.ppt_master_python is None: raise ValueError("both --ppt-master-root and --ppt-master-python are required")
        root, py, expected = args.ppt_master_root, args.ppt_master_python, None
    if not root.is_absolute(): root = (Path.cwd() / root).absolute()
    if not py.is_absolute(): py = (Path.cwd() / py).absolute()
    actual = None
    if expected:
        try: actual = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc: raise ValueError(f"cannot read ppt-master HEAD: {exc}")
        if actual != expected: raise ValueError(f"ppt-master HEAD mismatch: expected {expected}, actual {actual}")
    elif (root / ".git").exists():
        try:
            actual = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            actual = None
    return root.resolve(), py, actual

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
    master_root, master_py, master_head = resolve_toolchain(args)
    validate_tools(master_root, master_py)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}.staging-", dir=output.parent) as name:
        stage = Path(name)
        (stage / "preview").mkdir(); (stage / "output").mkdir()
        shutil.copy2(spec, stage / "spec_lock.md")
        (stage / "source.md").write_bytes(source.read_bytes())
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
        required=[stage/"source.md",stage/"spec_lock.md",plan,intent,stage/"preview/content-deck.html",report,pptx]
        required += sorted((stage/"svg_output").glob("*.svg"))
        if not all(p.is_file() and p.stat().st_size for p in required): raise ValueError("final artifact set incomplete")
        receipt = {
            "schema": "ppt-studio-content-build-receipt/v1",
            "slides": slides,
            "inputs": {
                "markdown_sha256": sha256(source),
                "spec_sha256": sha256(stage / "spec_lock.md"),
                "slide_plan_sha256": sha256(plan),
                "layout_intent_sha256": sha256(intent),
            },
            "toolchain": {"ppt_master_head": master_head},
            "artifacts": {
                "svg": {p.name: sha256(p) for p in sorted((stage / "svg_output").glob("*.svg"))},
                "html_sha256": sha256(stage / "preview/content-deck.html"),
                "svg_quality_report_sha256": sha256(report),
                "pptx_sha256": sha256(pptx),
            },
        }
        (stage / "build_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(stage, output)
    print(f"CONTENT_DECK_BUILT slides={slides} html=1 pptx=1")

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("source",type=Path); p.add_argument("--spec",required=True,type=Path); p.add_argument("--toolchain-config",type=Path); p.add_argument("--ppt-master-root",type=Path); p.add_argument("--ppt-master-python",type=Path); p.add_argument("-o","--output",required=True,type=Path); p.add_argument("--title"); a=p.parse_args(argv)
    try: build(a)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc: print(f"ERROR: {exc}",file=sys.stderr); return 2
    return 0
if __name__ == "__main__": raise SystemExit(main())
