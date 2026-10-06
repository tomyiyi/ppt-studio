"""tests/test_qa_assets.py -- SVG 引用图片资产门禁（第 29 轮）。"""
from __future__ import annotations

import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from PIL import Image
except ImportError:
    Image = None

from scripts.qa_assets import _find_svg_dir, main, resolve_project_dir, run_qa_assets

SVG_TMPL = """<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 1920 1080">
{images}
</svg>"""

IMG_TMPL = '<image xlink:href="{href}" x="0" y="0" width="{w}" height="{h}"/>'


class _MockImage:
    def __init__(self, size: tuple[int, int]):
        self.size = size

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _MockPIL:
    @staticmethod
    def open(fp: str | Path):
        data = Path(fp).read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("cannot identify image file")
        w, h = struct.unpack(">II", data[16:24])
        return _MockImage((w, h))


def _make_png(path: Path, w: int, h: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if Image is not None:
        Image.new("RGB", (w, h), (128, 128, 128)).save(path)
        return
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * w for _ in range(h))
    compressed = zlib.compress(raw)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    png_bytes = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")
    path.write_bytes(png_bytes)


class QaAssetsTestBase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        if Image is None:
            self._patch_pil_ok = patch("scripts.qa_assets._PIL_OK", True)
            self._patch_pil_img = patch("scripts.qa_assets._PILImage", _MockPIL)
            self._patch_pil_ok.start()
            self._patch_pil_img.start()
            self.addCleanup(self._patch_pil_ok.stop)
            self.addCleanup(self._patch_pil_img.stop)

    def make_project(self, td: str, images: str) -> Path:
        proj = Path(td) / "proj"
        svg_dir = proj / "svg_output"
        (proj / "images").mkdir(parents=True)
        svg_dir.mkdir(parents=True)
        (svg_dir / "p1.svg").write_text(
            SVG_TMPL.format(images=images), encoding="utf-8")
        return proj


