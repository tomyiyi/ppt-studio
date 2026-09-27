from __future__ import annotations
import argparse, base64, hashlib, json, re
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
        if item.get("layout")!="image-callout": continue
        blocks=slide.get("blocks",[]); images=[b for b in blocks if b.get("type")=="image"]; paragraphs=[b for b in blocks if b.get("type")=="paragraph"]
        if slide.get("kind")!="content" or len(images)!=1 or len(paragraphs)>1 or len(blocks)!=len(images)+len(paragraphs): fail("image-callout requires exactly 1 image and 0-1 paragraph")
        block=images[0]; suffix=Path(block.get("path","")).suffix.lower()
        if suffix not in {".png",".jpg",".jpeg"} or not block.get("path"): fail("image-callout requires PNG/JPG/JPEG")
        asset=output_path/"assets"/f'{slide["id"]}_image_callout{suffix}'
        if asset.is_symlink() or not asset.is_file(): fail(f"materialized image asset missing: {asset.name}")
        if len(slide.get("title",""))>28 or any(len(b.get("text",""))>72 for b in paragraphs): fail("image-callout text exceeds v1 budget")
        mime={".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg"}[suffix]
        out.append({"id":slide["id"],"title":slide.get("title",""),"alt":block["alt"],"path":f"data:{mime};base64,{base64.b64encode(asset.read_bytes()).decode('ascii')}","text":paragraphs[0].get("text","") if paragraphs else ""})
    if not out: fail("no image-callout slides found")
    return out
def render(x,total,c,s,font):
    text=f'<text x="80" y="350" fill="{c["primary_text"]}" font-family="{escape(font)}" font-size="{s["body"]}">{escape(x["text"])}</text>' if x["text"] else ''
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',f'<rect width="1280" height="720" fill="{c["background"]}"/>',f'<text x="80" y="92" fill="{c["accent"]}" font-family="{escape(font)}" font-size="{s["kicker"]}">MEDIA CALLOUT / {x["id"]}</text>',f'<text x="80" y="170" fill="{c["primary_text"]}" font-family="{escape(font)}" font-size="{s["body"]}">{escape(x["title"])}</text>',f'<rect x="80" y="220" width="560" height="280" rx="8" fill="{c["surface"]}"/>',text,f'<rect x="700" y="190" width="480" height="340" rx="8" fill="{c["surface"]}" stroke="{c["divider"]}"/>',f'<image x="720" y="210" width="440" height="300" href="{escape(x["path"])}" preserveAspectRatio="xMidYMid meet"/>',f'<line x1="80" y1="608" x2="1200" y2="608" stroke="{c["accent"]}"/>',f'<text x="1200" y="648" text-anchor="end" fill="{c["secondary_text"]}" font-family="{escape(font)}" font-size="{s["caption"]}">{x["id"]} / {total:02d}</text>','</svg>',''])
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("plan",type=Path); p.add_argument("intent",type=Path); p.add_argument("--spec",required=True,type=Path); p.add_argument("-o",required=True,type=Path); a=p.parse_args(argv)
    plan,raw=load(a.plan); intent,_=load(a.intent); xs=validate(a.plan,a.o,plan,raw,intent); c,s,f=spec(a.spec); a.o.mkdir(parents=True,exist_ok=True)
    for x in xs: (a.o/f'{x["id"]}_image_callout.svg').write_text(render(x,len(plan["slides"]),c,s,f),encoding="utf-8")
    print(f"IMAGE_CALLOUT_SVG_WRITTEN slides={','.join(x['id'] for x in xs)} layout=image-callout")
if __name__=="__main__":
    try: main()
    except (ValueError,OSError,json.JSONDecodeError) as exc: print(f"ERROR: {exc}",file=__import__('sys').stderr); raise SystemExit(2)
