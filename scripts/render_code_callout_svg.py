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
    text=path.read_text(encoding="utf-8"); colors={}; sizes={}
    for name in ("background","surface","primary_text","secondary_text","accent","divider"):
        m=re.search(rf"^\s*-\s*{name}:\s*(#[0-9A-Fa-f]{{6}})",text,re.M)
        if m: colors[name]=m.group(1)
    colors.setdefault("background","#0B0C10"); colors.setdefault("surface","#12131A"); colors.setdefault("divider","#23242E")
    for name in ("kicker","body","caption"):
        m=re.search(rf"^\s*-\s*{name}:\s*(\d+)\s*$",text,re.M)
        if not m: fail(f"spec_lock missing typography.{name}")
        sizes[name]=int(m.group(1))
    m=re.search(r"^\s*-\s*font_family:\s*(.+?)\s*$",text,re.M)
    if not m: fail("spec_lock missing typography.font_family")
    return colors,sizes,m.group(1).strip()
def width(text): return sum(2 if ord(ch)>127 else 1 for ch in text)
def validate(plan_path, output_path, plan, raw, intent):
    if plan.get("schema")!="ppt-studio-slide-plan/v1" or intent.get("schema")!="ppt-studio-layout-intent/v1": fail("unsupported schema")
    if intent.get("source_plan_sha256")!=hashlib.sha256(raw).hexdigest(): fail("source_plan_sha256 mismatch")
    out=[]
    for slide,item in zip(plan.get("slides",[]),intent.get("slides",[])):
        if item.get("layout")!="code-callout": continue
        blocks=slide.get("blocks",[]); codes=[b for b in blocks if b.get("type")=="code"]; paragraphs=[b for b in blocks if b.get("type")=="paragraph"]
        if slide.get("kind")!="content" or len(codes)!=1 or len(paragraphs)>1 or len(blocks)!=len(codes)+len(paragraphs): fail("code-callout requires exactly 1 code block and 0-1 paragraph")
        block=codes[0]; lines=block.get("lines"); language=block.get("language","")
        if not 2<=len(lines or [])<=8 or any(not isinstance(line,str) or not line.strip() for line in lines): fail("code-callout requires 2-8 non-empty code lines")
        if language and language not in {"python","bash","json","typescript","sql"}: fail("unsupported code language")
        if len(slide.get("title",""))>28 or (paragraphs and len(paragraphs[0].get("text",""))>44) or len(language)>16 or any(width(line)>58 for line in lines): fail("code-callout text exceeds v1 budget")
        out.append({"id":slide["id"],"title":slide.get("title",""),"intro":paragraphs[0].get("text","") if paragraphs else "","language":language.upper() or "CODE","lines":lines})
    if not out: fail("no code-callout slides found")
    return out
def render(x,total,c,s,font):
    intro=f'<text x="80" y="218" fill="{c["secondary_text"]}" font-family="{escape(font)}" font-size="{s["caption"]}">{escape(x["intro"])}</text>' if x["intro"] else ''
    code_y=300 if x["intro"] else 260; label_y=code_y+38
    code='\n'.join(f'<text xml:space="preserve" x="112" y="{label_y+42+i*38}" fill="{c["primary_text"]}" font-family="{escape(font)}" font-size="{s["caption"]}">{escape(line)}</text>' for i,line in enumerate(x["lines"]))
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',f'<rect width="1280" height="720" fill="{c["background"]}"/>',f'<text x="80" y="92" fill="{c["accent"]}" font-family="{escape(font)}" font-size="{s["kicker"]}">TOOL INVOCATION / {x["id"]}</text>',f'<text x="80" y="170" fill="{c["primary_text"]}" font-family="{escape(font)}" font-size="{s["body"]}">{escape(x["title"])}</text>',intro,f'<rect x="80" y="{code_y-22}" width="1120" height="{len(x["lines"])*38+92}" rx="8" fill="{c["surface"]}" stroke="{c["divider"]}"/>',f'<text x="112" y="{label_y}" fill="{c["accent"]}" font-family="{escape(font)}" font-size="{s["caption"]}">{escape(x["language"])}</text>',code,f'<line x1="80" y1="608" x2="1200" y2="608" stroke="{c["accent"]}"/>',f'<text x="1200" y="648" text-anchor="end" fill="{c["secondary_text"]}" font-family="{escape(font)}" font-size="{s["caption"]}">{x["id"]} / {total:02d}</text>','</svg>',''])
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("plan",type=Path); p.add_argument("intent",type=Path); p.add_argument("--spec",required=True,type=Path); p.add_argument("-o",required=True,type=Path); a=p.parse_args(argv)
    plan,raw=load(a.plan); intent,_=load(a.intent); xs=validate(a.plan,a.o,plan,raw,intent); c,s,f=spec(a.spec); a.o.mkdir(parents=True,exist_ok=True)
    for x in xs: (a.o/f'{x["id"]}_code_callout.svg').write_text(render(x,len(plan["slides"]),c,s,f),encoding="utf-8")
    print(f"CODE_CALLOUT_SVG_WRITTEN slides={','.join(x['id'] for x in xs)} layout=code-callout")
if __name__=="__main__":
    try: main()
    except (ValueError,OSError,json.JSONDecodeError) as exc: print(f"ERROR: {exc}",file=__import__('sys').stderr); raise SystemExit(2)
