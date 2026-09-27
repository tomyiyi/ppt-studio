from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
from xml.sax.saxutils import escape
def fail(m): raise ValueError(m)
def load(p):
    raw=p.read_bytes(); v=json.loads(raw)
    if not isinstance(v,dict): fail('invalid JSON object')
    return v,raw
def spec(p):
    t=p.read_text(encoding='utf-8'); c={}; s={}
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
    if plan.get('schema')!='ppt-studio-slide-plan/v1' or intent.get('schema')!='ppt-studio-layout-intent/v1':fail('unsupported schema')
    if intent.get('source_plan_sha256')!=hashlib.sha256(raw).hexdigest():fail('source_plan_sha256 mismatch')
    out=[]
    for slide,item in zip(plan.get('slides',[]),intent.get('slides',[])):
        if item.get('layout')!='milestone-timeline':continue
        blocks=slide.get('blocks',[]); ms=[b for b in blocks if b.get('type')=='milestone-list']; ps=[b for b in blocks if b.get('type')=='paragraph']
        if slide.get('kind')!='content' or len(ms)!=1 or len(ps)>1 or len(blocks)!=len(ms)+len(ps):fail('milestone-timeline requires exactly 1 milestone-list and 0-1 paragraph')
        items=ms[0].get('items',[])
        if not 3<=len(items)<=5:fail('milestone list requires 3-5 items in v1')
        if len(slide.get('title',''))>28 or (ps and len(ps[0].get('text',''))>44):fail('milestone-timeline text exceeds v1 budget')
        for x in items:
            if not isinstance(x,dict) or not re.fullmatch(r'\d{4}(?:-\d{2})?(?:-\d{2})?',x.get('date','')) or not x.get('text'):fail('invalid milestone item')
            if len(x['text'])>34:fail('milestone text exceeds v1 budget')
        out.append({'id':slide['id'],'title':slide.get('title',''),'intro':ps[0].get('text','') if ps else '','items':items})
    if not out:fail('no milestone-timeline slides found')
    return out
def render(x,total,c,s,font):
    intro=f'<text x="80" y="218" fill="{c["secondary_text"]}" font-family="{escape(font)}" font-size="{s["caption"]}">{escape(x["intro"])}</text>' if x['intro'] else ''
    y0=315; gap=80; line=f'<line x1="150" y1="{y0-18}" x2="150" y2="{y0-18+gap*(len(x["items"])-1)}" stroke="{c["accent"]}" stroke-width="3"/>'
    rows=[line]
    for i,m in enumerate(x['items']):
        y=y0+i*gap; rows += [f'<circle cx="150" cy="{y-18}" r="9" fill="{c["accent"]}"/>',f'<text x="190" y="{y-18}" fill="{c["accent"]}" font-family="{escape(font)}" font-size="{s["caption"]}">{escape(m["date"])}</text>',f'<text x="340" y="{y-18}" fill="{c["primary_text"]}" font-family="{escape(font)}" font-size="{s["caption"]}">{escape(m["text"])}</text>']
    return '\n'.join([f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',f'<rect width="1280" height="720" fill="{c["background"]}"/>',f'<text x="80" y="92" fill="{c["accent"]}" font-family="{escape(font)}" font-size="{s["kicker"]}">MILESTONE TIMELINE / {x["id"]}</text>',f'<text x="80" y="170" fill="{c["primary_text"]}" font-family="{escape(font)}" font-size="{s["body"]}">{escape(x["title"])}</text>',intro,*rows,f'<line x1="80" y1="608" x2="1200" y2="608" stroke="{c["accent"]}"/>',f'<text x="1200" y="648" text-anchor="end" fill="{c["secondary_text"]}" font-family="{escape(font)}" font-size="{s["caption"]}">{x["id"]} / {total:02d}</text>','</svg>',''])
def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('plan',type=Path);p.add_argument('intent',type=Path);p.add_argument('--spec',required=True,type=Path);p.add_argument('-o',required=True,type=Path);a=p.parse_args(argv)
    plan,raw=load(a.plan);intent,_=load(a.intent);xs=validate(plan,raw,intent);c,s,f=spec(a.spec);a.o.mkdir(parents=True,exist_ok=True)
    for x in xs:(a.o/f'{x["id"]}_milestone_timeline.svg').write_text(render(x,len(plan['slides']),c,s,f),encoding='utf-8')
    print(f'MILESTONE_TIMELINE_SVG_WRITTEN slides={",".join(x["id"] for x in xs)} layout=milestone-timeline')
if __name__=='__main__':
    try:main()
    except (ValueError,OSError,json.JSONDecodeError) as e: print(f'ERROR: {e}',file=__import__('sys').stderr);raise SystemExit(2)
