import argparse, hashlib, json, re
from pathlib import Path
from xml.sax.saxutils import escape

def main():
    p=argparse.ArgumentParser(); p.add_argument('plan'); p.add_argument('intent'); p.add_argument('--spec',required=True); p.add_argument('-o',required=True); a=p.parse_args()
    plan=json.loads(Path(a.plan).read_text()); raw=Path(a.plan).read_bytes(); intent=json.loads(Path(a.intent).read_text())
    if intent.get('source_plan_sha256')!=hashlib.sha256(raw).hexdigest(): raise ValueError('source_plan_sha256 mismatch')
    text=Path(a.spec).read_text(); colors={'background':'#0B0C10','surface':'#12131A','primary_text':'#F4F5F7','secondary_text':'#A9ADBA','accent':'#7AA2F7','divider':'#23242E'}; sizes={}
    for n in ('background','surface','primary_text','secondary_text','accent','divider'):
        m=re.search(rf'^\s*-\s*{n}:\s*(#[0-9A-Fa-f]{{6}})',text,re.M)
        if m: colors[n]=m.group(1)
    for n in ('kicker','body','caption'): sizes[n]=int(re.search(rf'^\s*-\s*{n}:\s*(\d+)\s*$',text,re.M).group(1))
    font=re.search(r'^\s*-\s*font_family:\s*(.+?)\s*$',text,re.M).group(1).strip(); out=Path(a.o); out.mkdir(parents=True,exist_ok=True)
    for slide,item in zip(plan['slides'],intent['slides']):
        if item['layout']!='hierarchy-tree': continue
        trees=[b for b in slide['blocks'] if b.get('type')=='hierarchy-tree']; ps=[b for b in slide['blocks'] if b.get('type')=='paragraph']; t=trees[0]; ch=t['children']; slots={2:[360,920],3:[240,640,1040],4:[180,485,790,1095]}[len(ch)]
        L=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"><rect width="1280" height="720" fill="{colors["background"]}"/>',f'<text x="80" y="92" fill="{colors["accent"]}" font-family="{escape(font)}" font-size="{sizes["kicker"]}">HIERARCHY TREE / {slide["id"]}</text>',f'<text x="80" y="170" fill="{colors["primary_text"]}" font-family="{escape(font)}" font-size="{sizes["body"]}">{escape(slide["title"])}</text>']
        if ps: L.append(f'<text x="80" y="218" fill="{colors["secondary_text"]}" font-family="{escape(font)}" font-size="{sizes["caption"]}">{escape(ps[0]["text"])}</text>')
        L += [f'<rect x="500" y="260" width="280" height="72" rx="8" fill="{colors["surface"]}" stroke="{colors["accent"]}"/>',f'<text x="640" y="304" text-anchor="middle" fill="{colors["primary_text"]}" font-family="{escape(font)}" font-size="{sizes["caption"]}">{escape(t["root"])}</text>']
        for x,c in zip(slots,ch): L += [f'<path d="M 640 332 V 382 H {x} V 420" fill="none" stroke="{colors["accent"]}"/>',f'<rect x="{x-110}" y="420" width="220" height="72" rx="8" fill="{colors["surface"]}" stroke="{colors["divider"]}"/>',f'<text x="{x}" y="464" text-anchor="middle" fill="{colors["primary_text"]}" font-family="{escape(font)}" font-size="{sizes["caption"]}">{escape(c)}</text>']
        L += [f'<line x1="80" y1="608" x2="1200" y2="608" stroke="{colors["accent"]}"/>','</svg>','']; (out/f'{slide["id"]}_hierarchy_tree.svg').write_text('\n'.join(L))
    print('HIERARCHY_TREE_SVG_WRITTEN slides=02 layout=hierarchy-tree')
if __name__=='__main__':
    try: main()
    except Exception as e: print(f'ERROR: {e}'); raise SystemExit(2)
