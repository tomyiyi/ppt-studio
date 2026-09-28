#!/usr/bin/env python3
import argparse, hashlib, html, json
from pathlib import Path
def render(slide,out):
    if slide.get("type")!="content" or slide.get("layout")!="target-progress": raise ValueError("target progress renderer requires content target-progress slide")
    data=[b for b in slide.get("blocks",[]) if b.get("type")=="target-progress"]
    if len(data)!=1 or any(b.get("type") not in {"target-progress","paragraph"} for b in slide.get("blocks",[])): raise ValueError("target progress requires exactly one block")
    items=data[0].get("items",[])
    if not 3<=len(items)<=5: raise ValueError("target progress requires 3-5 metrics")
    if len(str(slide.get("title","")))>28 or any(len(str(x.get("metric","")))>20 for x in items): raise ValueError("target progress metric exceeds budget")
    if any(float(x.get("actual",0))<0 or float(x.get("target",0))<=0 or float(x.get("actual",0))>9999 or float(x.get("target",0))>9999 for x in items): raise ValueError("target progress values must be non-negative and target > 0")
    e=html.escape; left,right,top=300,1190,205; track=right-left; rowh=72
    z=['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">','<rect width="1280" height="720" fill="#FFFFFF"/>','<text x="64" y="54" font-size="20">CONTENT / DELIVERY TARGETS</text>',f'<text x="64" y="104" font-size="32" font-weight="700">{e(slide["title"])}</text>']
    intro=[b for b in slide.get("blocks",[]) if b.get("type")=="paragraph"]
    if intro: z.append(f'<text x="64" y="142" font-size="16">{e(intro[0].get("text",""))}</text>')
    for i,item in enumerate(items):
        y=top+i*rowh; actual=float(item["actual"]); target=float(item["target"]); rowmax=max(actual,target)
        width=track*actual/rowmax; tx=left+track*target/rowmax
        actual_text=str(int(actual)) if actual.is_integer() else f"{actual:.2f}".rstrip("0").rstrip(".")
        target_text=str(int(target)) if target.is_integer() else f"{target:.2f}".rstrip("0").rstrip(".")
        z += [f'<text x="64" y="{y+28}" font-size="20">{e(item["metric"])}</text>',f'<text x="{left-18}" y="{y+28}" text-anchor="end" font-size="16">{actual_text}</text>',f'<rect x="{left}" y="{y}" width="{track}" height="34" fill="#F4F4F4" stroke="#222" stroke-width="1"/>',f'<rect x="{left}" y="{y}" width="{width:.2f}" height="34" rx="6" fill="#8FAFE8" stroke="#222" stroke-width="2"/>',f'<line x1="{tx:.2f}" y1="{y-8}" x2="{tx:.2f}" y2="{y+42}" stroke="#222" stroke-width="3"/>',f'<text x="{right-14}" y="{y+28}" text-anchor="end" font-size="16">Target {target_text}</text>']
    z += ['<text x="64" y="676" font-size="13">Actual bars with target reference markers - input order preserved</text>','</svg>']; Path(out).write_text("\n".join(z)+"\n")
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("plan"); ap.add_argument("intent"); ap.add_argument("--spec",required=True); ap.add_argument("-o",required=True); a=ap.parse_args()
    pp=Path(a.plan); plan=json.loads(pp.read_text()); intent=json.loads(Path(a.intent).read_text()); out=Path(a.o); out.mkdir(parents=True,exist_ok=True)
    if intent.get("source_plan_sha256") != hashlib.sha256(pp.read_bytes()).hexdigest(): raise ValueError("source_plan_sha256 mismatch")
    for item in intent["slides"]:
        if item["layout"]=="target-progress":
            slide=next(x for x in plan["slides"] if x["id"]==item["id"]); slide=dict(slide); slide["type"]="content"; slide["layout"]=item["layout"]; render(slide,out/f"{slide['id']}_target_progress.svg")
    print("TARGET_PROGRESS_SVG_WRITTEN slides=02 layout=target-progress")
if __name__=="__main__":
    try: main()
    except Exception as exc: print(f"ERROR: {exc}"); raise SystemExit(2)
