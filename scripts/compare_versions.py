#!/usr/bin/env python3
"""Create a self-contained visual comparison report for two rendered slide sets."""

from __future__ import annotations

import argparse
import base64
import io
import sys
from dataclasses import dataclass
from html import escape
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageDraw


PIXEL_DELTA_THRESHOLD = 12
SUPPORTED_SUFFIX = ".png"


@dataclass(frozen=True)
class SlideDiff:
    name: str
    left: Image.Image
    right: Image.Image
    diff: Image.Image
    changed_pixels: int
    changed_ratio: float
    bbox: tuple[int, int, int, int] | None


def _slides(directory: Path) -> dict[str, Path]:
    if not directory.is_dir():
        raise ValueError(f"render directory does not exist: {directory}")
    files = sorted(directory.glob(f"*{SUPPORTED_SUFFIX}"))
    if not files:
        raise ValueError(f"no PNG slides found in {directory}")
    return {path.stem: path for path in files}


def _changed_mask(left: Image.Image, right: Image.Image) -> Image.Image:
    diff = ImageChops.difference(left.convert("RGB"), right.convert("RGB"))
    channels = diff.split()
    maximum = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    return maximum.point(lambda value: 255 if value > PIXEL_DELTA_THRESHOLD else 0)


def _diff_image(left: Image.Image, right: Image.Image, mask: Image.Image, bbox: tuple[int, int, int, int] | None) -> Image.Image:
    faded = ImageEnhance.Brightness(left.convert("RGB")).enhance(0.38)
    raw = ImageChops.difference(left.convert("RGB"), right.convert("RGB"))
    result = Image.blend(faded, ImageEnhance.Contrast(raw).enhance(2.5), 0.72)
    result.putalpha(mask)
    canvas = Image.new("RGBA", left.size, (28, 28, 32, 255))
    canvas.alpha_composite(result.convert("RGBA"))
    if bbox:
        draw = ImageDraw.Draw(canvas)
        draw.rectangle(bbox, outline=(255, 220, 80, 255), width=max(2, left.width // 500))
    return canvas.convert("RGB")


def compare(left_dir: Path, right_dir: Path) -> list[SlideDiff]:
    left = _slides(left_dir)
    right = _slides(right_dir)
    if set(left) != set(right):
        missing = sorted(set(left) - set(right))
        extra = sorted(set(right) - set(left))
        raise ValueError(f"slide sets do not match; missing_right={missing}; extra_right={extra}")
    result: list[SlideDiff] = []
    for name in left:
        left_image = Image.open(left[name]).convert("RGB")
        right_image = Image.open(right[name]).convert("RGB")
        if left_image.size != right_image.size:
            raise ValueError(f"slide {name} dimensions differ: {left_image.size} vs {right_image.size}")
        mask = _changed_mask(left_image, right_image)
        changed = sum(1 for value in mask.getdata() if value)
        bbox = mask.getbbox()
        result.append(SlideDiff(name, left_image, right_image, _diff_image(left_image, right_image, mask, bbox), changed, changed / (left_image.width * left_image.height), bbox))
    return result


def _data_uri(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def render_report(diffs: list[SlideDiff]) -> str:
    changed = [item for item in diffs if item.changed_pixels]
    max_item = max(diffs, key=lambda item: item.changed_ratio)
    cards = []
    for item in diffs:
        bbox = "none" if item.bbox is None else "x=%d y=%d w=%d h=%d" % (item.bbox[0], item.bbox[1], item.bbox[2] - item.bbox[0], item.bbox[3] - item.bbox[1])
        cards.append(f'''<article class="slide"><h2>{escape(item.name)}</h2><p>changed: {item.changed_ratio:.2%} · bbox: {escape(bbox)}</p><div class="triptych"><figure><figcaption>A</figcaption><img src="{_data_uri(item.left)}"></figure><figure><figcaption>B</figcaption><img src="{_data_uri(item.right)}"></figure><figure><figcaption>DIFF</figcaption><img src="{_data_uri(item.diff)}"></figure></div></article>''')
    return """<!doctype html><html lang="en"><meta charset="utf-8"><title>Version comparison</title>
<style>body{font:14px system-ui,sans-serif;background:#f4f5f7;color:#20242b;margin:24px}.summary,.slide{background:white;border:1px solid #d8dce2;border-radius:12px;padding:16px;margin:0 0 16px}.triptych{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}figure{margin:0;background:#111;padding:8px;border-radius:8px}figcaption{color:#fff;font-weight:700;margin:0 0 6px}img{display:block;width:100%%;height:auto}.slide p{color:#586170}</style>
<section class="summary"><h1>Version comparison</h1><p>Slides compared: %d · Changed slides: %d · Max changed ratio: %.2f%% · %s</p></section>%s</html>""" % (len(diffs), len(changed), max_item.changed_ratio * 100, escape(max_item.name), "".join(cards))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left_render", type=Path)
    parser.add_argument("right_render", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        diffs = compare(args.left_render, args.right_render)
        args.output.write_text(render_report(diffs), encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"compare_versions: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {args.output} ({len(diffs)} slides)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
