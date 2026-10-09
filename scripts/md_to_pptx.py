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

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
VENDOR = REPO / "vendor" / "ppt-master" / "scripts"

PY311 = Path("/usr/local/bin/python3.11")
PY = str(PY311 if PY311.exists() else sys.executable)


def run(cmd, **kw):
    print("  $ " + " ".join(str(c) for c in cmd[:3]) + (" ..." if len(cmd) > 3 else ""))
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print(r.stdout[-1500:])
        print(r.stderr[-1500:], file=sys.stderr)
        raise SystemExit("阶段失败")
    return r


def gen_images(out: Path, pages_path: Path) -> int:
    """按 pages.json 生成配图 manifest，调 agnes_ppt_bridge 生图。返回成功数。
    image_intent=none 的页跳过生图。"""
    plan = json.loads(pages_path.read_text(encoding="utf-8"))
    images_dir = out / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    items = []
    skipped = 0
    for pg in plan["pages"]:
        intent = pg.get("image_intent", "background")
        if intent == "none":
            skipped += 1
            print(f"  p{pg['index']:02d} image_intent=none，跳过生图")
            continue
        fn = "p%02d_bg.png" % pg["index"]
        items.append({
            "filename": fn,
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

    print("  生图 %d 张（经 prompt 安全拦截）..." % len(items))
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "agnes_ppt_bridge.py"),
         "--manifest", str(manifest)],
        capture_output=True, text=True)
    print(r.stdout[-800:])
    if r.returncode != 0:
        print(r.stderr[-800:], file=sys.stderr)

    # 回写 image_file
    done = 0
    mf = json.loads(manifest.read_text(encoding="utf-8"))
    status = {it["filename"]: it.get("status") for it in mf.get("items", [])}
    for pg, it in zip(plan["pages"], items):
        fn = it["filename"]
        if status.get(fn) == "Generated" and (images_dir / fn).exists():
            pg["image_file"] = fn
            done += 1
    pages_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Markdown -> PPTX 一键")
    ap.add_argument("--md", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--name", default="deck")
    ap.add_argument("--no-images", action="store_true", help="跳过生图（纯文字版）")
    ap.add_argument("--skip-qa", action="store_true")
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
    run([sys.executable, str(SCRIPTS / "md_to_pages.py"),
         "--md", str(args.md), "--out", str(pages_path)])


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
        print("[4/7] planning 合同校验")
        run([sys.executable, str(SCRIPTS / "plan_contract.py"), "--project", str(out)])
        print("[5/7] 打分质检")
        run([sys.executable, str(SCRIPTS / "qa_score.py"), str(svg_dir)])
        print("[6/7] vendor SVG 质检门禁")
        run([PY, str(VENDOR / "svg_quality_checker.py"), str(out),
             "--canonical-authoring", "--stage", "final", "--json"])

    print("[7/7] SVG -> PPTX")
    pptx = out / (args.name + ".pptx")
    run([PY, str(VENDOR / "svg_to_pptx.py"), str(out), "-o", str(pptx)])

    n = len(json.loads(pages_path.read_text(encoding="utf-8"))["pages"])
    print("\n✅ 完成：%d 页 -> %s (%d KB)" % (n, pptx, pptx.stat().st_size // 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
