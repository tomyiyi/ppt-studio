from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
from xml.sax.saxutils import escape

def fail(message): raise ValueError(message)
def load(path):
    raw=path.read_bytes(); value=json.loads(raw)
    if not isinstance(value,dict): fail("invalid JSON object")
    return value,raw
def spec(path):
    text=path.read_text(encoding="utf-8"); colors={}; sizes={}
    for name in ("background","surface","primary_text","secondary_text","accent","divider"):
        m=re.search(rf"^\s*-\s*{name}:\s*(#[0-9A-Fa-f]{{6}})",text,re.M)
        if m: colors[name]=m.group(1)
    colors.setdefault("background","#0B0C10"); colors.setdefault("surface","#12131A"); colors.setdefault("divider","#23242E")
    for name in ("kicker","body","caption"):
        m=re.search(rf"^\s*-\s*{name}:\s*(\d+)\s*$",text,re.M)
        if not m: fail(f"spec_lock missing typography.{name}")
        sizes[name]=int(m.group(1))
    m=re.search(r"^\s*-\s*font_family:\s*(.+?)\s*$",text,re.M)
    if not m: fail("spec_lock missing typography.font_family")
    return colors,sizes,m.group(1).strip()
def validate(plan, raw, intent):
    if plan.get("schema")!="ppt-studio-slide-plan/v1" or intent.get("schema")!="ppt-studio-layout-intent/v1": fail("unsupported schema")
    if intent.get("source_plan_sha256")!=hashlib.sha256(raw).hexdigest(): fail("source_plan_sha256 mismatch")
    out=[]
    for slide,item in zip(plan.get("slides",[]),intent.get("slides",[])):
        if item.get("layout")!="metric-highlights": continue
        blocks=slide.get("blocks",[]); metrics=[b for b in blocks if b.get("type")=="metric-list"]; paragraphs=[b for b in blocks if b.get("type")=="paragraph"]
        if slide.get("kind")!="content" or len(metrics)!=1 or len(paragraphs)>1 or len(blocks)!=len(metrics)+len(paragraphs): fail("metric-highlights requires exactly 1 metric-list and 0-1 paragraph")
        items=metrics[0].get("items",[])
        if not 2<=len(items)<=4: fail("metric list requires 2-4 items in v1")
        if len(slide.get("title",""))>28 or (paragraphs and len(paragraphs[0].get("text",""))>44): fail("metric-highlights text exceeds v1 budget")
        for x in items:
            if not isinstance(x,dict) or not x.get("label") or not x.get("value"): fail("metric label and value must be non-empty")
            if len(x["label"])>16 or len(x["value"])>12: fail("metric label/value exceeds v1 budget")
        out.append({"id":slide["id"],"title":slide.get("title",""),"intro":paragraphs[0].get("text","") if paragraphs else "","items":items})
    if not out: fail("no metric-highlights slides found")
    return out
def render(x,total,c,s,font):
    intro=f'<text x="80" y="218" fill="{c["secondary_text"]}" font-family="{escape(font)}" font-size="{s["caption"]}">{escape(x["intro"])}</text>' if x["intro"] else ''
    coords=[(80,280),(650,280),(80,455),(650,455)]
    cards=[]
    for i,item in enumerate(x["items"]):
        cx,cy=coords[i]
        cards += [f'<rect x="{cx}" y="{cy}" width="550" height="135" rx="8" fill="{c["surface"]}" stroke="{c["divider"]}"/>',f'<text x="{cx+28}" y="{cy+58}" fill="{c["primary_text"]}" font-family="{escape(font)}" font-size="{s["body"]}">{escape(item["value"])}</text>',f'<text x="{cx+28}" y="{cy+102}" fill="{c["secondary_text"]}" font-family="{escape(font)}" font-size="{s["caption"]}">{escape(item["label"])}</text>']
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',f'<rect width="1280" height="720" fill="{c["background"]}"/>',f'<text x="80" y="92" fill="{c["accent"]}" font-family="{escape(font)}" font-size="{s["kicker"]}">METRIC HIGHLIGHTS / {x["id"]}</text>',f'<text x="80" y="170" fill="{c["primary_text"]}" font-family="{escape(font)}" font-size="{s["body"]}">{escape(x["title"])}</text>',intro,*cards,f'<line x1="80" y1="608" x2="1200" y2="608" stroke="{c["accent"]}"/>',f'<text x="1200" y="648" text-anchor="end" fill="{c["secondary_text"]}" font-family="{escape(font)}" font-size="{s["caption"]}">{x["id"]} / {total:02d}</text>','</svg>',''])
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("plan",type=Path); p.add_argument("intent",type=Path); p.add_argument("--spec",required=True,type=Path); p.add_argument("-o",required=True,type=Path); a=p.parse_args(argv)
    plan,raw=load(a.plan); intent,_=load(a.intent); xs=validate(plan,raw,intent); c,s,f=spec(a.spec); a.o.mkdir(parents=True,exist_ok=True)
    for x in xs: (a.o/f'{x["id"]}_metric_highlights.svg').write_text(render(x,len(plan["slides"]),c,s,f),encoding="utf-8")
    print(f"METRIC_HIGHLIGHTS_SVG_WRITTEN slides={','.join(x['id'] for x in xs)} layout=metric-highlights")
if __name__=="__main__":
    try: main()
    except (ValueError,OSError,json.JSONDecodeError) as exc: print(f"ERROR: {exc}",file=__import__('sys').stderr); raise SystemExit(2)
