#!/usr/bin/env python3
"""Render a bounded quote callout slide."""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from pathlib import Path
from xml.sax.saxutils import escape
def fail(message): raise ValueError(message)
def load(path):
    raw=path.read_bytes(); value=json.loads(raw)
    if not isinstance(value,dict): fail(f"invalid JSON object: {path}")
    return value,raw
def spec(path):
    text=path.read_text(encoding="utf-8"); c={}; s={}
    for n in ("background","primary_text","secondary_text","accent"):
        m=re.search(rf"^\s*-\s*{n}:\s*(#[0-9A-Fa-f]{{6}})",text,re.M)
        if not m: fail(f"spec_lock missing colors.{n}")
        c[n]=m.group(1)
    for n in ("kicker","statement","caption"):
        m=re.search(rf"^\s*-\s*{n}:\s*(\d+)\s*$",text,re.M)
        if not m: fail(f"spec_lock missing typography.{n}")
        s[n]=int(m.group(1))
    m=re.search(r"^\s*-\s*font_family:\s*(.+?)\s*$",text,re.M)
    if not m: fail("spec_lock missing typography.font_family")
    return c,s,m.group(1).strip()
def validate(plan,raw,intent):
    if plan.get("schema")!="ppt-studio-slide-plan/v1" or intent.get("schema")!="ppt-studio-layout-intent/v1": fail("unsupported schema")
    if intent.get("source_plan_sha256")!=hashlib.sha256(raw).hexdigest(): fail("source_plan_sha256 mismatch")
    slides,intents=plan.get("slides"),intent.get("slides")
    if not isinstance(slides,list) or not isinstance(intents,list) or len(slides)!=len(intents): fail("plan and intent slides mismatch")
    selected=[]
    for slide,item in zip(slides,intents):
        if item.get("layout")!="quote-callout": continue
        blocks=slide.get("blocks",[])
        if slide.get("kind")!="content" or len(blocks)!=1 or blocks[0].get("type")!="quote": fail("quote-callout requires exactly one quote block")
        block=blocks[0]; lines=block.get("lines"); attribution=block.get("attribution")
        if not isinstance(lines,list) or not 1<=len(lines)<=2 or any(not isinstance(x,str) or not x.strip() for x in lines): fail("quote block supports 1-2 quote lines in v1")
        if any(len(x)>42 for x in lines): fail("quote line exceeds v1 single-line budget")
        if attribution is not None and (not isinstance(attribution,str) or not attribution.strip() or len(attribution)>28): fail("quote attribution exceeds v1 single-line budget")
        title=slide.get("title")
        if not isinstance(title,str) or len(title)>28: fail("quote-callout title exceeds v1 single-line budget")
        selected.append({"id":slide["id"],"title":title,"lines":lines,"attribution":attribution or ""})
    if not selected: fail("no quote-callout slides found")
    return selected
def render(slide,total,c,s,font):
    font=escape(font,{'"':'&quot;'}); lines=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',f'  <g id="background"><rect x="0" y="0" width="1280" height="720" fill="{c["background"]}"/></g>',f'  <g id="page-kicker"><text x="80" y="100" fill="{c["accent"]}" font-family="{font}" font-size="{s["kicker"]}">QUOTE / {slide["id"]}</text></g>',f'  <g id="quote-title"><text x="80" y="180" fill="{c["secondary_text"]}" font-family="{font}" font-size="{s["kicker"]}">{escape(slide["title"])}</text></g>',f'  <g id="quote-mark"><rect x="80" y="224" width="6" height="220" fill="{c["accent"]}"/></g>',f'  <g id="quote-lines">']
    ys=[300,378]
    for y,text in zip(ys,slide["lines"]): lines.append(f'    <text x="120" y="{y}" fill="{c["primary_text"]}" font-family="{font}" font-size="{s["statement"]}">{escape(text)}</text>')
    lines.append('  </g>')
    if slide["attribution"]: lines.append(f'  <g id="quote-attribution"><text x="120" y="470" fill="{c["secondary_text"]}" font-family="{font}" font-size="{s["caption"]}">— {escape(slide["attribution"])}</text></g>')
    lines.extend([f'  <g id="footer"><line x1="80" y1="608" x2="1200" y2="608" stroke="{c["accent"]}"/><text x="1200" y="648" text-anchor="end" fill="{c["secondary_text"]}" font-family="{font}" font-size="{s["caption"]}">{slide["id"]} / {total:02d}</text></g>','</svg>',''])
    return "\n".join(lines)
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("plan",type=Path); p.add_argument("intent",type=Path); p.add_argument("--spec",required=True,type=Path); p.add_argument("-o",required=True,type=Path); a=p.parse_args(argv); plan,raw=load(a.plan); intent,_=load(a.intent); selected=validate(plan,raw,intent); c,s,font=spec(a.spec); a.o.mkdir(parents=True,exist_ok=True)
    for x in selected: (a.o/f'{x["id"]}_quote_callout.svg').write_text(render(x,len(plan["slides"]),c,s,font),encoding="utf-8")
    print(f"QUOTE_CALLOUT_SVG_WRITTEN slides={','.join(x['id'] for x in selected)} layout=quote-callout")
if __name__=="__main__":
    try: main()
    except (ValueError,OSError,json.JSONDecodeError) as exc: print(f"ERROR: {exc}",file=sys.stderr); raise SystemExit(2)
