#!/usr/bin/env python3
import argparse, hashlib, html, json
from pathlib import Path
def render(slide,out):
    if slide.get("type")!="content" or slide.get("layout")!="scatter-plot": raise ValueError("scatter renderer requires content scatter-plot slide")
    data=[b for b in slide.get("blocks",[]) if b.get("type")=="scatter-data"]
    if len(data)!=1 or any(b.get("type") not in {"scatter-data","paragraph"} for b in slide.get("blocks",[])): raise ValueError("scatter requires exactly one scatter-data block")
    items=data[0].get("items",[])
    if not 3<=len(items)<=6: raise ValueError("scatter requires 3-6 points")
    if len(str(slide.get("title","")))>28 or any(len(str(x.get("label","")))>14 for x in items): raise ValueError("scatter label exceeds budget")
    xs=[float(x["x"]) for x in items]; ys=[float(x["y"]) for x in items]
    left,right,top,bottom=150,1160,190,560
    def scale(v,lo,hi,a,b): return (a+b)/2 if hi==lo else a+(v-lo)/(hi-lo)*(b-a)
    e=html.escape
    z=['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">','<rect width="1280" height="720" fill="#FFFFFF"/>',f'<text x="64" y="54" font-size="20">CONTENT / SCATTER PROFILE</text>',f'<text x="64" y="104" font-size="32" font-weight="700">{e(slide["title"])}</text>',f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#555" stroke-width="2"/>',f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#555" stroke-width="2"/>',f'<text x="{right}" y="{bottom+42}" font-size="20">X</text>',f'<text x="{left-28}" y="{top-12}" font-size="20">Y</text>']
    for item in items:
        x=scale(float(item["x"]),min(xs),max(xs),left+20,right-20); y=scale(float(item["y"]),min(ys),max(ys),bottom-20,top+20)
        z += [f'<circle cx="{x:.2f}" cy="{y:.2f}" r="9" fill="#8FAFE8" stroke="#222" stroke-width="2"/>',f'<text x="{x+14:.2f}" y="{y-10:.2f}" font-size="16">{e(item["label"])}</text>',f'<text x="{x+14:.2f}" y="{y+10:.2f}" font-size="13">({item["x"]:g}, {item["y"]:g})</text>']
    z += ['<text x="64" y="676" font-size="13">Single continuous X/Y scale - input order preserved</text>','</svg>']
    Path(out).write_text("\n".join(z)+"\n")
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("plan"); ap.add_argument("intent"); ap.add_argument("--spec",required=True); ap.add_argument("-o",required=True); a=ap.parse_args()
    pp=Path(a.plan); plan=json.loads(pp.read_text()); intent=json.loads(Path(a.intent).read_text()); out=Path(a.o); out.mkdir(parents=True,exist_ok=True)
    if intent.get("source_plan_sha256") != hashlib.sha256(pp.read_bytes()).hexdigest(): raise ValueError("source_plan_sha256 mismatch")
    for item in intent["slides"]:
        if item["layout"]=="scatter-plot":
            slide=next(x for x in plan["slides"] if x["id"]==item["id"]); slide=dict(slide); slide["type"]="content"; slide["layout"]=item["layout"]; render(slide,out/f"{slide['id']}_scatter_plot.svg")
    print("SCATTER_PLOT_SVG_WRITTEN slides=02 layout=scatter-plot")
if __name__=="__main__":
    try: main()
    except Exception as exc: print(f"ERROR: {exc}"); raise SystemExit(2)
