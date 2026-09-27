#!/usr/bin/env python3
import argparse,html,json
from pathlib import Path
W,H=1280,720
def render(plan,out):
    if plan.get("type")!="content" or plan.get("layout")!="waterfall-change": raise ValueError("waterfall renderer requires content waterfall-change slide")
    bs=[b for b in plan.get("blocks",[]) if b.get("type")=="waterfall-data"]
    if len(bs)!=1 or any(b.get("type") not in {"waterfall-data","paragraph"} for b in plan.get("blocks",[])): raise ValueError("waterfall renderer requires exactly one waterfall-data block")
    items=bs[0].get("items",[])
    if not 3<=len(items)<=5: raise ValueError("waterfall renderer requires 3-5 items")
    title=plan.get("title",""); intro=next((b.get("text","") for b in plan.get("blocks",[]) if b.get("type")=="paragraph"),"")
    if len(title)>28 or len(intro)>44 or any(len(str(x.get("driver","")))>18 for x in items): raise ValueError("waterfall text budget exceeded")
    run=0.; totals=[]
    for x in items: start=run; run+=x["delta"]; totals.append((start,run))
    vals=[0.]+[v for pair in totals for v in pair]; lo,hi=min(vals),max(vals); pad=(hi-lo)*.12 or 1.; lo-=pad; hi+=pad
    x0,x1,y0,y1=120,1160,300,560; scale=(y1-y0)/(hi-lo); y=lambda v:y1-(v-lo)*scale; gap=(x1-x0)/len(items); bw=min(150,gap*.56)
    e=html.escape; z=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">','<rect width="1280" height="720" fill="#fff"/>',f'<text x="64" y="54" font-size="20">CONTENT / CHANGE DRIVERS</text>',f'<text x="64" y="104" font-size="32" font-weight="700">{e(title)}</text>']
    if intro:z.append(f'<text x="64" y="142" font-size="20">{e(intro)}</text>')
    z.append(f'<line x1="{x0-20}" y1="{y(0):.2f}" x2="{x1+20}" y2="{y(0):.2f}" stroke="#777" stroke-width="2"/>'); prev=None
    for i,(it,(a,b)) in enumerate(zip(items,totals)):
        cx=x0+gap*(i+.5); top=min(y(a),y(b)); h=abs(y(b)-y(a)); fill="#d9e8ff" if it["delta"]>0 else "#f0d7d7"
        z.append(f'<rect x="{cx-bw/2:.2f}" y="{top:.2f}" width="{bw:.2f}" height="{max(h,2):.2f}" fill="{fill}" stroke="#222" stroke-width="2"/>')
        if prev is not None:z.append(f'<line x1="{prev:.2f}" y1="{y(a):.2f}" x2="{cx-bw/2:.2f}" y2="{y(a):.2f}" stroke="#555" stroke-width="2"/>')
        label=f'{"+" if it["delta"]>0 else ""}{it["delta"]:g}'; z += [f'<text x="{cx:.2f}" y="{top-12:.2f}" text-anchor="middle" font-size="20" font-weight="700">{label}</text>',f'<text x="{cx:.2f}" y="602" text-anchor="middle" font-size="20">{e(it["driver"])}</text>']; prev=cx+bw/2
    z += [f'<text x="{x1+30}" y="{y(run)-12:.2f}" font-size="24" font-weight="700">NET {run:g}</text>','<text x="64" y="676" font-size="13">Deterministic cumulative change · input order preserved</text>','</svg>']; Path(out).write_text("\n".join(z)+"\n")
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("plan"); ap.add_argument("intent"); ap.add_argument("--spec",required=True); ap.add_argument("-o",required=True); a=ap.parse_args()
    plan_path=Path(a.plan); plan=json.loads(plan_path.read_text()); intent=json.loads(Path(a.intent).read_text())
    if intent.get("source_plan_sha256") != __import__("hashlib").sha256(plan_path.read_bytes()).hexdigest(): raise ValueError("source_plan_sha256 mismatch")
    out=Path(a.o); out.mkdir(parents=True,exist_ok=True)
    for item in intent["slides"]:
        if item["layout"]!="waterfall-change": continue
        slide=next(x for x in plan["slides"] if x["id"]==item["id"])
        target=out/f'{slide["id"]}_waterfall_change.svg'
        slide=dict(slide); slide["type"]="content"; slide["layout"]="waterfall-change"
        render(slide,target)
    print("WATERFALL_CHANGE_SVG_WRITTEN slides=02 layout=waterfall-change")
if __name__=="__main__":
    try: main()
    except Exception as exc: print(f"ERROR: {exc}"); raise SystemExit(2)
