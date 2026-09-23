import os, re, sys, base64, mimetypes

src, out, title = sys.argv[1], sys.argv[2], sys.argv[3]

IMAGE_RE = re.compile(r'(<image\b[^>]*?\bhref=")([^"]+)(")')


def inline_images(t, svg_dir):
    """把 <image href="../images/x.png"> 内联成 data URI，让预览单文件自包含。"""
    def repl(m):
        href = m.group(2)
        if href.startswith('data:'):
            return m.group(0)
        p = os.path.normpath(os.path.join(svg_dir, href))
        if not os.path.exists(p):
            print(f"  [warn] 缺图 {href}")
            return m.group(0)
        mime = mimetypes.guess_type(p)[0] or 'image/png'
        with open(p, 'rb') as fh:
            b64 = base64.b64encode(fh.read()).decode('ascii')
        return f"{m.group(1)}data:{mime};base64,{b64}{m.group(3)}"
    return IMAGE_RE.sub(repl, t)


svgs = []
for f in sorted(os.listdir(src)):
    if f.endswith('.svg'):
        with open(os.path.join(src, f), encoding='utf-8') as fh:
            t = fh.read()
        t = re.sub(r'\s*<\?xml[^>]*\?>', '', t)
        t = inline_images(t, src)
        svgs.append(t)

slides = "\n".join(f'  <div class="slide{" active" if i==0 else ""}">{s}</div>' for i, s in enumerate(svgs))
n = len(svgs)

html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title}</title><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#05060a;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow:hidden}}
.stage{{width:100vw;height:100vh;display:flex;align-items:center;justify-content:center}}
.slide{{display:none;width:100vw;height:56.25vw;max-height:100vh;max-width:177.78vh}}
.slide.active{{display:block}}.slide svg{{width:100%;height:100%;display:block}}
.nav{{position:fixed;bottom:18px;right:22px;display:flex;gap:10px;z-index:50}}
.nav button{{background:rgba(18,19,26,.85);border:1px solid #23242E;color:#F7F7F9;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:13px;backdrop-filter:blur(6px)}}
.nav button:hover{{background:rgba(110,123,255,.3);border-color:#6E7BFF}}
.ind{{position:fixed;bottom:24px;left:22px;color:#5A5B66;font-size:12px;letter-spacing:2px}}
.hint{{position:fixed;top:14px;left:22px;color:#5A5B66;font-size:12px}}
</style></head><body><div class="stage">
{slides}
</div><div class="hint">← → 翻页 · F 全屏</div><div class="ind" id="ind">01 / {n:02d}</div>
<div class="nav"><button onclick="go(-1)">◀ 上一页</button><button onclick="go(1)">下一页 ▶</button></div>
<script>
let cur=0;const sl=document.querySelectorAll('.slide'),ind=document.getElementById('ind');
function show(i){{sl[cur].classList.remove('active');cur=(i+sl.length)%sl.length;sl[cur].classList.add('active');ind.textContent=String(cur+1).padStart(2,'0')+' / '+String(sl.length).padStart(2,'0');}}
function go(d){{show(cur+d);}}
window.addEventListener('keydown',e=>{{if(e.key==='ArrowRight'||e.key===' '){{e.preventDefault();go(1);}}if(e.key==='ArrowLeft'){{e.preventDefault();go(-1);}}if(e.key==='f'||e.key==='F'){{if(!document.fullscreenElement)document.documentElement.requestFullscreen();else document.exitFullscreen();}}}});
</script></body></html>"""

open(out, 'w', encoding='utf-8').write(html)
print("saved:", out, os.path.getsize(out), "bytes,", n, "slides")
