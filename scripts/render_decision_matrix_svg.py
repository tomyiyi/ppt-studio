#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from xml.sax.saxutils import escape

W,H=1280,720
def main():
    p=argparse.ArgumentParser(); p.add_argument('plan',type=Path); p.add_argument('intent',type=Path); p.add_argument('--spec',required=True,type=Path); p.add_argument('-o','--output',required=True,type=Path); a=p.parse_args()
    plan=json.loads(a.plan.read_text()); intent=json.loads(a.intent.read_text())
    if intent.get('source_plan_sha256') != hashlib.sha256(a.plan.read_bytes()).hexdigest(): raise SystemExit('source_plan_sha256 mismatch')
    item=next((x for x in intent['slides'] if x.get('layout')=='decision-matrix'),None)
    slide=next(x for x in plan['slides'] if x['id']==item['id']); block=next(x for x in slide['blocks'] if x['type']=='decision-matrix')
    rows=block['rows']; levels={'Low':0,'Medium':1,'High':2}; xs=[390,660,930]; ys=[300,410,520]
    surface='#101820'; primary='#F4F7FA'; secondary='#AAB7C4'; accent='#57D6B5'; divider='#334654'
    def t(x,y,s,size=20,fill=primary,anchor='middle',weight='400'): return f'<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="{size}px" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}">{escape(s)}</text>'
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"><rect width="{W}" height="{H}" fill="{surface}"/>']
    out += [t(80,92,'What Should We Build Next?',44,primary,'start','700'),t(80,130,'Decision matrix · impact × effort',20,secondary,'start')]
    out += [t(660,190,'Impact',20,secondary),'<text x="145" y="410" transform="rotate(-90 145 410)" font-family="Arial, sans-serif" font-size="20px" fill="'+secondary+'" text-anchor="middle">Effort</text>']
    for x,label in zip(xs,['Low','Medium','High']): out += [t(x,232,label,20,secondary),f'<line x1="{x}" y1="250" x2="{x}" y2="570" stroke="{divider}" stroke-width="2"/>']
    for y,label in zip(ys,['Low','Medium','High']): out += [t(270,y+7,label,20,secondary,'end'),f'<line x1="300" y1="{y}" x2="1020" y2="{y}" stroke="{divider}" stroke-width="2"/>']
    slots=[(-42,-20),(42,-20),(-42,20),(42,20)]; cells={}
    for option,impact,effort in rows: cells.setdefault((levels[impact],levels[effort]),[]).append(option)
    for (ix,ey),opts in cells.items():
        for n,option in enumerate(opts):
            dx,dy=slots[n]; x,y=xs[ix]+dx,ys[ey]+dy; out += [f'<rect x="{x-78}" y="{y-19}" width="156" height="38" rx="19" fill="{accent}" fill-opacity="0.16" stroke="{accent}" stroke-width="2"/>',t(x,y+6,option[:22],16,primary)]
    out += [f'<line x1="80" y1="620" x2="1200" y2="620" stroke="{divider}"/>',t(80,660,f'{len(rows)} options · input order preserved · no ranking applied',16,secondary,'start'),'</svg>']
    outdir=a.output; outdir.mkdir(parents=True,exist_ok=True); path=outdir/'02_decision_matrix.svg'; path.write_text(''.join(out)); print('DECISION_MATRIX_SVG_WRITTEN slides=02 layout=decision-matrix')
if __name__=='__main__': main()
