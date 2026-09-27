#!/usr/bin/env python3
"""Render a bounded two-column comparison table."""
from __future__ import annotations
import argparse,hashlib,json,re,sys
from pathlib import Path
from xml.sax.saxutils import escape
def fail(m): raise ValueError(m)
def load(p):
 raw=p.read_bytes(); v=json.loads(raw)
 if not isinstance(v,dict): fail(f"invalid JSON object: {p}")
 return v,raw
def spec(p):
 t=p.read_text(encoding="utf-8"); c={}; s={}
 for n in ("background","surface","primary_text","secondary_text","accent","divider"):
  m=re.search(rf"^\s*-\s*{n}:\s*(#[0-9A-Fa-f]{{6}})",t,re.M)
  if m:c[n]=m.group(1)
 for n in ("kicker","body","caption"):
  m=re.search(rf"^\s*-\s*{n}:\s*(\d+)\s*$",t,re.M)
  if not m: fail(f"spec_lock missing typography.{n}")
  s[n]=int(m.group(1))
 c.setdefault("surface","#12131A"); c.setdefault("divider","#23242E")
 m=re.search(r"^\s*-\s*font_family:\s*(.+?)\s*$",t,re.M)
 if not m: fail("spec_lock missing typography.font_family")
 return c,s,m.group(1).strip()
def validate(plan,raw,intent):
 if plan.get("schema")!="ppt-studio-slide-plan/v1" or intent.get("schema")!="ppt-studio-layout-intent/v1":fail("unsupported schema")
 if intent.get("source_plan_sha256")!=hashlib.sha256(raw).hexdigest():fail("source_plan_sha256 mismatch")
 slides,intents=plan.get("slides"),intent.get("slides")
 if not isinstance(slides,list) or not isinstance(intents,list) or len(slides)!=len(intents):fail("plan and intent slides mismatch")
 out=[]
 for slide,item in zip(slides,intents):
  if item.get("layout")!="comparison-table":continue
  blocks=slide.get("blocks",[])
  if slide.get("kind")!="content" or len(blocks)!=1 or blocks[0].get("type")!="comparison-table":fail("comparison-table requires exactly one table block")
  b=blocks[0]; h=b.get("headers"); rows=b.get("rows")
  if not isinstance(h,list) or len(h)!=2:fail("comparison table requires exactly 2 columns")
  if not isinstance(rows,list) or not 2<=len(rows)<=4 or any(not isinstance(r,list) or len(r)!=2 for r in rows):fail("comparison table requires 2-4 data rows")
  if any(not isinstance(x,str) or not x.strip() or len(x)>24 for x in h+sum(rows,[])):fail("comparison table cell exceeds v1 single-line budget")
  if len(slide.get("title",""))>28:fail("comparison table title exceeds v1 single-line budget")
  out.append({"id":slide["id"],"title":slide.get("title",""),"headers":h,"rows":rows})
 if not out:fail("no comparison-table slides found")
 return out
def render(x,total,c,s,font):
 font=escape(font,{'"':'&quot;'}); left=80; mid=640; right=1200; y=230; row=70; lines=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',f'  <g id="background"><rect x="0" y="0" width="1280" height="720" fill="{c["background"]}"/></g>',f'  <g id="page-kicker"><text x="80" y="92" fill="{c["accent"]}" font-family="{font}" font-size="{s["kicker"]}">COMPARE / {x["id"]}</text></g>',f'  <g id="table-title"><text x="80" y="170" fill="{c["primary_text"]}" font-family="{font}" font-size="{s["body"]}">{escape(x["title"])}</text></g>',f'  <g id="comparison-table"><rect x="80" y="200" width="1120" height="{row*(len(x["rows"])+1)}" fill="{c["surface"]}"/><line x1="640" y1="200" x2="640" y2="{200+row*(len(x["rows"])+1)}" stroke="{c["divider"]}"/>']
 for i in range(len(x["rows"])+2): lines.append(f'    <line x1="80" y1="{200+i*row}" x2="1200" y2="{200+i*row}" stroke="{c["divider"]}"/>')
 lines.append(f'    <text x="{left+24}" y="{200+44}" fill="{c["accent"]}" font-family="{font}" font-size="{s["body"]}">{escape(x["headers"][0])}</text><text x="{mid+24}" y="{200+44}" fill="{c["accent"]}" font-family="{font}" font-size="{s["body"]}">{escape(x["headers"][1])}</text>')
 for i,r in enumerate(x["rows"],1): lines.append(f'    <text x="{left+24}" y="{200+i*row+44}" fill="{c["primary_text"]}" font-family="{font}" font-size="{s["body"]}">{escape(r[0])}</text><text x="{mid+24}" y="{200+i*row+44}" fill="{c["primary_text"]}" font-family="{font}" font-size="{s["body"]}">{escape(r[1])}</text>')
 lines.extend(['  </g>',f'  <g id="footer"><line x1="80" y1="608" x2="1200" y2="608" stroke="{c["accent"]}"/><text x="1200" y="648" text-anchor="end" fill="{c["secondary_text"]}" font-family="{font}" font-size="{s["caption"]}">{x["id"]} / {total:02d}</text></g>','</svg>','']); return "\n".join(lines)
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument("plan",type=Path);p.add_argument("intent",type=Path);p.add_argument("--spec",required=True,type=Path);p.add_argument("-o",required=True,type=Path);a=p.parse_args(argv);plan,raw=load(a.plan);intent,_=load(a.intent); xs=validate(plan,raw,intent);c,s,f=spec(a.spec);a.o.mkdir(parents=True,exist_ok=True)
 for x in xs:(a.o/f'{x["id"]}_comparison_table.svg').write_text(render(x,len(plan["slides"]),c,s,f),encoding="utf-8")
 print(f"COMPARISON_TABLE_SVG_WRITTEN slides={','.join(x['id'] for x in xs)} layout=comparison-table")
if __name__=="__main__":
 try:main()
 except (ValueError,OSError,json.JSONDecodeError) as e:print(f"ERROR: {e}",file=sys.stderr);raise SystemExit(2)
