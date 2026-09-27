#!/usr/bin/env python3
import argparse, hashlib, html, json
from pathlib import Path
def render(slide,out):
    if slide.get("type")!="content" or slide.get("layout")!="gantt-schedule": raise ValueError("gantt renderer requires content gantt-schedule slide")
    data=[b for b in slide.get("blocks",[]) if b.get("type")=="gantt-schedule"]
    if len(data)!=1 or any(b.get("type") not in {"gantt-schedule","paragraph"} for b in slide.get("blocks",[])): raise ValueError("gantt requires exactly one gantt-schedule block")
    items=data[0].get("items",[])
    if not 3<=len(items)<=5: raise ValueError("gantt requires 3-5 tasks")
    if len(str(slide.get("title","")))>28 or any(len(str(x.get("task","")))>20 for x in items): raise ValueError("gantt task exceeds budget")
    left,right,top=250,1190,210
    gridw=right-left; slot=gridw/12; rowh=68
    e=html.escape
    z=['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">','<rect width="1280" height="720" fill="#FFFFFF"/>',f'<text x="64" y="54" font-size="20">CONTENT / DELIVERY SCHEDULE</text>',f'<text x="64" y="104" font-size="32" font-weight="700">{e(slide["title"])}</text>']
    for w in range(13):
        x=left+w*slot; z.append(f'<line x1="{x:.2f}" y1="{top-28}" x2="{x:.2f}" y2="{top+rowh*len(items)-12}" stroke="#D0D0D0" stroke-width="1"/>')
    for w in range(1,13):
        x=left+(w-.5)*slot; z.append(f'<text x="{x:.2f}" y="{top-42}" text-anchor="middle" font-size="16">W{w}</text>')
    for i,item in enumerate(items):
        y=top+i*rowh; start,end=int(item["start"]),int(item["end"]); x=left+(start-1)*slot; width=(end-start+1)*slot
        z += [f'<text x="64" y="{y+28}" font-size="20">{e(item["task"])}</text>',f'<rect x="{x:.2f}" y="{y}" width="{width:.2f}" height="34" rx="6" fill="#8FAFE8" stroke="#222" stroke-width="2"/>',f'<text x="{x+width/2:.2f}" y="{y+23}" text-anchor="middle" font-size="16">W{start}-W{end}</text>']
    z += ['<text x="64" y="676" font-size="13">Fixed 12-week slots - input order preserved</text>','</svg>']
    Path(out).write_text("\n".join(z)+"\n")
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("plan"); ap.add_argument("intent"); ap.add_argument("--spec",required=True); ap.add_argument("-o",required=True); a=ap.parse_args()
    pp=Path(a.plan); plan=json.loads(pp.read_text()); intent=json.loads(Path(a.intent).read_text()); out=Path(a.o); out.mkdir(parents=True,exist_ok=True)
    if intent.get("source_plan_sha256") != hashlib.sha256(pp.read_bytes()).hexdigest(): raise ValueError("source_plan_sha256 mismatch")
    for item in intent["slides"]:
        if item["layout"]=="gantt-schedule":
            slide=next(x for x in plan["slides"] if x["id"]==item["id"]); slide=dict(slide); slide["type"]="content"; slide["layout"]=item["layout"]; render(slide,out/f"{slide['id']}_gantt_schedule.svg")
    print("GANTT_SCHEDULE_SVG_WRITTEN slides=02 layout=gantt-schedule")
if __name__=="__main__":
    try: main()
    except Exception as exc: print(f"ERROR: {exc}"); raise SystemExit(2)
