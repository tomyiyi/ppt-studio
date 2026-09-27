#!/usr/bin/env python3
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
    text=path.read_text(); colors={}; sizes={}
    for n in ("background","primary_text","secondary_text","tertiary_text","accent"):
        m=re.search(rf"^\s*-\s*{n}:\s*(#[0-9A-Fa-f]{{6}})",text,re.M)
        if not m: fail(f"spec_lock missing colors.{n}")
        colors[n]=m.group(1)
    for n in ("kicker","statement","body","caption"):
        m=re.search(rf"^\s*-\s*{n}:\s*(\d+)\s*$",text,re.M)
        if not m: fail(f"spec_lock missing typography.{n}")
        sizes[n]=int(m.group(1))
    m=re.search(r"^\s*-\s*font_family:\s*(.+?)\s*$",text,re.M)
    if not m: fail("spec_lock missing typography.font_family")
    return colors,sizes,m.group(1).strip()
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("plan",type=Path); p.add_argument("intent",type=Path); p.add_argument("--spec",required=True,type=Path); p.add_argument("-o",required=True,type=Path); a=p.parse_args(argv)
    plan,pb=load(a.plan); intent,_=load(a.intent)
    if intent.get("source_plan_sha256")!=hashlib.sha256(pb).hexdigest(): fail("source_plan_sha256 mismatch")
    slides=plan.get("slides",[]); intents=intent.get("slides",[]); selected=[]
    for s,i in zip(slides,intents):
        if i.get("layout")!="statement-split": continue
        blocks=s.get("blocks",[]); title=s.get("title")
        if s.get("kind")!="content" or len(blocks)!=2 or any(b.get("type")!="paragraph" for b in blocks): fail("statement-split requires exactly 2 paragraphs")
        if not isinstance(title,str) or len(title)>28 or any(len(b.get("text",""))>34 for b in blocks): fail("statement-split content exceeds v1 budget")
        selected.append((s["id"],title,blocks[0]["text"],blocks[1]["text"]))
    if not selected: fail("no statement-split slides found")
    c,z,font=spec(a.spec); a.o.mkdir(parents=True,exist_ok=True); total=len(slides)
    for ident,title,left,right in selected:
        e=lambda x:escape(x)
        page=f"{ident} / {total:02d}"
        text=f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">\n  <g id="background"><rect x="0" y="0" width="1280" height="720" fill="{c['background']}"/></g>\n  <g id="page-kicker"><text x="80" y="112" fill="{c['accent']}" font-family="{escape(font)}" font-size="{z['kicker']}">智流 OS</text></g>\n  <g id="statement"><text x="80" y="260" fill="{c['primary_text']}" font-family="{escape(font)}" font-size="{z['statement']}">{e(title)}</text></g>\n  <g id="statement-left"><text x="80" y="390" fill="{c['secondary_text']}" font-family="{escape(font)}" font-size="{z['body']}">{e(left)}</text></g>\n  <rect id="statement-separator" x="639" y="330" width="2" height="150" fill="{c['tertiary_text']}"/>\n  <g id="statement-right"><text x="680" y="390" fill="{c['secondary_text']}" font-family="{escape(font)}" font-size="{z['body']}">{e(right)}</text></g>\n  <g id="footer"><line x1="80" y1="608" x2="1200" y2="608" stroke="{c['accent']}"/><text x="1200" y="648" text-anchor="end" fill="{c['secondary_text']}" font-family="{escape(font)}" font-size="{z['caption']}">{page}</text></g>\n</svg>\n'''
        (a.o/f"{ident}_statement_split.svg").write_text(text)
    print(f"SPLIT_STATEMENT_SVG_WRITTEN slides={','.join(x[0] for x in selected)} layout=statement-split")
if __name__=="__main__":
    try: raise SystemExit(main())
    except ValueError as exc: print(f"ERROR: {exc}"); raise SystemExit(2)
