#!/usr/bin/env python3
import argparse, hashlib, json
from pathlib import Path
from xml.sax.saxutils import escape

COLORS=["#7AA2F7","#8BD5CA","#F5C26B","#C9A7FF","#F28E8E"]

def main():
    p=argparse.ArgumentParser(); p.add_argument("plan"); p.add_argument("intent"); p.add_argument("--spec",required=True); p.add_argument("-o",required=True); a=p.parse_args()
    plan_path=Path(a.plan); plan=json.loads(plan_path.read_text()); intent=json.loads(Path(a.intent).read_text())
    if intent.get("source_plan_sha256") != hashlib.sha256(plan_path.read_bytes()).hexdigest(): raise ValueError("source_plan_sha256 mismatch")
    out=Path(a.o); out.mkdir(parents=True,exist_ok=True)
    for item in intent["slides"]:
        if item["layout"] != "composition-bar": continue
        slide=next(x for x in plan["slides"] if x["id"]==item["id"])
        blocks=[b for b in slide.get("blocks",[]) if b.get("type")=="composition-data"]
        if len(blocks)!=1 or len(slide.get("blocks",[]))!=1: raise ValueError("composition-bar requires exactly one composition-data block")
        items=blocks[0]["items"]
        if not 3<=len(items)<=5 or sum(x["share"] for x in items)!=100: raise ValueError("invalid composition data")
        x0,x1=100,1180; total=x1-x0; cursor=x0
        rects=[]; labels=[]
        for idx,entry in enumerate(items):
            width=(x1-cursor) if idx==len(items)-1 else total*entry["share"]/100
            rects.append(f'<rect x="{cursor:.1f}" y="270" width="{width:.1f}" height="120" fill="{COLORS[idx]}" stroke="#0B0C10" stroke-width="2"/>')
            labels.append(f'<text x="{cursor+width/2:.1f}" y="342" text-anchor="middle" fill="#0B0C10" font-family="sans-serif" font-size="24">{entry["share"]}%</text>')
            cursor += width
        legend=[]
        slots=[180,460,740,1020,1100]
        for idx,entry in enumerate(items):
            lx=100 + idx*260
            legend += [f'<text x="{lx}" y="485" fill="#F4F5F7" font-family="sans-serif" font-size="20">{idx+1:02d} {escape(entry["segment"])}</text>',f'<text x="{lx+180}" y="485" fill="#A9ADBA" font-family="sans-serif" font-size="20" text-anchor="end">{entry["share"]}%</text>']
        svg=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"><rect width="1280" height="720" fill="#0B0C10"/>',f'<text x="80" y="132" fill="#F4F5F7" font-family="sans-serif" font-size="32">{escape(slide["title"])}</text>']+rects+labels+legend+['<line x1="80" y1="650" x2="1200" y2="650" stroke="#7AA2F7"/>','</svg>','']
        (out/f'{slide["id"]}_composition_bar.svg').write_text("\n".join(svg))
    print("COMPOSITION_BAR_SVG_WRITTEN slides=02 layout=composition-bar")
if __name__=="__main__":
    try: main()
    except Exception as exc: print(f"ERROR: {exc}"); raise SystemExit(2)
