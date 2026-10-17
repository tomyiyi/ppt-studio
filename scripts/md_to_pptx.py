#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键：Markdown 文章 -> PPTX（内容驱动生成的完整闭环）

链路：
  md_to_pages.py（切页，含 image_prompt） -> agnes_ppt_bridge.py（生图）
  -> pages_to_svg.py（渲染，背景图+scrim）
  -> plan_contract.py（合同校验） -> qa_score.py（打分质检）
  -> svg_quality_checker.py（vendor 门禁） -> svg_to_pptx.py（转 PPTX）

用法：
    python3 scripts/md_to_pptx.py --md <文章.md> --out <输出目录> [--name deck]
    python3 scripts/md_to_pptx.py --md <文章.md> --out <输出目录> --no-images  # 纯文字版

要求：vendor 转换链需 Python 3.10+（黑苹果上用 /usr/local/bin/python3.11）。
生图走本机 New API（agnes_ppt_bridge），prompt 经 prompt_safety 拦截。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
import console_utf8  # noqa: F401  中文 Windows 控制台 GBK 兜底

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
VENDOR = REPO / "vendor" / "ppt-master" / "scripts"

PY311 = Path("/usr/local/bin/python3.11")
PY = str(PY311 if PY311.exists() else sys.executable)


def run(cmd, **kw):
    print("  $ " + " ".join(str(c) for c in cmd[:3]) + (" ..." if len(cmd) > 3 else ""))
    kw.setdefault("env", console_utf8.child_env())
    kw.update(console_utf8.TEXT_KW)
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print(r.stdout[-1500:])
        print(r.stderr[-1500:], file=sys.stderr)
        raise SystemExit("阶段失败")
    return r


