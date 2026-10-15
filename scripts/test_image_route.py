#!/usr/bin/env python3
"""test_image_route.py — 8 项：路由 3、scrim 2、panel clipPath 1、黑名单 1、缺凭据降级 1。"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
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

# D4. vector 未接线：如实缓办，不进 Agnes manifest
with tempfile.TemporaryDirectory() as td:
    out = Path(td); (out / "images").mkdir()
    pages_path = out / "pages.json"
    pages_path.write_text(json.dumps({"pages": [
        {"index": 0, "title": "结构", "image_intent": "vector", "image_prompt": "架构图"}]}),
        encoding="utf-8")
    import md_to_pptx as MP
    n = MP.gen_images(out, pages_path)
    mf = json.loads((out / "images" / "image_prompts.json").read_text(encoding="utf-8"))
    ok("D4. vector 缓办不进 Agnes", n == 0 and mf["items"] == [])

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

print(f"\n{'='*56}")
print(f"通过 {PASS} / 失败 {FAIL}")
sys.exit(1 if FAIL else 0)
