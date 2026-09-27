#!/usr/bin/env python3
import argparse, hashlib, html, json
from pathlib import Path
SLOTS={3:[(640,230),(350,470),(930,470)],4:[(640,205),(1010,360),(640,515),(270,360)],5:[(640,190),(1030,310),(870,525),(410,525),(250,310)]}
def render(slide,out):
    if slide.get("type")!="content" or slide.get("layout")!="cycle-loop": raise ValueError("cycle renderer requires content cycle-loop slide")
    blocks=slide.get("blocks",[]); data=[b for b in blocks if b.get("type")=="cycle-stages"]
    if len(data)!=1 or any(b.get("type") not in {"cycle-stages","paragraph"} for b in blocks): raise ValueError("cycle requires exactly one cycle-stages block")
    items=data[0].get("items",[])
    if len(items) not in SLOTS: raise ValueError("cycle requires 3-5 stages")
    e=html.escape; pts=SLOTS[len(items)]
    z=['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">','<rect width="1280" height="720" fill="#FFFFFF"/>','<defs><marker markerUnits="userSpaceOnUse" id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#555"/></marker></defs>',f'<text x="64" y="104" font-size="32" font-weight="700">{e(slide["title"])}</text>']
    for i,(x,y) in enumerate(pts):
        x2,y2=pts[(i+1)%len(pts)]; z.append(f'<line x1="{x}" y1="{y}" x2="{x2}" y2="{y2}" stroke="#555" stroke-width="4" marker-end="url(#arrow)"/>')
    for (x,y),it in zip(pts,items):
        z += [f'<circle cx="{x}" cy="{y}" r="82" fill="#E8EEF8" stroke="#222" stroke-width="3"/>',f'<text x="{x}" y="{y-8}" text-anchor="middle" font-size="24" font-weight="700">{e(it["stage"])}</text>',f'<text x="{x}" y="{y+24}" text-anchor="middle" font-size="16">{e(it["detail"])}</text>']
    z += ['<text x="64" y="676" font-size="13">Single directed loop</text>','</svg>']
    Path(out).write_text("\n".join(z)+"\n")
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("plan"); ap.add_argument("intent"); ap.add_argument("--spec",required=True); ap.add_argument("-o",required=True); a=ap.parse_args()
    pp=Path(a.plan); plan=json.loads(pp.read_text()); intent=json.loads(Path(a.intent).read_text()); out=Path(a.o); out.mkdir(parents=True,exist_ok=True)
    for item in intent["slides"]:
        if item["layout"]=="cycle-loop":
            slide=next(x for x in plan["slides"] if x["id"]==item["id"]); slide=dict(slide); slide["type"]="content"; slide["layout"]=item["layout"]; render(slide,out/f"{slide['id']}_cycle_loop.svg")
    print("CYCLE_LOOP_SVG_WRITTEN slides=02 layout=cycle-loop")
if __name__=="__main__":
    try: main()
    except Exception as exc: print(f"ERROR: {exc}"); raise SystemExit(2)
