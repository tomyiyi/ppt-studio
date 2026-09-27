#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re, sys
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
def validate(plan,raw,intent):
    if plan.get("schema")!="ppt-studio-slide-plan/v1" or intent.get("schema")!="ppt-studio-layout-intent/v1": fail("unsupported schema")
    if intent.get("source_plan_sha256")!=hashlib.sha256(raw).hexdigest(): fail("source_plan_sha256 mismatch")
    slides,intents=plan.get("slides"),intent.get("slides")
    out=[]
    for slide,item in zip(slides or [],intents or []):
        if item.get("layout")!="three-card": continue
        blocks=slide.get("blocks",[])
        if slide.get("kind")!="content" or len(blocks)!=3 or any(b.get("type")!="paragraph" for b in blocks): fail("three-card requires exactly 3 paragraph blocks")
        title=slide.get("title","")
        texts=[b.get("text","") for b in blocks]
        if len(title)>28: fail("three-card title exceeds v1 single-line budget")
        if any(not isinstance(t,str) or not t.strip() or len(t)>34 for t in texts): fail("three-card paragraph exceeds v1 single-line budget")
        out.append({"id":slide["id"],"title":title,"texts":texts})
    if not out: fail("no three-card slides found")
    return out
def render(x,total,c,s,font):
    font=escape(font,{"\"":"&quot;"}); xs=(80,440,800); width=320; y=235; height=245
    lines=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',f'<g id="background"><rect x="0" y="0" width="1280" height="720" fill="{c["background"]}"/></g>',f'<g id="page-kicker"><text x="80" y="92" fill="{c["accent"]}" font-family="{font}" font-size="{s["kicker"]}">CAPABILITIES / {x["id"]}</text></g>',f'<g id="three-card-title"><text x="80" y="170" fill="{c["primary_text"]}" font-family="{font}" font-size="{s["body"]}">{escape(x["title"])}</text></g>','<g id="three-card">']
    for i,(xpos,text) in enumerate(zip(xs,x["texts"]),1):
        lines += [f'<rect x="{xpos}" y="{y}" width="{width}" height="{height}" rx="8" fill="{c["surface"]}" stroke="{c["divider"]}"/>',f'<text x="{xpos+24}" y="{y+44}" fill="{c["accent"]}" font-family="{font}" font-size="{s["body"]}">0{i}</text>',f'<text x="{xpos+24}" y="{y+112}" fill="{c["primary_text"]}" font-family="{font}" font-size="{s["body"]}">{escape(text)}</text>']
    lines += ['</g>',f'<g id="footer"><line x1="80" y1="608" x2="1200" y2="608" stroke="{c["accent"]}"/><text x="1200" y="648" text-anchor="end" fill="{c["secondary_text"]}" font-family="{font}" font-size="{s["caption"]}">{x["id"]} / {total:02d}</text></g>','</svg>','']
    return "\n".join(lines)
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("plan",type=Path); p.add_argument("intent",type=Path); p.add_argument("--spec",required=True,type=Path); p.add_argument("-o",required=True,type=Path); a=p.parse_args(argv)
    plan,raw=load(a.plan); intent,_=load(a.intent); xs=validate(plan,raw,intent); c,s,f=spec(a.spec); a.o.mkdir(parents=True,exist_ok=True)
    for x in xs: (a.o/f'{x["id"]}_three_card.svg').write_text(render(x,len(plan["slides"]),c,s,f),encoding="utf-8")
    print(f"THREE_CARD_SVG_WRITTEN slides={','.join(x['id'] for x in xs)} layout=three-card")
if __name__=="__main__":
    try: main()
    except (ValueError,OSError,json.JSONDecodeError) as exc: print(f"ERROR: {exc}",file=sys.stderr); raise SystemExit(2)
