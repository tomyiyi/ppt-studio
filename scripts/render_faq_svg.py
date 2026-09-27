#!/usr/bin/env python3
import argparse,hashlib,json
from pathlib import Path
from xml.sax.saxutils import escape
def main():
 p=argparse.ArgumentParser();p.add_argument('plan');p.add_argument('intent');p.add_argument('--spec');p.add_argument('-o','--output',required=True);a=p.parse_args(); plan=json.loads(Path(a.plan).read_text()); intent=json.loads(Path(a.intent).read_text());
 if intent['source_plan_sha256']!=hashlib.sha256(Path(a.plan).read_bytes()).hexdigest(): raise SystemExit('source_plan_sha256 mismatch')
 s=next(x for x in plan['slides'] if x['id']==next(y['id'] for y in intent['slides'] if y['layout']=='faq')); b=next(x for x in s['blocks'] if x['type']=='faq'); items=b['items']
 if not 2<=len(items)<=4: raise SystemExit('faq block requires 2-4 Q/A pairs in v1')
 def t(x,y,z,size,fill='#F4F7FA',anchor='start'): return f'<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="{size}px" fill="{fill}" text-anchor="{anchor}">{escape(z)}</text>'
 out=['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720"><rect width="1280" height="720" fill="#101820"/>',t(80,92,'Frequently Asked Questions',44,'#F4F7FA'),t(80,130,'Questions, answers, and the evidence behind the workflow',20,'#AAB7C4')]
 y=205; step=92 if len(items)>=4 else 112
 for q in items:
  if len(q['question'])>30 or len(q['answer'])>44: raise SystemExit('faq text budget exceeded')
  out += [f'<rect x="80" y="{y-34}" width="1120" height="74" rx="12" fill="#172631" stroke="#334654"/>',t(108,y,'Q',20,'#57D6B5'),t(148,y,q['question'],20),t(108,y+30,'A',20,'#57D6B5'),t(148,y+30,q['answer'],16,'#AAB7C4')]; y+=step
 out += [f'<line x1="80" y1="620" x2="1200" y2="620" stroke="#334654"/>',t(80,660,f'{len(items)} Q/A pairs · fixed order · no interaction',16,'#AAB7C4'),'</svg>']; o=Path(a.output);o.mkdir(parents=True,exist_ok=True);(o/'02_faq.svg').write_text(''.join(out));print('FAQ_SVG_WRITTEN slides=02 layout=faq')
if __name__=='__main__': main()
