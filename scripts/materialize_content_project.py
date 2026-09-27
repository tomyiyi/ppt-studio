#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
RENDERERS={"cover":ROOT/"render_cover_svg.py","section-divider":ROOT/"render_section_divider_svg.py","statement":ROOT/"render_statement_svg.py","statement-split":ROOT/"render_split_statement_svg.py","statement-list":ROOT/"render_statement_list_svg.py","process-steps":ROOT/"render_process_steps_svg.py","quote-callout":ROOT/"render_quote_callout_svg.py","comparison-table":ROOT/"render_comparison_table_svg.py","three-card":ROOT/"render_three_card_svg.py","image-callout":ROOT/"render_image_callout_svg.py","image-comparison":ROOT/"render_image_comparison_svg.py","code-callout":ROOT/"render_code_callout_svg.py","metric-highlights":ROOT/"render_metric_highlights_svg.py","milestone-timeline":ROOT/"render_milestone_timeline_svg.py"}
RENDERERS["architecture-stack"]=ROOT/"render_architecture_stack_svg.py"
RENDERERS["bar-chart"]=ROOT/"render_bar_chart_svg.py"
RENDERERS["checklist-status"]=ROOT/"render_checklist_status_svg.py"
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
        names={"section-divider":"section_divider","statement-list":"statement_list","statement-split":"statement_split","process-steps":"process_steps","quote-callout":"quote_callout","comparison-table":"comparison_table","three-card":"three_card","image-callout":"image_callout","image-comparison":"image_comparison","code-callout":"code_callout","metric-highlights":"metric_highlights","milestone-timeline":"milestone_timeline","architecture-stack":"architecture_stack","bar-chart":"bar_chart","checklist-status":"checklist_status"}
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
        for slide in plan["slides"]:
            image_blocks = [b for b in slide.get("blocks", []) if b.get("type") == "image"]
            image_index = 0
            for block in slide.get("blocks", []):
                if block.get("type") != "image":
                    continue
                image_index += 1
                source = a.plan.parent / block["path"]
                if source.is_symlink() or not source.is_file(): fail(f"image asset not found: {block['path']}")
                suffix = source.suffix.lower()
                if suffix not in {".png", ".jpg", ".jpeg"}: fail("unsupported image asset")
                assets = staging / "assets"; assets.mkdir(parents=True, exist_ok=True)
                stem = "image_callout" if len(image_blocks) == 1 else f"image_{image_index}"
                shutil.copyfile(source, assets / f"{slide['id']}_{stem}{suffix}")
        for layout,renderer in RENDERERS.items():
            if any(item.get("layout")==layout for item in intent["slides"]): run_renderer(renderer,a.plan,a.intent,a.spec,staging)
        actual=sorted(x.name for x in staging.glob("*.svg"))
        if actual!=sorted(expected): fail(f"materialized files mismatch: expected {sorted(expected)}, got {actual}")
        a.output.mkdir(parents=True,exist_ok=True)
        for x in staging.glob("*.svg"): shutil.move(str(x),a.output/x.name)
        if (staging / "assets").exists(): shutil.copytree(staging / "assets", a.output / "assets")
    counts={layout:sum(item.get("layout")==layout for item in intent["slides"]) for layout in RENDERERS}
    print(f"CONTENT_PROJECT_MATERIALIZED slides={len(expected)} cover={counts['cover']} section-divider={counts['section-divider']} statement-list={counts['statement-list']} statement={counts['statement']} statement-split={counts['statement-split']} process-steps={counts['process-steps']} quote-callout={counts['quote-callout']} comparison-table={counts['comparison-table']} three-card={counts['three-card']} image-callout={counts['image-callout']} image-comparison={counts['image-comparison']} code-callout={counts['code-callout']} metric-highlights={counts['metric-highlights']} milestone-timeline={counts['milestone-timeline']}")
    return 0
if __name__=="__main__":
    try: raise SystemExit(main())
    except (ValueError,json.JSONDecodeError,OSError,subprocess.CalledProcessError) as exc: print(f"ERROR: {exc}",file=sys.stderr); raise SystemExit(2)
