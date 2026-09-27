#!/usr/bin/env python3
import argparse, hashlib, json, re, sys
from pathlib import Path
from xml.sax.saxutils import escape

def fail(message): raise ValueError(message)
def load(path):
    raw=path.read_bytes(); value=json.loads(raw)
    if not isinstance(value,dict): fail('invalid JSON object')
    return value,raw
def spec(path):
    text=path.read_text(encoding='utf-8'); colors={}; sizes={}
    for name in ('background','surface','primary_text','secondary_text','accent','divider'):
        match=re.search(rf'^\s*-\s*{name}:\s*(#[0-9A-Fa-f]{{6}})',text,re.M)
        if match: colors[name]=match.group(1)
    for name in ('kicker','body','caption'):
        match=re.search(rf'^\s*-\s*{name}:\s*(\d+)\s*$',text,re.M)
        if not match: fail(f'spec_lock missing typography.{name}')
        sizes[name]=int(match.group(1))
    match=re.search(r'^\s*-\s*font_family:\s*(.+?)\s*$',text,re.M)
    if not match: fail('spec_lock missing typography.font_family')
    colors.setdefault('surface','#12131A'); colors.setdefault('divider','#23242E')
    return colors,sizes,match.group(1).strip()
def validate(plan,raw,intent):
    if intent.get('source_plan_sha256') != hashlib.sha256(raw).hexdigest(): fail('source_plan_sha256 mismatch')
    out=[]
    for slide,entry in zip(plan.get('slides',[]),intent.get('slides',[])):
        if entry.get('layout') != 'risk-register': continue
        blocks=slide.get('blocks',[])
        if slide.get('kind') != 'content' or len(blocks)!=1 or blocks[0].get('type')!='risk-register': fail('risk-register requires exactly one table block')
        block=blocks[0]; headers=block.get('headers'); rows=block.get('rows',[])
        if headers != ['Risk','Severity','Mitigation']: fail('risk-register header mismatch')
        if not 2<=len(rows)<=4 or any(len(row)!=3 for row in rows): fail('risk-register requires 2-4 data rows')
        if any(cell=='' or len(cell)>24 for cell in headers+sum(rows,[])): fail('risk-register cell exceeds v1 single-line budget')
        if any(row[1] not in {'Low','Medium','High'} for row in rows): fail('risk-register severity must be Low, Medium, or High')
        if len(slide.get('title',''))>28: fail('risk-register title exceeds v1 single-line budget')
        out.append({'id':slide['id'],'title':slide['title'],'headers':headers,'rows':rows})
    if not out: fail('no risk-register slides found')
    return out
def render(item,total,colors,sizes,font):
    font=escape(font); xs=[80,430,760]; row=70; bottom=200+row*(len(item['rows'])+1)
    lines=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',f'<g id="background"><rect width="1280" height="720" fill="{colors["background"]}"/></g>',f'<g id="page-kicker"><text x="80" y="92" fill="{colors["accent"]}" font-family="{font}" font-size="{sizes["kicker"]}">RISK REGISTER / {item["id"]}</text></g>',f'<g id="table-title"><text x="80" y="170" fill="{colors["primary_text"]}" font-family="{font}" font-size="{sizes["body"]}">{escape(item["title"])}</text></g>',f'<g id="risk-register"><rect x="80" y="200" width="1120" height="{row*(len(item["rows"])+1)}" fill="{colors["surface"]}"/>']
    for x in (430,760): lines.append(f'<line x1="{x}" y1="200" x2="{x}" y2="{bottom}" stroke="{colors["divider"]}"/>')
    for i in range(len(item['rows'])+2): lines.append(f'<line x1="80" y1="{200+i*row}" x2="1200" y2="{200+i*row}" stroke="{colors["divider"]}"/>')
    for x,header in zip(xs,item['headers']): lines.append(f'<text x="{x+24}" y="244" fill="{colors["accent"]}" font-family="{font}" font-size="{sizes["body"]}">{escape(header)}</text>')
    for i,rowdata in enumerate(item['rows'],1):
        for x,cell in zip(xs,rowdata): lines.append(f'<text x="{x+24}" y="{200+i*row+44}" fill="{colors["primary_text"]}" font-family="{font}" font-size="{sizes["body"]}">{escape(cell)}</text>')
    lines += [f'</g><g id="footer"><line x1="80" y1="608" x2="1200" y2="608" stroke="{colors["accent"]}"/><text x="1200" y="648" text-anchor="end" fill="{colors["secondary_text"]}" font-family="{font}" font-size="{sizes["caption"]}">{item["id"]} / {total:02d}</text></g></svg>','']
    return '\n'.join(lines)
def main():
    parser=argparse.ArgumentParser(); parser.add_argument('plan',type=Path); parser.add_argument('intent',type=Path); parser.add_argument('--spec',required=True,type=Path); parser.add_argument('-o',required=True,type=Path); args=parser.parse_args()
    plan,raw=load(args.plan); intent,_=load(args.intent); items=validate(plan,raw,intent); colors,sizes,font=spec(args.spec); args.o.mkdir(parents=True,exist_ok=True)
    for item in items: (args.o/f'{item["id"]}_risk_register.svg').write_text(render(item,len(plan['slides']),colors,sizes,font),encoding='utf-8')
    print(f'RISK_REGISTER_SVG_WRITTEN slides={",".join(x["id"] for x in items)} layout=risk-register')
if __name__=='__main__':
    try: main()
    except Exception as exc: print(f'ERROR: {exc}',file=sys.stderr); raise SystemExit(2)
