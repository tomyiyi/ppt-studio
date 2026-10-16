#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deck_to_poster.py —— deck 页 → Agnes 商业海报 的交接路由（S11）

方向性说明：agnes→deck 出口（生图/素材进 deck 页）S6–S8 已接通；
本脚本补上反向出口：把一页 deck（pages.json 内容要素 + 其底图）
交给 AGNES 侧 poster_composer 合成竖版海报。
与 make_cards.py 并列：make_cards 重排成竖版 SVG 卡片，
本桥接走 PIL 字体光影合成（得意黑/霞鹜文楷/宋体三套字体谱系）。

用法：
  python3 scripts/deck_to_poster.py <deck_dir> --page 1 [--out <dir>]
                                    [--agnes-repo PATH] [--ratio 3:4]
产物：
  <out>/pageNN_style1.png  /  pageNN_style2.png
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
DEFAULT_AGNES = Path("/Volumes/3TB_DATA/05-开发项目/agnes-studio-work")

STYLES = [
    {"font_style": "wenkai", "theme_color": "amber_gold", "tag": "wenkai_gold"},
    {"font_style": "smiley", "theme_color": "cyber_cyan", "tag": "smiley_cyan"},
]


def load_agnes(agnes_repo: Path):
    ap = str(agnes_repo / "scripts")
    if ap not in sys.path:
        sys.path.insert(0, ap)
    from poster_composer import compose_commercial_poster  # noqa: E402
    from copywriting_rules import apply_fix  # noqa: E402
    return compose_commercial_poster, apply_fix


def pick_tagline(text: str, limit: int = 30) -> str:
    """tagline 单行合成，底图上 1/3 是密集插画区，整句 48 字横向铺满必跨亮部失读
    （S11 目检实证）。按中文子句边界截到 limit 字内，是取材收紧、不改判据。"""
    import re
    clauses = [c for c in re.split(r"(?<=[，。；！？])", text) if c.strip()]
    acc = ""
    for c in clauses:
        if acc and len(acc) + len(c) > limit:
            break
        acc += c
        if len(acc) >= limit:
            break
    if not acc:
        acc = text[:limit]
    trimmed = len(acc) < len(text)
    return acc.rstrip("，。；！？") + ("…" if trimmed else "")


def crop_ratio(img, ratio_w=3, ratio_h=4):
    """中心裁切到目标比例（先按高度撑满再裁宽，保文字带在上方负空间）。"""
    from PIL import Image
    w, h = img.size
    target = ratio_w / ratio_h
    if w / h > target:
        nw = int(h * target)
        x0 = (w - nw) // 2
        box = (x0, 0, x0 + nw, h)
    else:
        nh = int(w / target)
        y0 = 0  # 顶部对齐：底图主体多在上 2/3，底部多为暗部
        box = (0, y0, w, y0 + nh)
    return img.crop(box)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="deck 页 → Agnes 海报")
    ap.add_argument("deck_dir")
    ap.add_argument("--page", type=int, required=True, help="pages.json 里的 index")
    ap.add_argument("--out", help="输出目录，默认 <deck_dir>/posters")
    ap.add_argument("--agnes-repo", default=str(DEFAULT_AGNES))
    ap.add_argument("--ratio", default="3:4")
    args = ap.parse_args(argv)

    deck = Path(args.deck_dir)
    pages = json.loads((deck / "pages.json").read_text(encoding="utf-8"))
    pg = next((p for p in pages.get("pages", []) if p.get("index") == args.page), None)
    if pg is None:
        print(f"[FAIL] pages.json 无 index={args.page} 的页", file=sys.stderr)
        return 1
    image_file = pg.get("image_file")
    bg_path = deck / "images" / image_file if image_file else None
    if not bg_path or not bg_path.exists():
        print(f"[FAIL] 该页无底图 image_file（poster_composer 需要背景图）；"
              f"请先走 S6–S8 的 agnes/asset/vector 出口补图", file=sys.stderr)
        return 1

    compose, apply_fix = load_agnes(Path(args.agnes_repo))

    title = apply_fix((pg.get("title") or "").strip())
    bullets = [apply_fix(b.strip()) for b in (pg.get("bullets") or []) if b.strip()]
    tagline = pick_tagline(bullets[0] if bullets else (pg.get("subtitle") or "").strip())
    tagline = apply_fix(tagline)
    sub_en = (pg.get("subtitle") or "").strip() or "AGNES DECK BRIDGE"
    meta = f"DECK PAGE {args.page:02d} // RUN-20261015-S11 // {date.today().isoformat()}"

    from PIL import Image
    rw, rh = (int(x) for x in args.ratio.split(":"))
    src = Image.open(bg_path).convert("RGBA")
    # 备料只做裁切：文字带压暗带（原 S11 兜底）已上移到 poster_composer 的
    # 明度自适应墨色/雾罩，底图不再被固定 alpha 的暗带整体压暗。
    cropped = crop_ratio(src, rw, rh)
    out_dir = Path(args.out) if args.out else deck / "posters"
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_bg = out_dir / f".page{args.page:02d}_bg{rw}x{rh}.png"
    cropped.convert("RGB").save(tmp_bg)

    made = []
    try:
        for st in STYLES:
            outp = out_dir / f"page{args.page:02d}_{st['tag']}.png"
            compose(str(tmp_bg), str(outp),
                    font_style=st["font_style"], theme_color=st["theme_color"],
                    main_title=title, sub_title=sub_en, tagline=tagline,
                    metadata_no=meta)
            made.append(outp)
    finally:
        tmp_bg.unlink(missing_ok=True)
    for p in made:
        print(f"✓ {p} ({p.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
