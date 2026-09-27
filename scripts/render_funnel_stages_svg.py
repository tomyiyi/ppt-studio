#!/usr/bin/env python3
import argparse, hashlib, json, re, sys
from pathlib import Path
from xml.sax.saxutils import escape

def load(p):
    raw=p.read_bytes(); return json.loads(raw), raw
def validate(plan, raw, intent):
    if intent.get("source_plan_sha256") != hashlib.sha256(raw).hexdigest(): raise ValueError("source_plan_sha256 mismatch")
    out=[]
    for slide, item in zip(plan.get("slides",[]), intent.get("slides",[])):
        if item.get("layout") != "funnel-stages": continue
        blocks=slide.get("blocks",[]); fs=[b for b in blocks if b.get("type")=="funnel-stages"]; ps=[b for b in blocks if b.get("type")=="paragraph"]
        if slide.get("kind") != "content" or len(fs)!=1 or len(ps)>1 or len(blocks)!=len(fs)+len(ps): raise ValueError("funnel-stages requires exactly 1 funnel-stages block and 0-1 paragraph")
        items=fs[0].get("items",[])
        if not 3 <= len(items) <= 5: raise ValueError("funnel stages require 3-5 items in v1")
        if len(slide.get("title",""))>28 or (ps and len(ps[0].get("text",""))>44): raise ValueError("funnel-stages text exceeds v1 budget")
        for x in items:
            if not isinstance(x,dict) or not x.get("label") or not x.get("description"): raise ValueError("funnel label and description must be non-empty")
            if len(x["label"])>18 or len(x["description"])>26: raise ValueError("funnel stage text exceeds v1 budget")
        out.append({"id":slide["id"],"title":slide.get("title",""),"intro":ps[0].get("text","") if ps else "","items":items})
    if not out: raise ValueError("no funnel-stages slides found")
    return out
def render(x,total):
    esc=lambda s:escape(str(s)); n=len(x["items"]); widths={3:[860,720,580],4:[860,760,660,560],5:[860,785,710,635,560]}[n]
    y=225; rows=[]
    for i,(item,w) in enumerate(zip(x["items"],widths)):
        left=(1280-w)//2; h=64
        rows += [f'<rect x="{left}" y="{y}" width="{w}" height="{h}" rx="12" fill="#172631" stroke="#334654"/>',f'<text x="{left+28}" y="{y+27}" font-family="Arial, sans-serif" font-size="20px" fill="#57D6B5">{esc(item["label"])}</text>',f'<text x="{left+28}" y="{y+50}" font-family="Arial, sans-serif" font-size="16px" fill="#AAB7C4">{esc(item["description"])}</text>']; y+=86
    return ''.join([ '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720"><rect width="1280" height="720" fill="#101820"/>',f'<text x="80" y="92" font-family="Arial, sans-serif" font-size="44px" fill="#F4F7FA">Execution Funnel</text>',f'<text x="80" y="130" font-family="Arial, sans-serif" font-size="20px" fill="#AAB7C4">{esc(x["intro"])}</text>',*rows,'<line x1="80" y1="620" x2="1200" y2="620" stroke="#334654"/>',f'<text x="80" y="660" font-family="Arial, sans-serif" font-size="16px" fill="#AAB7C4">{n} stages · fixed order · deterministic width</text></svg>' ])
def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("plan",type=Path);p.add_argument("intent",type=Path);p.add_argument("--spec",required=True);p.add_argument("-o",required=True,type=Path);a=p.parse_args(argv); plan,raw=load(a.plan); intent,_=load(a.intent); xs=validate(plan,raw,intent); a.o.mkdir(parents=True,exist_ok=True)
    for x in xs: (a.o/f'{x["id"]}_funnel_stages.svg').write_text(render(x,len(plan["slides"])),encoding="utf-8")
    print(f'FUNNEL_STAGES_SVG_WRITTEN slides={",".join(x["id"] for x in xs)} layout=funnel-stages')
if __name__=='__main__':
    try: main()
    except (ValueError,OSError,json.JSONDecodeError) as e: print(f'ERROR: {e}',file=sys.stderr); raise SystemExit(2)
