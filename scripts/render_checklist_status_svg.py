from __future__ import annotations
import argparse,hashlib,json,re
from pathlib import Path
from xml.sax.saxutils import escape
def fail(m): raise ValueError(m)
def load(p):
 raw=p.read_bytes(); v=json.loads(raw); return v,raw
def spec(p):
 t=p.read_text(); c={}; s={}
 for n in ('background','surface','primary_text','secondary_text','accent','divider'):
  m=re.search(rf'^\s*-\s*{n}:\s*(#[0-9A-Fa-f]{{6}})',t,re.M)
  if m:c[n]=m.group(1)
 c.setdefault('background','#0B0C10');c.setdefault('surface','#12131A');c.setdefault('divider','#23242E')
 for n in ('kicker','body','caption'):
  m=re.search(rf'^\s*-\s*{n}:\s*(\d+)\s*$',t,re.M)
  if not m:fail(f'spec_lock missing typography.{n}')
  s[n]=int(m.group(1))
 m=re.search(r'^\s*-\s*font_family:\s*(.+?)\s*$',t,re.M)
 if not m:fail('spec_lock missing typography.font_family')
 return c,s,m.group(1).strip()
def validate(plan,raw,intent):
 if intent.get('source_plan_sha256')!=hashlib.sha256(raw).hexdigest():fail('source_plan_sha256 mismatch')
 out=[]
 for slide,item in zip(plan['slides'],intent['slides']):
  if item.get('layout')!='checklist-status':continue
  bs=slide.get('blocks',[]); ls=[b for b in bs if b.get('type')=='task-list']; ps=[b for b in bs if b.get('type')=='paragraph']
  if slide.get('kind')!='content' or len(ls)!=1 or len(ps)>1 or len(bs)!=len(ls)+len(ps):fail('checklist-status requires exactly 1 task-list and 0-1 paragraph')
  items=ls[0].get('items',[])
  if not 3<=len(items)<=6:fail('task list requires 3-6 items in v1')
  if len(slide.get('title',''))>28 or (ps and len(ps[0].get('text',''))>44):fail('bar-chart text exceeds v1 budget')
  for x in items:
   if not x.get('text'):fail('task text must be non-empty')
   if len(x['text'])>42:fail('task text exceeds v1 budget')
  out.append({'id':slide['id'],'title':slide['title'],'intro':ps[0]['text'] if ps else '','items':items})
 return out
def main():
 p=argparse.ArgumentParser();p.add_argument('plan',type=Path);p.add_argument('intent',type=Path);p.add_argument('--spec',required=True,type=Path);p.add_argument('-o',required=True,type=Path);a=p.parse_args()
 plan,raw=load(a.plan);intent,_=load(a.intent);xs=validate(plan,raw,intent);c,s,f=spec(a.spec);a.o.mkdir(parents=True,exist_ok=True)
 for x in xs:
  rows=[]
  for i,it in enumerate(x['items']):
   y=270+i*55; mark='✓' if it['checked'] else ''; rows += [f'<rect x="80" y="{y}" width="28" height="28" rx="4" fill="{c["surface"]}" stroke="{c["accent"]}"/>',f'<text x="87" y="{y+22}" fill="{c["accent"]}" font-family="{escape(f)}" font-size="{s["caption"]}">{mark}</text>',f'<text x="140" y="{y+22}" fill="{c["primary_text"]}" font-family="{escape(f)}" font-size="{s["caption"]}">{escape(it["text"])}</text>']
  intro=f'<text x="80" y="218" fill="{c["secondary_text"]}" font-family="{escape(f)}" font-size="{s["caption"]}">{escape(x["intro"])}</text>' if x['intro'] else ''
  svg='\n'.join([f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',f'<rect width="1280" height="720" fill="{c["background"]}"/>',f'<text x="80" y="92" fill="{c["accent"]}" font-family="{escape(f)}" font-size="{s["kicker"]}">ARCHITECTURE STACK / {x["id"]}</text>',f'<text x="80" y="170" fill="{c["primary_text"]}" font-family="{escape(f)}" font-size="{s["body"]}">{escape(x["title"])}</text>',intro,*rows,f'<line x1="80" y1="608" x2="1200" y2="608" stroke="{c["accent"]}"/>',f'<text x="1200" y="648" text-anchor="end" fill="{c["secondary_text"]}" font-family="{escape(f)}" font-size="{s["caption"]}">{x["id"]} / {len(plan["slides"]):02d}</text>','</svg>',''])
  (a.o/f'{x["id"]}_checklist_status.svg').write_text(svg.replace('ARCHITECTURE STACK','CHECKLIST STATUS'))
 print(f'CHECKLIST_STATUS_SVG_WRITTEN slides={",".join(x["id"] for x in xs)} layout=checklist-status')
if __name__=='__main__':
 try:main()
 except Exception as e:print(f'ERROR: {e}',file=__import__('sys').stderr);raise SystemExit(2)
