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
def validate(plan_path,output_path,plan,raw,intent):
    if plan.get("schema")!="ppt-studio-slide-plan/v1" or intent.get("schema")!="ppt-studio-layout-intent/v1": fail("unsupported schema")
    if intent.get("source_plan_sha256")!=hashlib.sha256(raw).hexdigest(): fail("source_plan_sha256 mismatch")
    out=[]
    for slide,item in zip(plan.get("slides",[]),intent.get("slides",[])):
        if item.get("layout")!="image-comparison": continue
        blocks=slide.get("blocks",[]); images=[b for b in blocks if b.get("type")=="image"]; paragraphs=[b for b in blocks if b.get("type")=="paragraph"]
        if slide.get("kind")!="content" or len(images)!=2 or len(paragraphs)>1 or len(blocks)!=len(images)+len(paragraphs): fail("image-comparison requires exactly 2 images and 0-1 paragraph")
        if any(not isinstance(b.get("alt"),str) or not b["alt"].strip() for b in images): fail("image captions must be non-empty")
        paths=[b.get("path") for b in images]
        if len(set(paths))!=2: fail("image paths must be distinct in v1")
        assets=[]
        for index,block in enumerate(images,1):
            suffix=Path(block.get("path","")).suffix.lower()
            if suffix not in {".png",".jpg",".jpeg"}: fail("image-comparison requires PNG/JPG/JPEG")
            asset=output_path/"assets"/f'{slide["id"]}_image_{index}{suffix}'
            if asset.is_symlink() or not asset.is_file(): fail(f"materialized image asset missing: {asset.name}")
            assets.append(f"assets/{asset.name}")
        if len(slide.get("title",""))>28 or any(len(b.get("text",""))>72 for b in paragraphs): fail("image-comparison text exceeds v1 budget")
        out.append({"id":slide["id"],"title":slide.get("title",""),"captions":[b["alt"] for b in images],"paths":assets,"text":paragraphs[0].get("text","") if paragraphs else ""})
    if not out: fail("no image-comparison slides found")
    return out
def render(x,total,c,s,font):
    body=f'<text x="80" y="220" fill="{c["primary_text"]}" font-family="{escape(font)}" font-size="{s["body"]}">{escape(x["text"])}</text>' if x["text"] else ''
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',f'<rect width="1280" height="720" fill="{c["background"]}"/>',f'<text x="80" y="92" fill="{c["accent"]}" font-family="{escape(font)}" font-size="{s["kicker"]}">IMAGE COMPARISON / {x["id"]}</text>',f'<text x="80" y="160" fill="{c["primary_text"]}" font-family="{escape(font)}" font-size="{s["body"]}">{escape(x["title"])}</text>',body]
    for i,(xpos,path,caption) in enumerate(zip((80,660),x["paths"],x["captions"]),1):
        parts += [f'<rect x="{xpos}" y="270" width="540" height="280" rx="8" fill="{c["surface"]}" stroke="{c["divider"]}"/>',f'<image x="{xpos+20}" y="290" width="500" height="230" href="{escape(path)}" preserveAspectRatio="xMidYMid meet"/>',f'<text x="{xpos+20}" y="585" fill="{c["secondary_text"]}" font-family="{escape(font)}" font-size="{s["caption"]}">{escape(caption)}</text>']
    parts += [f'<line x1="80" y1="620" x2="1200" y2="620" stroke="{c["accent"]}"/>',f'<text x="1200" y="660" text-anchor="end" fill="{c["secondary_text"]}" font-family="{escape(font)}" font-size="{s["caption"]}">{x["id"]} / {total:02d}</text>','</svg>','']
    return "\n".join(parts)
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("plan",type=Path); p.add_argument("intent",type=Path); p.add_argument("--spec",required=True,type=Path); p.add_argument("-o",required=True,type=Path); a=p.parse_args(argv)
    plan,raw=load(a.plan); intent,_=load(a.intent); xs=validate(a.plan,a.o,plan,raw,intent); c,s,f=spec(a.spec); a.o.mkdir(parents=True,exist_ok=True)
    for x in xs: (a.o/f'{x["id"]}_image_comparison.svg').write_text(render(x,len(plan["slides"]),c,s,f),encoding="utf-8")
    print(f"IMAGE_COMPARISON_SVG_WRITTEN slides={','.join(x['id'] for x in xs)} layout=image-comparison")
if __name__=="__main__":
    try: main()
    except (ValueError,OSError,json.JSONDecodeError) as exc: print(f"ERROR: {exc}",file=__import__('sys').stderr); raise SystemExit(2)
