#!/usr/bin/env python3
"""Render a bounded ordered-steps content slide."""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from pathlib import Path
from xml.sax.saxutils import escape

def fail(message): raise ValueError(message)
def load(path):
    raw=path.read_bytes(); value=json.loads(raw)
    if not isinstance(value,dict): fail(f"invalid JSON object: {path}")
    return value,raw
def load_spec(path):
    text=path.read_text(encoding="utf-8"); colors={}; sizes={}
    for name in ("background","primary_text","secondary_text","tertiary_text","accent","divider"):
        m=re.search(rf"^\s*-\s*{name}:\s*(#[0-9A-Fa-f]{{6}})",text,re.M)
        if m: colors[name]=m.group(1)
    for name in ("kicker","statement","body","caption"):
        m=re.search(rf"^\s*-\s*{name}:\s*(\d+)\s*$",text,re.M)
        if not m: fail(f"spec_lock missing typography.{name}")
        sizes[name]=int(m.group(1))
    if "divider" not in colors: colors["divider"]="#23242E"
    m=re.search(r"^\s*-\s*font_family:\s*(.+?)\s*$",text,re.M)
    if not m: fail("spec_lock missing typography.font_family")
    return colors,sizes,m.group(1).strip()
def validate(plan,raw,intent):
    if plan.get("schema")!="ppt-studio-slide-plan/v1" or intent.get("schema")!="ppt-studio-layout-intent/v1": fail("unsupported schema")
    if intent.get("source_plan_sha256")!=hashlib.sha256(raw).hexdigest(): fail("source_plan_sha256 mismatch")
    slides,intents=plan.get("slides"),intent.get("slides")
    if not isinstance(slides,list) or not isinstance(intents,list) or len(slides)!=len(intents): fail("plan and intent slides mismatch")
    selected=[]
    for slide,item in zip(slides,intents):
        if item.get("layout")!="process-steps": continue
        blocks=slide.get("blocks",[]); steps=[b for b in blocks if isinstance(b,dict) and b.get("type")=="steps"]; paras=[b for b in blocks if isinstance(b,dict) and b.get("type")=="paragraph"]
        if slide.get("kind")!="content" or len(steps)!=1 or len(paras)>1 or len(blocks)!=len(steps)+len(paras): fail("process-steps supports one steps block and at most one paragraph")
        items=steps[0].get("items")
        if not isinstance(items,list) or not 2<=len(items)<=4: fail("process-steps requires 2-4 steps")
        title=slide.get("title")
        if not isinstance(title,str) or not title.strip() or len(title)>28: fail("process-steps title exceeds v1 single-line budget")
        intro=paras[0].get("text","") if paras else ""
        if len(intro)>48: fail("process-steps intro exceeds v1 single-line budget")
        if any(not isinstance(x,str) or not x.strip() or len(x)>26 for x in items): fail("process-steps item exceeds v1 single-line budget")
        selected.append({"id":slide["id"],"title":title,"intro":intro,"items":items})
    if not selected: fail("no process-steps slides found")
    return selected
def render(slide,total,c,s,font):
    font=escape(font,{'"':'&quot;'}); y=270 if not slide["intro"] else 290; gap=88; lines=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',f'  <g id="background"><rect x="0" y="0" width="1280" height="720" fill="{c["background"]}"/></g>',f'  <g id="page-kicker"><text x="80" y="92" fill="{c["accent"]}" font-family="{font}" font-size="{s["kicker"]}">PROCESS / {slide["id"]}</text></g>',f'  <g id="process-title"><text x="80" y="180" fill="{c["primary_text"]}" font-family="{font}" font-size="{s["statement"]}">{escape(slide["title"])}</text></g>']
    if slide["intro"]: lines.append(f'  <g id="process-intro"><text x="80" y="228" fill="{c["secondary_text"]}" font-family="{font}" font-size="{s["body"]}">{escape(slide["intro"])}</text></g>')
    lines.append('  <g id="process-steps">')
    for index,item in enumerate(slide["items"],1):
        cy=y+(index-1)*gap
        lines.append(f'    <rect x="80" y="{cy-20}" width="40" height="40" rx="20" fill="{c["accent"]}"/><text x="100" y="{cy+6}" text-anchor="middle" fill="{c["background"]}" font-family="{font}" font-size="{s["body"]}">{index:02d}</text><text x="152" y="{cy+6}" fill="{c["primary_text"]}" font-family="{font}" font-size="{s["body"]}">{escape(item)}</text>')
        if index<len(slide["items"]): lines.append(f'    <line x1="100" y1="{cy+20}" x2="100" y2="{cy+gap-20}" stroke="{c["divider"]}"/>')
    lines.extend(["  </g>",f'  <g id="footer"><line x1="80" y1="608" x2="1200" y2="608" stroke="{c["accent"]}"/><text x="1200" y="648" text-anchor="end" fill="{c["secondary_text"]}" font-family="{font}" font-size="{s["caption"]}">{slide["id"]} / {total:02d}</text></g>','</svg>',''])
    return "\n".join(lines)
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("plan",type=Path); p.add_argument("intent",type=Path); p.add_argument("--spec",required=True,type=Path); p.add_argument("-o",required=True,type=Path); a=p.parse_args(argv); plan,raw=load(a.plan); intent,_=load(a.intent); selected=validate(plan,raw,intent); c,s,font=load_spec(a.spec); a.o.mkdir(parents=True,exist_ok=True)
    for slide in selected: (a.o/f'{slide["id"]}_process_steps.svg').write_text(render(slide,len(plan["slides"]),c,s,font),encoding="utf-8")
    print(f"PROCESS_STEPS_SVG_WRITTEN slides={','.join(x['id'] for x in selected)} layout=process-steps")
if __name__=="__main__":
    try: main()
    except (ValueError,OSError,json.JSONDecodeError) as exc: print(f"ERROR: {exc}",file=sys.stderr); raise SystemExit(2)
