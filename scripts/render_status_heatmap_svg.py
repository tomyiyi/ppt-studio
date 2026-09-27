#!/usr/bin/env python3
import argparse, hashlib, html, json
from pathlib import Path

ALLOWED={"Low","Medium","High"}
def render(slide,out):
    if slide.get("type")!="content" or slide.get("layout")!="status-heatmap": raise ValueError("status heatmap renderer requires content status-heatmap slide")
    data=[b for b in slide.get("blocks",[]) if b.get("type")=="status-heatmap"]
    if len(data)!=1 or any(b.get("type") not in {"status-heatmap","paragraph"} for b in slide.get("blocks",[])): raise ValueError("status heatmap requires exactly one block")
    items=data[0].get("items",[])
    if not 3<=len(items)<=5: raise ValueError("status heatmap requires 3-5 items")
    if data[0].get("periods")!=["W1","W2","W3","W4"]: raise ValueError("status heatmap requires W1-W4 periods")
    if len(str(slide.get("title","")))>28 or any(len(str(x.get("item","")))>18 for x in items): raise ValueError("status heatmap item exceeds budget")
    if any(len(x.get("statuses",[]))!=4 or any(v not in ALLOWED for v in x["statuses"]) for x in items): raise ValueError("status heatmap values must be Low, Medium, or High in v1")
    e=html.escape; left,right,top=250,1190,205; rowh=64; colw=(right-left)/4
    z=['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">','<rect width="1280" height="720" fill="#FFFFFF"/>', '<text x="64" y="54" font-size="20">CONTENT / OPERATIONAL RISK</text>', f'<text x="64" y="104" font-size="32" font-weight="700">{e(slide["title"])}</text>']
    intro=[b for b in slide.get("blocks",[]) if b.get("type")=="paragraph"]
    if intro: z.append(f'<text x="64" y="142" font-size="16">{e(intro[0].get("text",""))}</text>')
    for j,p in enumerate(["W1","W2","W3","W4"]):
        x=left+(j+.5)*colw; z.append(f'<text x="{x:.2f}" y="{top-32}" text-anchor="middle" font-size="16">{p}</text>')
    z.append(f'<text x="64" y="{top+28}" font-size="20">Item</text>')
    for i,item in enumerate(items):
        y=top+i*rowh; z.append(f'<text x="64" y="{y+28}" font-size="20">{e(item["item"])}</text>')
        for j,status in enumerate(item["statuses"]):
            x=left+j*colw
            z.append(f'<rect x="{x:.2f}" y="{y}" width="{colw:.2f}" height="44" fill="#F4F4F4" stroke="#222" stroke-width="1.5"/>')
            z.append(f'<text x="{x+colw/2:.2f}" y="{y+28}" text-anchor="middle" font-size="16">{status}</text>')
    z += ['<text x="64" y="676" font-size="13">Fixed W1-W4 matrix - input order preserved</text>','</svg>']
    Path(out).write_text("\n".join(z)+"\n")
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("plan"); ap.add_argument("intent"); ap.add_argument("--spec",required=True); ap.add_argument("-o",required=True); a=ap.parse_args()
    pp=Path(a.plan); plan=json.loads(pp.read_text()); intent=json.loads(Path(a.intent).read_text()); out=Path(a.o); out.mkdir(parents=True,exist_ok=True)
    if intent.get("source_plan_sha256") != hashlib.sha256(pp.read_bytes()).hexdigest(): raise ValueError("source_plan_sha256 mismatch")
    for item in intent["slides"]:
        if item["layout"]=="status-heatmap":
            slide=next(x for x in plan["slides"] if x["id"]==item["id"]); slide=dict(slide); slide["type"]="content"; slide["layout"]=item["layout"]; render(slide,out/f"{slide['id']}_status_heatmap.svg")
    print("STATUS_HEATMAP_SVG_WRITTEN slides=02 layout=status-heatmap")
if __name__=="__main__":
    try: main()
    except Exception as exc: print(f"ERROR: {exc}"); raise SystemExit(2)
