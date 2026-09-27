#!/usr/bin/env python3
"""Render an empty content slide as a deterministic section divider."""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
from xml.sax.saxutils import escape

def fail(message: str) -> None: raise ValueError(message)
def load(path: Path):
    raw = path.read_bytes(); value = json.loads(raw)
    if not isinstance(value, dict): fail(f"invalid JSON object: {path}")
    return value, raw
def spec(path: Path):
    text=path.read_text(encoding="utf-8"); colors={}; sizes={}
    for name in ("background","primary_text","secondary_text","accent"):
        m=re.search(rf"^\s*-\s*{name}:\s*(#[0-9A-Fa-f]{{6}})",text,re.M)
        if not m: fail(f"spec_lock missing colors.{name}")
        colors[name]=m.group(1)
    for name in ("kicker","statement","caption"):
        m=re.search(rf"^\s*-\s*{name}:\s*(\d+)\s*$",text,re.M)
        if not m: fail(f"spec_lock missing typography.{name}")
        sizes[name]=int(m.group(1))
    m=re.search(r"^\s*-\s*font_family:\s*(.+?)\s*$",text,re.M)
    if not m: fail("spec_lock missing typography.font_family")
    return colors,sizes,m.group(1).strip()
def validate(plan, plan_bytes, intent):
    if plan.get("schema")!="ppt-studio-slide-plan/v1" or intent.get("schema")!="ppt-studio-layout-intent/v1": fail("unsupported schema")
    if intent.get("source_plan_sha256")!=hashlib.sha256(plan_bytes).hexdigest(): fail("source_plan_sha256 mismatch")
    slides,intents=plan.get("slides"),intent.get("slides")
    if not isinstance(slides,list) or not isinstance(intents,list) or len(slides)!=len(intents): fail("plan and intent slides mismatch")
    selected=[]
    for slide,item in zip(slides,intents):
        if item.get("layout")!="section-divider": continue
        if slide.get("kind")!="content" or slide.get("blocks")!=[]: fail("section-divider requires empty content blocks")
        title=slide.get("title")
        if not isinstance(title,str) or not title.strip(): fail("section-divider title must be non-empty")
        if len(title)>28: fail("section-divider title exceeds v1 single-line budget")
        selected.append(slide)
    if not selected: fail("no section-divider slides found")
    return selected
def render(slide,total,colors,sizes,font):
    font=escape(font,{'"':'&quot;'}); c=colors; s=sizes; page=f'{slide["id"]} / {total:02d}'
    return "\n".join([
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',
        f'  <g id="background"><rect x="0" y="0" width="1280" height="720" fill="{c["background"]}"/></g>',
        f'  <g id="section-kicker"><text x="80" y="112" fill="{c["accent"]}" font-family="{font}" font-size="{s["kicker"]}">SECTION / {slide["id"]}</text></g>',
        f'  <g id="section-title"><text x="80" y="320" fill="{c["primary_text"]}" font-family="{font}" font-size="{s["statement"]}">{escape(slide["title"])}</text></g>',
        f'  <g id="section-accent"><rect x="80" y="386" width="240" height="4" fill="{c["accent"]}"/></g>',
        f'  <g id="footer"><text x="1200" y="648" text-anchor="end" fill="{c["secondary_text"]}" font-family="{font}" font-size="{s["caption"]}">{page}</text></g>',
        '</svg>',''])
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("plan",type=Path); p.add_argument("intent",type=Path); p.add_argument("--spec",required=True,type=Path); p.add_argument("-o",required=True,type=Path); a=p.parse_args(argv)
    plan,raw=load(a.plan); intent,_=load(a.intent); selected=validate(plan,raw,intent); colors,sizes,font=spec(a.spec); a.o.mkdir(parents=True,exist_ok=True)
    for slide in selected: (a.o/f'{slide["id"]}_section_divider.svg').write_text(render(slide,len(plan["slides"]),colors,sizes,font),encoding="utf-8")
    print(f"SECTION_DIVIDER_SVG_WRITTEN slides={','.join(s['id'] for s in selected)} layout=section-divider")
if __name__=="__main__":
    try: main()
    except (ValueError,OSError,json.JSONDecodeError) as exc: print(f"ERROR: {exc}",file=__import__('sys').stderr); raise SystemExit(2)