def _place_asset(pg: dict, images_dir: Path) -> bool:
    """asset 路由落图：图库选图 + 复制 + 出处 JSON。无匹配返回 False（不硬塞）。"""
    import source_illustration as SI
    index = SI.load_index(SI.REPO_INDEX) if SI.REPO_INDEX.exists() else SI.build_index()
    q = (pg.get("image_prompt") or "") + " " + (pg.get("title") or "")
    scored = SI.pick(index, q)
    fn = "p%02d_asset.png" % pg["index"]
    if not scored:
        return False
    score, e = scored[0]
    shutil.copyfile(e["path"], images_dir / fn)
    pg["image_file"] = fn
    (images_dir / ("p%02d_asset.prov.json" % pg["index"])).write_text(
        json.dumps({"picked": e["rel"], "source": e["path"], "repo": e["repo"],
                    "license": e["license"], "artwork_rights": e["artwork_rights"],
                    "sha256_16": e["sha256_16"], "score": score},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  p{pg['index']:02d} asset 选图 %s（license=%s）" % (e["rel"], e["license"]))
    return True


def gen_images(out: Path, pages_path: Path) -> int:
    """三级配图路由：agnes（background/panel/hero 走生图桥）/ asset（本地图库选图）/
    vector（S7 起走 vector_illustration 本地生成，cairosvg 旁路栅格化；环境缺失如实缓办）。
    返回成功配图页数。image_intent=none 的页跳过。"""
    plan = json.loads(pages_path.read_text(encoding="utf-8"))
    images_dir = out / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    items = []
    skipped = deferred = 0
    for pg in plan["pages"]:
        intent = pg.get("image_intent", "background")
        if intent == "none":
            skipped += 1
            print(f"  p{pg['index']:02d} image_intent=none，跳过生图")
            continue
        if intent == "vector":
            # S7 接线：本地确定性矢量配图（无浏览器/无 Agnes 调用）；环境缺失如实缓办
            import vector_illustration as VI
            svg_fn = "p%02d_vector.svg" % pg["index"]
            fn = "p%02d_vector.png" % pg["index"]
            svg_path = images_dir / svg_fn
            svg_path.write_text(
                VI.make_svg(pg.get("image_prompt") or pg.get("title") or "",
                            seed=pg["index"] + 1, spec_lock=out / "spec_lock.md"),
                encoding="utf-8")
            engine = VI.rasterize_with_engine(svg_path, images_dir / fn)
            if not engine:
                svg_path.unlink(missing_ok=True)
                print(f"  p{pg['index']:02d} image_intent=vector：cairosvg 与 chromium 两条"
                      "栅格化路都不通，如实缓办（不硬塞半成品）")
                deferred += 1
                continue
            pg["image_file"] = fn
            (images_dir / ("p%02d_vector.prov.json" % pg["index"])).write_text(
                json.dumps({"generator": "vector_illustration", "motif_seed": pg["index"] + 1,
                            "prompt": pg.get("image_prompt", ""), "engine": engine,
                            "text_in_image": False},
                           ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  p{pg['index']:02d} vector 本矢生成 {fn}（未调 Agnes）")
            continue
        if intent == "asset":
            if not _place_asset(pg, images_dir):
                print(f"  p{pg['index']:02d} image_intent=asset：图库无匹配（不硬塞），缓办")
                deferred += 1
            continue
        fn = "p%02d_bg.png" % pg["index"]
        items.append({
            "filename": fn,
            "page_index": pg["index"],   # 回写按页号对位；旧版 zip() 在有跳过页时错位
            "purpose": "第%d页配图：%s" % (pg["index"] + 1, pg["title"][:30]),
            "page_role": "content_bg",
            "text_policy": "none",
            "aspect_ratio": "16:9",
            "model": "agnes-image-2.5-flash",
            "status": "Pending",
            "prompt": pg.get("image_prompt", ""),
        })
    manifest = images_dir / "image_prompts.json"
    manifest.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    done = sum(1 for pg in plan["pages"]
               if str(pg.get("image_file", "")).endswith(("_asset.png", "_vector.png")))
    if items:
        print("  生图 %d 张（经 prompt 安全拦截）..." % len(items))
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "agnes_ppt_bridge.py"),
             "--manifest", str(manifest)],
            capture_output=True, text=True,
            env=console_utf8.child_env(), **console_utf8.TEXT_KW)
        print(r.stdout[-800:])
        if r.returncode != 0:
            print(r.stderr[-800:], file=sys.stderr)

        # 回写 image_file：按 page_index 对位，不按列表位置
        mf = json.loads(manifest.read_text(encoding="utf-8"))
        status = {it["filename"]: it.get("status") for it in mf.get("items", [])}
        by_index = {pg["index"]: pg for pg in plan["pages"]}
        for it in mf.get("items", []):
            fn = it["filename"]
            pg = by_index.get(it.get("page_index"))
            if pg is None:
                continue
            if status.get(fn) == "Generated" and (images_dir / fn).exists():
                pg["image_file"] = fn
                done += 1
            else:
                # S8 降级护栏的后半段：Agnes 失败/停调的页改走 asset 兜底
                if _place_asset(pg, images_dir):
                    done += 1
                else:
                    deferred += 1
                    print(f"  p{pg['index']:02d} Agnes 未成图且 asset 无匹配，如实缓办"
                          f"（{it.get('error', status.get(fn))}）")
    pages_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    if deferred:
        print("  缓办 %d 页（vector/asset 无匹配）" % deferred)
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Markdown -> PPTX 一键")
    ap.add_argument("--md", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--name", default="deck")
    ap.add_argument("--no-images", action="store_true", help="跳过生图（纯文字版）")
    ap.add_argument("--skip-qa", action="store_true")
    ap.add_argument("--narrative", type=Path, default=None,
                    help="narrative.json 路径（接入 N1 结构器输出）")
    ap.add_argument("--cover-choice",
                    choices=["hero_full", "split", "minimal"],
                    help="封面构图三选一（默认 hero_full；out/cover_choice.json 存在时自动采用）")
    args = ap.parse_args(argv)

    out = args.out
    svg_dir = out / "svg_output"
    (out / "images").mkdir(parents=True, exist_ok=True)
    pages_path = out / "pages.json"

    if not (out / "spec_lock.md").exists():
        tmpl = REPO / "patterns" / "spec_lock.template.md"
        if not tmpl.exists():
            raise SystemExit(f"缺真相源模板 {tmpl} —— 拒绝静默回退到工程实例（真相源缺口，见 spec §4.1）")
        shutil.copy(tmpl, out / "spec_lock.md")

    print("[1/7] 切页 md -> pages.json")
    cmd = [sys.executable, str(SCRIPTS / "md_to_pages.py"),
           "--md", str(args.md), "--out", str(pages_path)]
    if args.narrative:
        cmd += ["--narrative", str(args.narrative)]
    run(cmd)


    # 封面三选一：显式参数 > cover_choice.json > 默认 hero_full
    _choice = args.cover_choice
    _choice_file = out / "cover_choice.json"
    if not _choice and _choice_file.exists():
        try:
            _choice = json.loads(_choice_file.read_text(encoding="utf-8")).get("cover_variant")
        except Exception:
            _choice = None
    _choice = _choice or "hero_full"
    _plan = json.loads(pages_path.read_text(encoding="utf-8"))
    for _pg in _plan.get("pages", []):
        if _pg.get("layout") == "cover":
            _pg["cover_variant"] = _choice
            break
    pages_path.write_text(json.dumps(_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print("  封面构图：%s" % _choice)

    if args.no_images:
        print("[2/7] 跳过生图")
    else:
        print("[2/7] Agnes 生图")
        n = gen_images(out, pages_path)
        print("  成功 %d 张" % n)

    print("[3/7] 渲染 pages -> SVG（ppt-master 模板驱动）")
    run([sys.executable, str(SCRIPTS / "template_renderer.py"),
         "--pages", str(pages_path), "--out", str(svg_dir),
         "--images", str(out / "images")])

    if not args.skip_qa:
        print("[4/7] qa_layout 版面复核")
        render_dir = out / "qa_render"
        render_dir.mkdir(parents=True, exist_ok=True)
        # F1：先把版面栅格化喂给 qa_layout——此前 qa_render 恒为空，面板/对比度门禁形同虚设
        # （S8 实测发现）。S17 起 cairo 独路改成 cairo→chromium 双路：主力 Windows 环境没有
        # libcairo-2.dll，老代码在这台上每次都静默跳过整块版面门禁。
        import vector_illustration as VI
        engine = VI.rasterize_dir_with_engine(svg_dir, render_dir)
        if not engine:
            print("[WARN] cairo 与 chromium 两条栅格化路都不通：qa_layout 面板/对比度检查"
                  "将被跳过，本次产物不得作为交付证据", file=sys.stderr)
        else:
            print(f"  版面栅格化引擎：{engine}（qa_layout 面板/对比度门禁已喂入）")
        run([sys.executable, str(SCRIPTS / "qa_layout.py"),
             str(svg_dir), str(render_dir)])
        print("[5/7] planning 合同校验")
        run([sys.executable, str(SCRIPTS / "plan_contract.py"), "--project", str(out)])
        print("[6/7] 打分质检")
        run([sys.executable, str(SCRIPTS / "qa_score.py"), str(svg_dir)])
        print("[7/7] vendor SVG 质检门禁")
        run([PY, str(VENDOR / "svg_quality_checker.py"), str(out),
             "--canonical-authoring", "--stage", "final", "--json"])

    print("[8/8] SVG -> PPTX")
    pptx = out / (args.name + ".pptx")
    run([PY, str(VENDOR / "svg_to_pptx.py"), str(out), "-o", str(pptx)])

    n = len(json.loads(pages_path.read_text(encoding="utf-8"))["pages"])
    print("\n✅ 完成：%d 页 -> %s (%d KB)" % (n, pptx, pptx.stat().st_size // 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
