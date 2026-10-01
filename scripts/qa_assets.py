"""qa_assets.py -- SVG 引用图片资产门禁（第 29 轮）。

背景：v4 交付时 P06 街拍图（500×750 源图放在 1920 画布上）轻微模糊，
是人工肉眼发现的；svg_to_pptx._materialize_images 对缺失图片只打印 [warn]，
rsvg 静默跳过——构建前没有任何门禁。本脚本在构建/验收前检查
每个 SVG 的 <image> 引用：

1. 存在性：本地 href 必须解析到存在的文件（data: URI 内嵌图跳过）；
2. 可解码：Pillow 能打开并读出尺寸（缺 Pillow 时分辨率项记 warn，不拦门禁）；
3. 分辨率充足度：源图像素 / SVG 声明的显示尺寸（width/height 属性，
   viewBox 单位 ≈ 画布像素）；scale = min(img_w/disp_w, img_h/disp_h)；
   scale < min_scale（默认 0.5）判 fail（肉眼可见模糊）；
   min_scale <= scale < 1.0 判 warn（记录但不拦门禁）。

接口：run_qa_assets(project_dir, *, min_scale=0.5) -> dict
CLI：python3 scripts/qa_assets.py projects/fw2026-trends [--min-scale 0.5]
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_page_map import find_svg_dir  # noqa: E402

XLINK = "{http://www.w3.org/1999/xlink}"

try:
    from PIL import Image as _PILImage

    _PIL_OK = True
except ImportError:  # pragma: no cover
    _PIL_OK = False


def _iter_images(root: ET.Element):
    """产出 (image 元素, href)。"""
    for el in root.iter():
        if el.tag.endswith("image"):
            href = el.get(f"{XLINK}href") or el.get("href")
            if href:
                yield el, href.strip()


def _parse_len(val: str | None) -> float | None:
    if not val:
        return None
    try:
        return float(val.strip().lower().removesuffix("px"))
    except ValueError:
        return None


def run_qa_assets(project_dir: str | Path, *, min_scale: float = 0.5) -> dict[str, Any]:
    """检查项目 SVG 目录下所有 <image> 引用的资产完整性。

    返回 dict(ok=无 fail 项, issues=[fail...], warnings=[warn...],
             n_images=本地引用数, n_skipped_data_uri=内嵌图数)。
    """
    proj = Path(project_dir).resolve()
    svg_dir = find_svg_dir(proj)
    if svg_dir is None:
        return {"ok": False, "code": "NO_SVG_DIR",
                "issues": [f"找不到 SVG 目录: {proj}"], "warnings": [],
                "n_images": 0, "n_skipped_data_uri": 0}

    issues: list[str] = []
    warnings: list[str] = []
    n_images = n_data = 0
    for svg in sorted(svg_dir.glob("*.svg")):
        try:
            root = ET.parse(svg).getroot()
        except ET.ParseError as e:
            issues.append(f"{svg.name}: SVG 解析失败: {e}")
            continue
        for el, href in _iter_images(root):
            if href.startswith("data:"):
                n_data += 1
                continue
            n_images += 1
            src = (svg.parent / href).resolve() \
                if not Path(href).is_absolute() else Path(href).resolve()
            if not src.is_file():
                issues.append(f"{svg.name}: 图片缺失: {href}（rsvg 会静默跳过，页面留空）")
                continue
            if not _PIL_OK:
                warnings.append(f"{svg.name}: {src.name} 未做分辨率检查（缺 Pillow）")
                continue
            try:
                with _PILImage.open(src) as im:
                    iw, ih = im.size
            except Exception as e:
                issues.append(f"{svg.name}: 图片不可解码: {src.name}（{e}）")
                continue
            disp_w, disp_h = _parse_len(el.get("width")), _parse_len(el.get("height"))
            if disp_w and disp_h and disp_w > 0 and disp_h > 0:
                scale = min(iw / disp_w, ih / disp_h)
                if scale < min_scale:
                    issues.append(
                        f"{svg.name}: {src.name} 分辨率不足：源图 {iw}×{ih}，"
                        f"显示 {int(disp_w)}×{int(disp_h)}"
                        f"（scale={scale:.2f} < {min_scale}，肉眼可见模糊）")
                elif scale < 1.0:
                    warnings.append(
                        f"{svg.name}: {src.name} 源图 {iw}×{ih} 小于"
                        f"显示 {int(disp_w)}×{int(disp_h)}（scale={scale:.2f}），轻微放大")
    return {"ok": not issues, "issues": issues, "warnings": warnings,
            "n_images": n_images, "n_skipped_data_uri": n_data,
            "svg_dir": str(svg_dir), "pil_ok": _PIL_OK}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="SVG 引用图片资产门禁：存在性 / 可解码 / 分辨率充足度")
    ap.add_argument("project_dir", nargs="?", default=".",
                    help="项目目录（缺省当前目录）")
    ap.add_argument("--min-scale", type=float, default=0.5,
                    help="分辨率 fail 阈值（默认 0.5）")
    a = ap.parse_args(argv)
    rep = run_qa_assets(a.project_dir, min_scale=a.min_scale)
    for w in rep["warnings"]:
        print(f"  [warn] {w}")
    for i in rep["issues"]:
        print(f"  [fail] {i}")
    print(f"[{'ok' if rep['ok'] else 'FAIL'}] 图片资产门禁：{rep['n_images']} 张本地引用"
          f"（另 {rep['n_skipped_data_uri']} 张 data: 内嵌图跳过），"
          f"{len(rep['issues'])} fail / {len(rep['warnings'])} warn")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