class TestQaAssets(QaAssetsTestBase):
    def test_good_image_passes(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(
                td, IMG_TMPL.format(href="../images/good.png", w=400, h=300))
            _make_png(proj / "images" / "good.png", 800, 600)
            rep = run_qa_assets(proj)
            self.assertTrue(rep["ok"])
            self.assertEqual(rep["issues"], [])
            self.assertEqual(rep["n_images"], 1)

    def test_missing_image_fails(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(
                td, IMG_TMPL.format(href="../images/nope.png", w=400, h=300))
            rep = run_qa_assets(proj)
            self.assertFalse(rep["ok"])
            self.assertTrue(any("缺失" in i for i in rep["issues"]))

    def test_undecodable_image_fails(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(
                td, IMG_TMPL.format(href="../images/broken.png", w=400, h=300))
            (proj / "images" / "broken.png").write_text("not a png", encoding="utf-8")
            rep = run_qa_assets(proj)
            self.assertFalse(rep["ok"])
            self.assertTrue(any("不可解码" in i for i in rep["issues"]))

    def test_low_resolution_fails(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(
                td, IMG_TMPL.format(href="../images/tiny.png", w=400, h=400))
            _make_png(proj / "images" / "tiny.png", 100, 100)  # scale=0.25
            rep = run_qa_assets(proj)
            self.assertFalse(rep["ok"])
            self.assertTrue(any("分辨率不足" in i and "scale=0.25" in i
                                for i in rep["issues"]))

    def test_mid_resolution_warns_but_passes(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(
                td, IMG_TMPL.format(href="../images/mid.png", w=400, h=400))
            _make_png(proj / "images" / "mid.png", 300, 300)  # scale=0.75
            rep = run_qa_assets(proj)
            self.assertTrue(rep["ok"])
            self.assertEqual(rep["issues"], [])
            self.assertTrue(any("轻微放大" in w for w in rep["warnings"]))

    def test_data_uri_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(
                td, IMG_TMPL.format(href="data:image/png;base64,iVBORw0KGgo=",
                                    w=10, h=10))
            rep = run_qa_assets(proj)
            self.assertTrue(rep["ok"])
            self.assertEqual(rep["n_images"], 0)
            self.assertEqual(rep["n_skipped_data_uri"], 1)

    def test_absolute_href_resolved(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(td, "")
            img = proj / "images" / "abs.png"
            _make_png(img, 800, 600)
            (proj / "svg_output" / "p1.svg").write_text(
                SVG_TMPL.format(images=IMG_TMPL.format(href=str(img), w=400, h=300)),
                encoding="utf-8")
            rep = run_qa_assets(proj)
            self.assertTrue(rep["ok"])

    def test_no_svg_dir_fails(self):
        with tempfile.TemporaryDirectory() as td:
            rep = run_qa_assets(Path(td))
            self.assertFalse(rep["ok"])
            self.assertEqual(rep["code"], "NO_SVG_DIR")

    def test_cli_exit_code(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(
                td, IMG_TMPL.format(href="../images/nope.png", w=400, h=300))
            self.assertEqual(main([str(proj)]), 1)
            _make_png(proj / "images" / "nope.png", 800, 600)
            (proj / "svg_output" / "p1.svg").write_text(
                SVG_TMPL.format(images=IMG_TMPL.format(
                    href="../images/nope.png", w=400, h=300)),
                encoding="utf-8")
            self.assertEqual(main([str(proj)]), 0)


class TestQaAssetsSubdirAndSingleSvgResolution(QaAssetsTestBase):
    def test_resolve_project_dir_subfolder_and_file(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(td, "")
            (proj / "spec_lock.md").write_text("# Spec\n", encoding="utf-8")
            sub_svg = proj / "svg_output"
            sub_img = proj / "images"
            spec_file = proj / "spec_lock.md"
            self.assertEqual(resolve_project_dir(sub_svg), proj.resolve())
            self.assertEqual(resolve_project_dir(sub_img), proj.resolve())
            self.assertEqual(resolve_project_dir(spec_file), proj.resolve())
            self.assertEqual(resolve_project_dir(str(sub_svg)), proj.resolve())
            self.assertEqual(resolve_project_dir(base_dir=sub_svg), proj.resolve())
            self.assertEqual(resolve_project_dir(base_dir=spec_file), proj.resolve())
            self.assertEqual(resolve_project_dir("svg_output", base_dir=proj), proj.resolve())

            with patch("scripts.qa_assets._cpm_resolve_project_dir", None):
                self.assertEqual(resolve_project_dir(sub_svg), proj.resolve())
                self.assertEqual(resolve_project_dir(sub_img), proj.resolve())
                self.assertEqual(resolve_project_dir(spec_file), proj.resolve())
                self.assertEqual(resolve_project_dir(base_dir=sub_svg), proj.resolve())
                self.assertEqual(resolve_project_dir(base_dir=spec_file), proj.resolve())
                self.assertEqual(resolve_project_dir("svg_output", base_dir=proj), proj.resolve())
                self.assertEqual(resolve_project_dir(""), Path.cwd().resolve())
                self.assertEqual(resolve_project_dir("."), Path.cwd().resolve())

    def test_run_qa_assets_with_base_dir(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(
                td, IMG_TMPL.format(href="../images/good.png", w=400, h=300))
            (proj / "spec_lock.md").write_text("# Spec\n", encoding="utf-8")
            _make_png(proj / "images" / "good.png", 800, 600)
            rep_rel = run_qa_assets(".", base_dir=proj)
            self.assertTrue(rep_rel["ok"])
            self.assertEqual(rep_rel["n_images"], 1)

            rep_sub = run_qa_assets("svg_output", base_dir=proj)
            self.assertTrue(rep_sub["ok"])
            self.assertEqual(rep_sub["n_images"], 1)

            self.assertEqual(main([".", "--min-scale", "0.5"], base_dir=proj), 0)
            self.assertEqual(main(["svg_output"], base_dir=proj), 0)
            self.assertEqual(main([".", "--min-scale", "0.5", "--base-dir", str(proj)]), 0)
            self.assertEqual(main(["svg_output", "--base-dir", str(proj)]), 0)

    def test_run_qa_assets_from_subfolder(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(
                td, IMG_TMPL.format(href="../images/good.png", w=400, h=300))
            (proj / "spec_lock.md").write_text("# Spec\n", encoding="utf-8")
            _make_png(proj / "images" / "good.png", 800, 600)
            rep_from_svg = run_qa_assets(proj / "svg_output")
            self.assertTrue(rep_from_svg["ok"])
            self.assertEqual(rep_from_svg["n_images"], 1)

            rep_from_img = run_qa_assets(proj / "images")
            self.assertTrue(rep_from_img["ok"])
            self.assertEqual(rep_from_img["n_images"], 1)

    def test_run_qa_assets_single_svg_file(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(
                td, IMG_TMPL.format(href="../images/good.png", w=400, h=300))
            _make_png(proj / "images" / "good.png", 800, 600)
            single_svg = proj / "svg_output" / "p1.svg"
            rep = run_qa_assets(single_svg)
            self.assertTrue(rep["ok"])
            self.assertEqual(rep["n_images"], 1)

    def test_run_qa_assets_prefers_versioned_svg_output(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(
                td, IMG_TMPL.format(href="../images/old.png", w=400, h=300))
            _make_png(proj / "images" / "old.png", 800, 600)
            # 建立 svg_output_v4，并指向 v4 图片
            v4_dir = proj / "svg_output_v4"
            v4_dir.mkdir(parents=True)
            (v4_dir / "p1.svg").write_text(
                SVG_TMPL.format(images=IMG_TMPL.format(href="../images/v4.png", w=400, h=300)),
                encoding="utf-8",
            )
            _make_png(proj / "images" / "v4.png", 800, 600)
            rep = run_qa_assets(proj)
            self.assertTrue(rep["ok"])
            self.assertEqual(Path(rep["svg_dir"]).name, "svg_output_v4")

    def test_cli_from_subfolder_and_single_svg(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(
                td, IMG_TMPL.format(href="../images/good.png", w=400, h=300))
            (proj / "spec_lock.md").write_text("# Spec\n", encoding="utf-8")
            _make_png(proj / "images" / "good.png", 800, 600)
            self.assertEqual(main([str(proj / "svg_output")]), 0)
            self.assertEqual(main([str(proj / "svg_output" / "p1.svg")]), 0)

    def test_missing_pillow_warns(self):
        with patch("scripts.qa_assets._PIL_OK", False):
            with tempfile.TemporaryDirectory() as td:
                proj = self.make_project(
                    td, IMG_TMPL.format(href="../images/good.png", w=400, h=300))
                _make_png(proj / "images" / "good.png", 800, 600)
                rep = run_qa_assets(proj)
                self.assertTrue(rep["ok"])
                self.assertTrue(any("缺 Pillow" in w for w in rep["warnings"]))

    def test_find_svg_dir_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "my_proj"
            proj.mkdir()
            (proj / "images").mkdir()
            v3 = proj / "svg_output_v3"
            v3.mkdir()
            (v3 / "slide.svg").write_text("<svg></svg>", encoding="utf-8")
            with patch("scripts.qa_assets.find_svg_dir", None):
                found = _find_svg_dir(proj)
                self.assertEqual(found, v3)
                rep = run_qa_assets(proj)
                self.assertTrue(rep["ok"])
                self.assertEqual(rep["svg_dir"], str(v3))


if __name__ == "__main__":
    unittest.main()
