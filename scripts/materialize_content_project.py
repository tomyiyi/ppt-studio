#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
RENDERERS={"cover":ROOT/"render_cover_svg.py","section-divider":ROOT/"render_section_divider_svg.py","statement":ROOT/"render_statement_svg.py","statement-split":ROOT/"render_split_statement_svg.py","statement-list":ROOT/"render_statement_list_svg.py","process-steps":ROOT/"render_process_steps_svg.py","quote-callout":ROOT/"render_quote_callout_svg.py","comparison-table":ROOT/"render_comparison_table_svg.py"}
def fail(message): raise ValueError(message)
def load(path):
    raw=path.read_bytes(); value=json.loads(raw)
    if not isinstance(value,dict): fail(f"JSON object required: {path}")
    return value,raw
def expected_files(plan,intent,raw):
    if plan.get("schema")!="ppt-studio-slide-plan/v1": fail("unsupported slide plan schema")
    if intent.get("schema")!="ppt-studio-layout-intent/v1": fail("unsupported layout intent schema")
    if intent.get("source_plan_sha256")!=hashlib.sha256(raw).hexdigest(): fail("source_plan_sha256 mismatch")
    slides,intents=plan.get("slides"),intent.get("slides")
    if not isinstance(slides,list) or not isinstance(intents,list) or len(slides)!=len(intents) or not slides: fail("plan and intent slides must be non-empty lists of equal length")
    if [s.get("id") for s in slides]!=[i.get("id") for i in intents]: fail("plan and intent slide IDs mismatch")
    result=[]
    for slide,item in zip(slides,intents):
        layout=item.get("layout")
        if layout not in RENDERERS: fail(f"unsupported layout: {layout}")
        names={"section-divider":"section_divider","statement-list":"statement_list","statement-split":"statement_split","process-steps":"process_steps","quote-callout":"quote_callout","comparison-table":"comparison_table"}
        result.append(f"{slide.get('id')}_{names.get(layout,layout)}.svg")
    return result
def run_renderer(renderer,plan,intent,spec,output): subprocess.run([sys.executable,str(renderer),str(plan),str(intent),"--spec",str(spec),"-o",str(output)],check=True)
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("plan",type=Path); p.add_argument("intent",type=Path); p.add_argument("--spec",required=True,type=Path); p.add_argument("-o","--output",required=True,type=Path); a=p.parse_args(argv)
    plan,raw=load(a.plan); intent,_=load(a.intent); expected=expected_files(plan,intent,raw)
    if a.output.exists() and any(a.output.iterdir()): fail("output directory must be empty")
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="content-project-",dir=a.output.parent) as name:
        staging=Path(name)
        for layout,renderer in RENDERERS.items():
            if any(item.get("layout")==layout for item in intent["slides"]): run_renderer(renderer,a.plan,a.intent,a.spec,staging)
        actual=sorted(x.name for x in staging.glob("*.svg"))
        if actual!=sorted(expected): fail(f"materialized files mismatch: expected {sorted(expected)}, got {actual}")
        a.output.mkdir(parents=True,exist_ok=True)
        for x in staging.glob("*.svg"): shutil.move(str(x),a.output/x.name)
    counts={layout:sum(item.get("layout")==layout for item in intent["slides"]) for layout in RENDERERS}
    print(f"CONTENT_PROJECT_MATERIALIZED slides={len(expected)} cover={counts['cover']} section-divider={counts['section-divider']} statement-list={counts['statement-list']} statement={counts['statement']} statement-split={counts['statement-split']} process-steps={counts['process-steps']} quote-callout={counts['quote-callout']} comparison-table={counts['comparison-table']}")
    return 0
if __name__=="__main__":
    try: raise SystemExit(main())
    except (ValueError,json.JSONDecodeError,OSError,subprocess.CalledProcessError) as exc: print(f"ERROR: {exc}",file=sys.stderr); raise SystemExit(2)
