#!/usr/bin/env python3
import argparse,html,json,hashlib
from pathlib import Path
def render(slide,out):
    if slide.get("type")!="content" or slide.get("layout")!="grouped-bar-comparison": raise ValueError("grouped bar renderer requires content grouped-bar-comparison slide")
    bs=[b for b in slide.get("blocks",[]) if b.get("type")=="grouped-bar-data"]
    if len(bs)!=1 or any(b.get("type") not in {"grouped-bar-data","paragraph"} for b in slide.get("blocks",[])): raise ValueError("grouped bar requires exactly one grouped-bar-data block")
    items=bs[0].get("items",[])
    if not 3<=len(items)<=5: raise ValueError("grouped bar requires 3-5 items")
    if len(str(slide.get("title","")))>28: raise ValueError("grouped bar title exceeds budget")
    if any(len(str(x.get("category","")))>16 or len(x.get("values",[]))!=2 for x in items): raise ValueError("grouped bar item exceeds budget")
    vals=[v for x in items for v in x["values"]]; hi=max(vals) or 1
    x0,x1=130,1160; y0,y1=220,520; gap=(x1-x0)/len(items); bw=min(42,gap*.22); scale=(y1-y0)/hi
    e=html.escape; z=['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">','<rect width="1280" height="720" fill="#FFFFFF"/>',f'<text x="64" y="54" font-size="20">CONTENT / BEFORE VS AFTER</text>',f'<text x="64" y="104" font-size="32" font-weight="700">{e(slide["title"])}</text>',f'<line x1="{x0-30}" y1="{y1}" x2="{x1+30}" y2="{y1}" stroke="#777" stroke-width="2"/>']
    for i,it in enumerate(items):
        cx=x0+gap*(i+.5)
        for j,v in enumerate(it["values"]):
            x=cx+(j-.5)*(bw+8); h=v*scale; y=y1-h; fill="#C9D9F5" if j==0 else "#8FAFE8"
            z += [f'<rect x="{x:.2f}" y="{y:.2f}" width="{bw:.2f}" height="{h:.2f}" fill="{fill}" stroke="#222" stroke-width="2"/>',f'<text x="{x+bw/2:.2f}" y="{y-10:.2f}" text-anchor="middle" font-size="20">{v:g}</text>']
        z.append(f'<text x="{cx:.2f}" y="564" text-anchor="middle" font-size="20">{e(it["category"])}</text>')
    z += ['<rect x="930" y="132" width="18" height="18" fill="#C9D9F5"/><text x="958" y="148" font-size="20">Before</text>','<rect x="1040" y="132" width="18" height="18" fill="#8FAFE8"/><text x="1068" y="148" font-size="20">After</text>','<text x="64" y="676" font-size="13">Two fixed series · category order preserved</text>','</svg>']
    Path(out).write_text("\n".join(z)+"\n")
def main():
    ap=argparse.ArgumentParser();ap.add_argument("plan");ap.add_argument("intent");ap.add_argument("--spec",required=True);ap.add_argument("-o",required=True);a=ap.parse_args()
    pp=Path(a.plan);plan=json.loads(pp.read_text());intent=json.loads(Path(a.intent).read_text())
    if intent.get("source_plan_sha256") != hashlib.sha256(pp.read_bytes()).hexdigest(): raise ValueError("source_plan_sha256 mismatch")
    out=Path(a.o);out.mkdir(parents=True,exist_ok=True)
    for item in intent["slides"]:
        if item["layout"]=="grouped-bar-comparison":
            slide=next(x for x in plan["slides"] if x["id"]==item["id"]);slide=dict(slide);slide["type"]="content";slide["layout"]=item["layout"];render(slide,out/f'{slide["id"]}_grouped_bar_comparison.svg')
    print("GROUPED_BAR_COMPARISON_SVG_WRITTEN slides=02 layout=grouped-bar-comparison")
if __name__=="__main__":
    try:main()
    except Exception as exc:print(f"ERROR: {exc}");raise SystemExit(2)
