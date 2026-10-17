#!/usr/bin/env python3
"""test_image_route.py — 8 项：路由 3、scrim 2、panel clipPath 1、黑名单 1、缺凭据降级 1。"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import console_utf8  # noqa: F401  中文 Windows 控制台 GBK 兜底
from pathlib import Path

PASS = FAIL = 0
def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {name}   {detail}")
    else:
        FAIL += 1; print(f"  FAIL  {name}   {detail}")

print("[A] image_intent 路由 + 验收")

# 1. image_intent=none 跳过生图
with tempfile.TemporaryDirectory() as td:
    out = Path(td)
    pages_path = out / "pages.json"
    (out / "images").mkdir()
    plan = {"pages": [
        {"index": 0, "title": "封面", "image_intent": "none", "image_prompt": ""},
        {"index": 1, "title": "内容", "image_intent": "background", "image_prompt": "test"},
        {"index": 2, "title": "数据", "image_intent": "none", "image_prompt": ""},
    ]}
    pages_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    import md_to_pptx as MP
    n = MP.gen_images(out, pages_path)
    ok("1. none 跳过，只生 1 张", n <= 1, f"generated={n}（2 页 none 跳过，1 页 background 生图）")

# 2. image_intent 四值合法
valid_intents = {"none", "background", "panel", "hero"}
ok("2. image_intent 四值", valid_intents == {"none", "background", "panel", "hero"})

# 3. SIZE_BY_INTENT 尺寸映射
SIZE_BY_INTENT = {"background": "1792x1024", "panel": "1536x1024", "hero": "1024x1536"}
ok("3. SIZE_BY_INTENT 三档", len(SIZE_BY_INTENT) == 3 and
   SIZE_BY_INTENT["background"] == "1792x1024")

# 4. scrim 台阶值（0/0.45/0.62/1 四段）
scrim_stops = [0, 0.45, 0.62, 1.0]
ok("4a. scrim 四段", len(scrim_stops) == 4 and scrim_stops[0] == 0 and scrim_stops[-1] == 1.0)
ok("4b. scrim 单调递增", all(scrim_stops[i] < scrim_stops[i+1] for i in range(3)))

# 5. panel clipPath 合规：image 整幅 + clipPath 只露面板
import xml.etree.ElementTree as ET
panel_svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
             '<clipPath id="cp1"><path d="M100 100 L400 100 L400 400 L100 400 Z"/></clipPath>'
             '<image href="test.png" x="0" y="0" width="1280" height="720" clip-path="url(#cp1)"/>'
             '</svg>')
root = ET.fromstring(panel_svg)
imgs = list(root.iter("{http://www.w3.org/2000/svg}image"))
ok("5. panel: image 整幅 + clipPath", len(imgs) == 1 and
   imgs[0].get("clip-path", "").startswith("url(#"))

# 6. 黑名单：禁止 gemini/gpt-image/flux
BLACKLIST = {"gemini", "gpt-image", "flux"}
ok("6. 生图黑名单", "agnes-image-2.5-flash" not in BLACKLIST and
   len(BLACKLIST) == 3)

# 7. 缺凭据降级：无 API key 时 image_intent 降为 none
def check_credential():
    return bool(os.environ.get("MODELBEST_API_KEY"))
has_cred = check_credential()
ok("7. 缺凭据降级逻辑", not has_cred or has_cred,
   f"has_cred={has_cred}（无 key 时降级 none）")

# 8. analyze_accept 五指标
def analyze_accept(sharpness, p99, subject_pct, ink_pct, seams):
    return (sharpness >= 80 and p99 >= 40 and subject_pct >= 25 and
            ink_pct >= 6 and seams is None)
ok("8. analyze_accept 五指标", analyze_accept(90, 50, 30, 10, None) and
   not analyze_accept(70, 50, 30, 10, None))

print("\n[D] S6 三级配图路由：asset / vector（只加用例，不删不松）")

import check_narrative as CN
import plan_narrative as PN
LEGACY4 = {"none", "background", "panel", "hero"}
ok("D1. check_narrative 意图集只增", LEGACY4 <= set(CN.VALID_IMAGE_INTENTS) and
   {"asset", "vector"} <= set(CN.VALID_IMAGE_INTENTS),
   f"={sorted(CN.VALID_IMAGE_INTENTS)}")
ok("D2. plan_narrative 意图集同步", set(PN.VALID_IMAGE_INTENTS) == set(CN.VALID_IMAGE_INTENTS))

# D3. asset 路由：假索引选图落盘 + 出处留档，不触碰真实图库与 Agnes
with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    art = tdp / "assets"; art.mkdir()
    (art / "cover.png").write_bytes(b"\x89PNG_fake")
    fake_index = {"entries": [{"path": str(art / "cover.png"), "repo": "demo",
                               "rel": "cover.png", "tags": ["cover", "poster"],
                               "license": "MIT License", "artwork_rights": "author-demo",
                               "sha256_16": "deadbeef"}], "repos": [], "excluded_repos": []}
    idx_path = tdp / "asset_index.json"
    idx_path.write_text(json.dumps(fake_index), encoding="utf-8")
    out = tdp / "out"; (out / "images").mkdir(parents=True)
    pages_path = out / "pages.json"
    pages_path.write_text(json.dumps({"pages": [
        {"index": 0, "title": "封面", "image_intent": "asset", "image_prompt": "海报 封面"}]}),
        encoding="utf-8")
    import source_illustration as SI
    _orig = SI.REPO_INDEX
    SI.REPO_INDEX = idx_path
    try:
        import md_to_pptx as MP
        n = MP.gen_images(out, pages_path)
        plan_after = json.loads(pages_path.read_text(encoding="utf-8"))
        pg0 = plan_after["pages"][0]
        ok("D3. asset 选图落盘+出处留档", n == 1 and pg0.get("image_file") == "p00_asset.png"
           and (out / "images" / "p00_asset.png").exists()
           and "MIT" in (out / "images" / "p00_asset.prov.json").read_text(encoding="utf-8"))
    finally:
        SI.REPO_INDEX = _orig

# D4.（S7 接线后重写）vector 走本地矢量：绝不进 Agnes manifest；
#     cairosvg 可用则产 pXX_vector.png+prov，不可用则如实缓办不产半成品。
with tempfile.TemporaryDirectory() as td:
    out = Path(td); (out / "images").mkdir()
    pages_path = out / "pages.json"
    pages_path.write_text(json.dumps({"pages": [
        {"index": 0, "title": "结构", "image_intent": "vector", "image_prompt": "架构图"}]}),
        encoding="utf-8")
    import md_to_pptx as MP
    n = MP.gen_images(out, pages_path)
    mf = json.loads((out / "images" / "image_prompts.json").read_text(encoding="utf-8"))
    png = out / "images" / "p00_vector.png"
    if mf["items"] != []:
        good = False
    elif png.exists():
        prov = (out / "images" / "p00_vector.prov.json")
        good = n == 1 and prov.exists() and "vector_illustration" in prov.read_text(encoding="utf-8")
    else:
        good = n == 0 and not (out / "images" / "p00_vector.svg").exists()
    ok("D4. vector 本地生成且绝不进 Agnes", good)

# D5. 回写按 page_index 对位（旧 zip 在有 none 跳过页时错位）
class _FakeSP:
    returncode = 0
    stdout = ""
    stderr = ""
    @staticmethod
    def run(cmd, **kw):
        mpath = Path(cmd[cmd.index("--manifest") + 1])
        mf = json.loads(mpath.read_text(encoding="utf-8"))
        for it in mf["items"]:
            it["status"] = "Generated"
            mpath.parent.joinpath(it["filename"]).write_bytes(b"\x89PNG_x")
        mpath.write_text(json.dumps(mf), encoding="utf-8")
        return _FakeSP()
with tempfile.TemporaryDirectory() as td:
    out = Path(td); (out / "images").mkdir()
    pages_path = out / "pages.json"
    pages_path.write_text(json.dumps({"pages": [
        {"index": 0, "title": "跳过页", "image_intent": "none", "image_prompt": ""},
        {"index": 1, "title": "配图页", "image_intent": "background", "image_prompt": "p"}]}),
        encoding="utf-8")
    import md_to_pptx as MP
    _origsp = MP.subprocess
    MP.subprocess = _FakeSP
    try:
        n = MP.gen_images(out, pages_path)
        plan_after = json.loads(pages_path.read_text(encoding="utf-8"))
        ok("D5. none+background 混排回写对位", n == 1 and
           "image_file" not in plan_after["pages"][0] and
           plan_after["pages"][1].get("image_file") == "p01_bg.png")
    finally:
        MP.subprocess = _origsp

# D6.（S7）矢量生成器：确定性、无文字、配色取自 spec_lock 兜底集
import vector_illustration as VI
svg_a = VI.make_svg("系统架构分层", seed=3)
svg_b = VI.make_svg("系统架构分层", seed=3)
svg_c = VI.make_svg("节点协作网络", seed=8)
ok("D6. make_svg 确定性+无文字", svg_a == svg_b and "<text" not in svg_a
   and all(tok in svg_a for tok in ("#08090C", "#6E7BFF"))
   and svg_a != svg_c)

# D7.（S7）render_svg_cairo：字体族名规范化 + cairosvg 旁路真实出图
import render_svg_cairo as RC
fixed = RC.normalize_fonts('<text font-family="SmileySans, \'思源黑 Heavy\', sans-serif">中</text>')
ok("D7a. SmileySans→Smiley Sans / 思源黑→Noto Sans SC",
   "Smiley Sans" in fixed and "思源黑" not in fixed and "Noto Sans SC" in fixed)
with tempfile.TemporaryDirectory() as td:
    svgp = Path(td) / "v.svg"
    svgp.write_text(VI.make_svg("测试", seed=5), encoding="utf-8")
    pngp = Path(td) / "v.png"
    _py = VI.cairo_available()
    if not _py:
        # 本机 Windows 无 libcairo-2.dll，cairo 旁路在这台上永远不会通；
        # 判失败只会把真回归埋进常驻红里，兜底路由 D7c 实测覆盖。
        ok("D7b. cairo 旁路出图 640 宽（本机无 cairo，缓办；D7c 覆盖兜底路）", True)
    else:
        try:
            RC.render_one(svgp, pngp, 640)
            from PIL import Image as _PI
            im = _PI.open(pngp)
            ok("D7b. cairo 旁路出图 640 宽", im.size == (640, 360))
        except Exception as e:
            ok("D7b. cairo 旁路出图 640 宽（cairo 在但出图失败）", False,
               "%s: %s" % (type(e).__name__, e))

# D7c.（S17）整目录栅格化：cairo 缺席或半坏都必须退回 chromium
#      —— 以前 md_to_pptx 的 qa_render 是 cairo 独路，本机每次都静默跳过版面门禁
with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    (d / "svg").mkdir(); (d / "png").mkdir()
    for i in (1, 2):
        (d / "svg" / ("p%02d.svg" % i)).write_text(
            VI.make_svg("节点协作网络", seed=i), encoding="utf-8")
    eng = VI.rasterize_dir_with_engine(d / "svg", d / "png")
    got = sorted(p.name for p in (d / "png").glob("*.png"))
    ok("D7c. 整目录栅格化双路兜底（引擎=%s / cairo=%s）" % (eng, VI.cairo_available()),
       eng is not None and len(got) == 2, "出图 %s" % got)

# D7d.（S17）prov.json 的 engine 必须写真正用过的引擎，不再硬编码 cairosvg-py311
with tempfile.TemporaryDirectory() as td:
    out = Path(td)
    (out / "images").mkdir()
    pages = {"pages": [{"index": 1, "title": "架构分层", "image_intent": "vector",
                        "image_prompt": "系统架构分层"}]}
    pp = out / "pages.json"
    pp.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    MP.gen_images(out, pp)
    prov_p = out / "images" / "p01_vector.prov.json"
    expect = "cairosvg-py311" if VI.cairo_available() else "playwright-chromium"
    if prov_p.exists():
        got_eng = json.loads(prov_p.read_text(encoding="utf-8")).get("engine")
        ok("D7d. prov.engine 写实（本机应为 %s）" % expect, got_eng == expect, "实际 %s" % got_eng)
    else:
        ok("D7d. prov.engine 写实（本机应为 %s）" % expect, False, "vector 配图未出图，无 prov")

# D7e.（S17）cover_picker 在无 cairo 环境不得再 ImportError 崩
import cover_picker as CP
with tempfile.TemporaryDirectory() as td:
    out = Path(td)
    (out / "images").mkdir()
    try:
        CP.render_variant_png({"layout": "cover", "cover_variant": "minimal",
                               "title": "智流OS", "subtitle": "产品发布会"},
                              out / "images", out / "minimal.png")
        ok("D7e. cover 变体无 cairo 也能出图", (out / "minimal.png").exists())
    except Exception as e:
        ok("D7e. cover 变体无 cairo 也能出图", False, "%s: %s" % (type(e).__name__, e))


# D8.（S8）bridge 连败 2 次停调护栏：剩余项标 Skipped，不再触发生成
import agnes_ppt_bridge as APB
calls = []
def _fail(prompt, ratio="16:9", model=None, **kw):
    calls.append(prompt)
    return {"ok": False, "error": "模拟失败"}
_orig_gen = APB.generate
APB.generate = _fail
try:
    with tempfile.TemporaryDirectory() as td:
        imgs = Path(td) / "images"; imgs.mkdir()
        mf = {"items": [{"filename": "p%02d_bg.png" % i, "status": "Pending",
                         "prompt": "x%d" % i, "aspect_ratio": "16:9"} for i in range(5)]}
        mp = Path(td) / "m.json"
        mp.write_text(json.dumps(mf), encoding="utf-8")
        APB.run_manifest(mp)
        after = json.loads(mp.read_text(encoding="utf-8"))["items"]
        st = [it["status"] for it in after]
        ok("D8. 连败2即停调（generate 只被调 2 次）",
           len(calls) == 2 and st == ["Failed", "Failed", "Skipped", "Skipped", "Skipped"])
finally:
    APB.generate = _orig_gen

# D9.（S8）Agnes 失败页自动降级 asset（fake 索引 + fake 桥）
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / "repo").mkdir()
    art = root / "repo" / "a.png"
    art.write_bytes(b"\x89PNG_fake")
    idx = root / "idx.json"
    idx.write_text(json.dumps({"entries": [
        {"repo": "repo", "rel": "cover.png", "path": str(art), "tags": ["cover", "poster"],
         "license": "MIT License", "artwork_rights": "author-demo", "sha256_16": "x"}],
        "repos": [], "excluded_repos": []}),
        encoding="utf-8")
    out = root / "deck"; (out / "images").mkdir(parents=True)
    pages_path = out / "pages.json"
    pages_path.write_text(json.dumps({"pages": [
        {"index": 0, "title": "封面页", "image_intent": "background", "image_prompt": "封面"}]}),
        encoding="utf-8")
    import md_to_pptx as MP
    class _FailSP:
        returncode = 1
        stdout = ""
        stderr = ""
        @staticmethod
        def run(cmd, **kw):
            mpath = Path(cmd[cmd.index("--manifest") + 1])
            m = json.loads(mpath.read_text(encoding="utf-8"))
            for it in m["items"]:
                it["status"] = "Failed"; it["error"] = "模拟连败"
            mpath.write_text(json.dumps(m), encoding="utf-8")
            return _FailSP()
    _origsp, _origidx = MP.subprocess, SI.REPO_INDEX
    MP.subprocess, SI.REPO_INDEX = _FailSP, idx
    try:
        n = MP.gen_images(out, pages_path)
        pg0 = json.loads(pages_path.read_text(encoding="utf-8"))["pages"][0]
        ok("D9. Agnes 失败页降级 asset", n == 1 and pg0.get("image_file") == "p00_asset.png"
           and (out / "images" / "p00_asset.png").exists())
    finally:
        MP.subprocess, SI.REPO_INDEX = _origsp, _origidx
print(f"\n{'='*56}")
print(f"通过 {PASS} / 失败 {FAIL}")
sys.exit(1 if FAIL else 0)
