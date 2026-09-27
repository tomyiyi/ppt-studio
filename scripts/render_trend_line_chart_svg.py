#!/usr/bin/env python3
import argparse,hashlib,json
from pathlib import Path
from xml.sax.saxutils import escape
def main():
 p=argparse.ArgumentParser(); p.add_argument("plan"); p.add_argument("intent"); p.add_argument("--spec",required=True); p.add_argument("-o",required=True); a=p.parse_args()
 plan=json.loads(Path(a.plan).read_text()); raw=Path(a.plan).read_bytes(); intent=json.loads(Path(a.intent).read_text())
 if intent.get("source_plan_sha256")!=hashlib.sha256(raw).hexdigest(): raise ValueError("source_plan_sha256 mismatch")
 out=Path(a.o); out.mkdir(parents=True,exist_ok=True)
 for it in intent["slides"]:
  if it["layout"]!="trend-line-chart": continue
  slide=next(x for x in plan["slides"] if x["id"]==it["id"]); block=next(x for x in slide["blocks"] if x["type"]=="trend-series"); items=block["items"]; vals=[x["value"] for x in items]; lo,hi=min(vals),max(vals); left,right,top,bottom=140,1160,250,590; span=hi-lo
  pts=[]
  for i,x in enumerate(items):
   px=left+(right-left)*i/(len(items)-1); py=(top+bottom)/2 if span==0 else bottom-(x["value"]-lo)/(span)*(bottom-top); pts.append((px,py))
  path=" ".join(("M" if i==0 else "L")+f" {x:.1f} {y:.1f}" for i,(x,y) in enumerate(pts))
  L=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"><rect width="1280" height="720" fill="#0B0C10"/>',f'<text x="80" y="132" fill="#F4F5F7" font-family="sans-serif" font-size="32">{escape(slide["title"])}</text>',f'<path d="{path}" fill="none" stroke="#7AA2F7" stroke-width="3"/>']
  for (px,py),x in zip(pts,items): L += [f'<circle cx="{px:.1f}" cy="{py:.1f}" r="7" fill="#7AA2F7"/>',f'<text x="{px:.1f}" y="{py-16:.1f}" text-anchor="middle" fill="#F4F5F7" font-family="sans-serif" font-size="16">{x["value"]:g}</text>',f'<text x="{px:.1f}" y="630" text-anchor="middle" fill="#A9ADBA" font-family="sans-serif" font-size="16">{escape(x["period"])}</text>']
  L += ['<line x1="80" y1="650" x2="1200" y2="650" stroke="#7AA2F7"/>','</svg>','']; (out/f'{slide["id"]}_trend_line_chart.svg').write_text("\n".join(L))
 print("TREND_LINE_CHART_SVG_WRITTEN slides=02 layout=trend-line-chart")
if __name__=="__main__":
 try: main()
 except Exception as e: print(f"ERROR: {e}"); raise SystemExit(2)
