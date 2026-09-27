#!/usr/bin/env python3
import argparse, hashlib, json, re
from pathlib import Path
from xml.sax.saxutils import escape

def main():
    p=argparse.ArgumentParser(); p.add_argument("plan"); p.add_argument("intent"); p.add_argument("--spec",required=True); p.add_argument("-o",required=True); a=p.parse_args()
    plan=json.loads(Path(a.plan).read_text()); raw=Path(a.plan).read_bytes(); intent=json.loads(Path(a.intent).read_text())
    if intent.get("source_plan_sha256") != hashlib.sha256(raw).hexdigest(): raise ValueError("source_plan_sha256 mismatch")
    out=Path(a.o); out.mkdir(parents=True,exist_ok=True); slides={x["id"]:x for x in plan["slides"]}
    for item in intent["slides"]:
        if item["layout"] != "swimlane-handoff": continue
        slide=slides[item["id"]]; block=slide["blocks"][0]; rows=block["rows"]; owners=block["owners"]; lane=1120/len(owners); xs=[80+i*lane for i in range(len(owners))]
        L=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"><rect width="1280" height="720" fill="#0B0C10"/>',f'<text x="80" y="132" fill="#F4F5F7" font-family="sans-serif" font-size="32">{escape(slide["title"])}</text>']
        for x,o in zip(xs,owners): L.append(f'<text x="{x+lane/2:.1f}" y="196" text-anchor="middle" fill="#A9ADBA" font-family="sans-serif" font-size="16">{escape(o)}</text>')
        centers=[]
        for i,row in enumerate(rows):
            x=xs[owners.index(row[1])]+22; y=230+i*86; w=lane-44; centers.append((x+w/2,y+64)); L += [f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="64" rx="8" fill="#12131A" stroke="#23242E"/>',f'<text x="{x+14:.1f}" y="{y+25}" fill="#7AA2F7" font-family="sans-serif" font-size="16">{escape(row[0])}</text>',f'<text x="{x+14:.1f}" y="{y+48}" fill="#F4F5F7" font-family="sans-serif" font-size="16">{escape(row[2])}</text>']
        for (x1,y1),(x2,y2) in zip(centers,centers[1:]): L.append(f'<path d="M {x1:.1f} {y1:.1f} C {x1:.1f} {y1+25:.1f}, {x2:.1f} {y2-25:.1f}, {x2:.1f} {y2:.1f}" fill="none" stroke="#7AA2F7"/>')
        L += ['<line x1="80" y1="650" x2="1200" y2="650" stroke="#7AA2F7"/>','</svg>','']; (out/f'{slide["id"]}_swimlane_handoff.svg').write_text("\n".join(L))
    print("SWIMLANE_HANDOFF_SVG_WRITTEN slides=02 layout=swimlane-handoff")
if __name__=="__main__":
    try: main()
    except Exception as e: print(f"ERROR: {e}"); raise SystemExit(2)
