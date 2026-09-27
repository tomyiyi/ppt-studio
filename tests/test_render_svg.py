#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_render_svg.py
========================
测试 render_svg.py 的 viewBox 尺寸解析、图片内联、安全项目发现与 CLI 流程。
使用临时目录与标准库 unittest，不引入额外外部依赖。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# 将项目根目录加入 sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.render_svg import (
    svg_size,
    inline_images,
    resolve_targets,
    resolve_chrome,
    render_svg,
    main,
)


def create_minimal_svg(path: Path, width: int = 1280, height: int = 720) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="#0B0C12"/>'
        f'</svg>',
        encoding="utf-8",
    )


class TestSvgSize(unittest.TestCase):
    def test_standard_viewbox(self):
        svg = '<svg viewBox="0 0 1280 720"></svg>'
        self.assertEqual(svg_size(svg), (1280, 720))

    def test_card_viewbox(self):
        svg = '<svg viewBox="0 0 1080 1350"></svg>'
        self.assertEqual(svg_size(svg), (1080, 1350))

    def test_comma_delimited_viewbox(self):
        svg1 = '<svg viewBox="0, 0, 1080, 1350"></svg>'
        self.assertEqual(svg_size(svg1), (1080, 1350))
        svg2 = '<svg viewBox="0,0,1920,1080"></svg>'
        self.assertEqual(svg_size(svg2), (1920, 1080))

    def test_single_quoted_viewbox(self):
        svg = "<svg viewBox='0 0 1080 1350'></svg>"
        self.assertEqual(svg_size(svg), (1080, 1350))

    def test_fallback_to_width_height_attributes(self):
        svg1 = '<svg width="1080" height="1350"><circle cx="10" cy="10" r="5"/></svg>'
        self.assertEqual(svg_size(svg1), (1080, 1350))
        svg2 = '<svg width="1920px" height="1080px"></svg>'
        self.assertEqual(svg_size(svg2), (1920, 1080))

    def test_fallback_default_when_missing(self):
        svg = '<svg><text>Hello</text></svg>'
        self.assertEqual(svg_size(svg), (1280, 720))


class TestInlineImages(unittest.TestCase):
    def test_standard_href_inlining(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            img_file = td / "photo.png"
            img_file.write_bytes(b"\x89PNG\r\n\x1a\nfakeimagecontent")

            svg_text = '<svg><image href="photo.png" width="100" height="100"/></svg>'
            inlined = inline_images(svg_text, td)
            self.assertIn("data:image/png;base64,", inlined)
            self.assertNotIn('href="photo.png"', inlined)

    def test_xlink_href_single_quotes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            img_file = td / "hero.png"
            img_file.write_bytes(b"\x89PNG\r\n\x1a\nherocontent")

            svg_text = "<svg><image xlink:href='hero.png' width='200' height='200'/></svg>"
            inlined = inline_images(svg_text, td)
            self.assertIn("data:image/png;base64,", inlined)
            self.assertNotIn("hero.png", inlined)

    def test_already_data_uri_unmodified(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg_text = '<svg><image href="data:image/png;base64,AAAA" width="50" height="50"/></svg>'
            inlined = inline_images(svg_text, td)
            self.assertEqual(inlined, svg_text)

    def test_missing_image_retained_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg_text = '<svg><image href="missing.png" width="50" height="50"/></svg>'
            inlined = inline_images(svg_text, td)
            self.assertEqual(inlined, svg_text)


class TestResolveTargets(unittest.TestCase):
    def test_explicit_svg_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg = td / "svg_output" / "01_cover.svg"
            create_minimal_svg(svg)

            files, out = resolve_targets(str(svg), base_dir=td)
            self.assertEqual(files, [svg.resolve()])
            self.assertEqual(out, (td / "render").resolve())

    def test_explicit_svg_file_with_custom_out(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg = td / "slide.svg"
            create_minimal_svg(svg)
            custom_out = td / "custom_out.png"

            files, out = resolve_targets(str(svg), str(custom_out), base_dir=td)
            self.assertEqual(files, [svg.resolve()])
            self.assertEqual(out, custom_out.resolve())

    def test_explicit_directory_svg_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg1 = td / "svg_output" / "01.svg"
            svg2 = td / "svg_output" / "02.svg"
            create_minimal_svg(svg1)
            create_minimal_svg(svg2)

            files, out = resolve_targets(str(td / "svg_output"), base_dir=td)
            self.assertEqual(files, [svg1.resolve(), svg2.resolve()])
            self.assertEqual(out, (td / "render").resolve())

    def test_explicit_directory_cards(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            card1 = td / "cards" / "01_card.svg"
            create_minimal_svg(card1)

            files, out = resolve_targets(str(td / "cards"), base_dir=td)
            self.assertEqual(files, [card1.resolve()])
            self.assertEqual(out, (td / "render_cards").resolve())

    def test_explicit_project_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            proj = td / "my-project"
            svg1 = proj / "svg_output" / "cover.svg"
            create_minimal_svg(svg1)

            files, out = resolve_targets(str(proj), base_dir=td)
            self.assertEqual(files, [svg1.resolve()])
            self.assertEqual(out, (proj / "render").resolve())

    def test_auto_discovery_from_projects_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            proj = td / "projects" / "unique-proj"
            svg = proj / "svg_output" / "01.svg"
            create_minimal_svg(svg)

            files, out = resolve_targets(None, base_dir=td)
            self.assertEqual(files, [svg.resolve()])
            self.assertEqual(out, (proj / "render").resolve())

    def test_auto_discovery_multiple_projects_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            p1 = td / "projects" / "proj1"
            p2 = td / "projects" / "proj2"
            create_minimal_svg(p1 / "svg_output" / "01.svg")
            create_minimal_svg(p2 / "svg_output" / "01.svg")

            with self.assertRaises(ValueError) as ctx:
                resolve_targets(None, base_dir=td)
            self.assertIn("发现多个", str(ctx.exception))

    def test_nonexistent_src_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            with self.assertRaises(FileNotFoundError):
                resolve_targets("non_existent_folder", base_dir=td)


class TestResolveChrome(unittest.TestCase):
    def test_env_var_override(self):
        with tempfile.NamedTemporaryFile() as tf:
            with patch.dict(os.environ, {"CHROME_PATH": tf.name}):
                self.assertEqual(resolve_chrome(), tf.name)


class TestMainCLI(unittest.TestCase):
    @patch("scripts.render_svg.render_one")
    def test_cli_success(self, mock_render_one):
        mock_render_one.return_value = True
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg = td / "01_test.svg"
            create_minimal_svg(svg)
            out_dir = td / "out"

            ret = main([str(svg), str(out_dir), "--scale", "1.5"])
            self.assertEqual(ret, 0)
            mock_render_one.assert_called_once()
            args, kwargs = mock_render_one.call_args
            self.assertEqual(args[0], svg.resolve())
            self.assertEqual(args[1], out_dir.resolve() / "01_test.png")
            self.assertEqual(args[2], 1.5)

    @patch("scripts.render_svg.render_one")
    def test_cli_single_png_out(self, mock_render_one):
        mock_render_one.return_value = True
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg = td / "01_test.svg"
            create_minimal_svg(svg)
            out_png = td / "custom.png"

            ret = main([str(svg), str(out_png)])
            self.assertEqual(ret, 0)
            mock_render_one.assert_called_once()
            args, _ = mock_render_one.call_args
            self.assertEqual(args[1], out_png.resolve())

    @patch("scripts.render_svg.render_one")
    def test_cli_only_filter(self, mock_render_one):
        mock_render_one.return_value = True
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg1 = td / "01_cover.svg"
            svg2 = td / "02_detail.svg"
            create_minimal_svg(svg1)
            create_minimal_svg(svg2)
            out_dir = td / "out"

            ret = main([str(td), str(out_dir), "--only", "02_detail"])
            self.assertEqual(ret, 0)
            self.assertEqual(mock_render_one.call_count, 1)

    def test_cli_nonexistent_src(self):
        ret = main(["/non_existent_path_12345"])
        self.assertEqual(ret, 2)

    @patch("scripts.render_svg.render_one")
    @patch("scripts.render_svg.run_qa_layout")
    def test_cli_check_success(self, mock_qa_layout, mock_render_one):
        mock_render_one.return_value = True
        mock_qa_layout.return_value = True
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg = td / "01_test.svg"
            create_minimal_svg(svg)
            out_dir = td / "out"

            ret = main([str(svg), str(out_dir), "--check"])
            self.assertEqual(ret, 0)
            mock_qa_layout.assert_called_once()

    @patch("scripts.render_svg.render_one")
    @patch("scripts.render_svg.run_qa_layout")
    def test_cli_check_failure(self, mock_qa_layout, mock_render_one):
        mock_render_one.return_value = True
        mock_qa_layout.return_value = False
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg = td / "01_test.svg"
            create_minimal_svg(svg)
            out_dir = td / "out"

            ret = main([str(svg), str(out_dir), "--check"])
            self.assertEqual(ret, 1)

    @patch("scripts.render_svg.render_one")
    @patch("scripts.render_svg.run_qa_layout")
    def test_cli_spec_argument(self, mock_qa_layout, mock_render_one):
        mock_render_one.return_value = True
        mock_qa_layout.return_value = True
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg = td / "01_test.svg"
            spec = td / "custom_spec.md"
            spec.write_text("# Spec", encoding="utf-8")
            create_minimal_svg(svg)
            out_dir = td / "out"

            ret = main([str(svg), str(out_dir), "--check", "--spec", str(spec)])
            self.assertEqual(ret, 0)
            _, kwargs = mock_qa_layout.call_args
            self.assertEqual(kwargs["spec_path"], str(spec))


class TestRenderSvgProgrammatic(unittest.TestCase):
    @patch("scripts.render_svg.render_one")
    def test_render_svg_basic(self, mock_render_one):
        mock_render_one.return_value = True
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg1 = td / "01_cover.svg"
            svg2 = td / "02_detail.svg"
            create_minimal_svg(svg1)
            create_minimal_svg(svg2)
            out_dir = td / "render"

            res = render_svg(src=td, out=out_dir)
            self.assertEqual(len(res), 2)
            self.assertEqual(mock_render_one.call_count, 2)
            self.assertIn(out_dir.resolve() / "01_cover.png", res)
            self.assertIn(out_dir.resolve() / "02_detail.png", res)

    @patch("scripts.render_svg.render_one")
    def test_render_svg_only_filter(self, mock_render_one):
        mock_render_one.return_value = True
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg1 = td / "01_cover.svg"
            svg2 = td / "02_detail.svg"
            create_minimal_svg(svg1)
            create_minimal_svg(svg2)

            res = render_svg(src=td, only="detail")
            self.assertEqual(len(res), 1)
            self.assertTrue(res[0].name.endswith("02_detail.png"))

    @patch("scripts.render_svg.render_one")
    def test_render_svg_single_png_out(self, mock_render_one):
        mock_render_one.return_value = True
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg = td / "01_cover.svg"
            create_minimal_svg(svg)
            custom_out = td / "custom.png"

            res = render_svg(src=svg, out=custom_out)
            self.assertEqual(res, [custom_out.resolve()])

    def test_render_svg_nonexistent_src_raises(self):
        with self.assertRaises(FileNotFoundError):
            render_svg(src="/non_existent_path_xyz")

    @patch("scripts.render_svg.render_one")
    def test_render_svg_no_matching_only_raises(self, mock_render_one):
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg = td / "01_cover.svg"
            create_minimal_svg(svg)
            with self.assertRaises(FileNotFoundError):
                render_svg(src=td, only="not_found")

    @patch("scripts.render_svg.render_one")
    def test_render_svg_failure_raises_runtime_error(self, mock_render_one):
        mock_render_one.side_effect = RuntimeError("Playwright error")
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg = td / "01_cover.svg"
            create_minimal_svg(svg)
            with self.assertRaises(RuntimeError) as ctx:
                render_svg(src=td)
            self.assertIn("Playwright error", str(ctx.exception))


class TestRenderSvgQualityGates(unittest.TestCase):
    @patch("scripts.render_svg.render_one")
    @patch("scripts.render_svg.run_qa_layout")
    def test_slides_quality_gate_pass(self, mock_qa_layout, mock_render_one):
        mock_render_one.return_value = True
        mock_qa_layout.return_value = True
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg_dir = td / "svg_output"
            svg1 = svg_dir / "01_cover.svg"
            svg2 = svg_dir / "02_detail.svg"
            create_minimal_svg(svg1)
            create_minimal_svg(svg2)

            res = render_svg(src=svg_dir, check=True)
            self.assertEqual(len(res), 2)
            mock_qa_layout.assert_called_once()
            args, kwargs = mock_qa_layout.call_args
            self.assertEqual(args[0], svg_dir.resolve())
            self.assertEqual(kwargs["render_dir"], (td / "render").resolve())

    @patch("scripts.render_svg.render_one")
    @patch("scripts.render_svg.run_qa_layout")
    def test_slides_quality_gate_fail(self, mock_qa_layout, mock_render_one):
        mock_render_one.return_value = True
        mock_qa_layout.return_value = False
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg_dir = td / "svg_output"
            svg = svg_dir / "01_cover.svg"
            create_minimal_svg(svg)

            with self.assertRaises(RuntimeError) as ctx:
                render_svg(src=svg_dir, check=True)
            self.assertIn("SVG 版面客观质量门禁未通过", str(ctx.exception))

    @patch("scripts.render_svg.render_one")
    @patch("scripts.render_svg.run_qa_cards")
    def test_cards_quality_gate_pass(self, mock_qa_cards, mock_render_one):
        mock_render_one.return_value = True
        mock_qa_cards.return_value = True
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            card_dir = td / "cards"
            card1 = card_dir / "01_card.svg"
            create_minimal_svg(card1)

            res = render_svg(src=card_dir, check=True)
            self.assertEqual(len(res), 1)
            mock_qa_cards.assert_called_once()
            args, kwargs = mock_qa_cards.call_args
            self.assertEqual(args[0], card_dir.resolve())
            self.assertEqual(kwargs["render_dir"], (td / "render_cards").resolve())

    @patch("scripts.render_svg.render_one")
    @patch("scripts.render_svg.run_qa_cards")
    def test_cards_quality_gate_fail(self, mock_qa_cards, mock_render_one):
        mock_render_one.return_value = True
        mock_qa_cards.return_value = False
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            card_dir = td / "cards"
            card1 = card_dir / "01_card.svg"
            create_minimal_svg(card1)

            with self.assertRaises(RuntimeError) as ctx:
                render_svg(src=card_dir, check=True)
            self.assertIn("卡片客观质量门禁未通过", str(ctx.exception))

    @patch("scripts.render_svg.render_one")
    @patch("scripts.render_svg.run_qa_layout")
    def test_spec_forwarding(self, mock_qa_layout, mock_render_one):
        mock_render_one.return_value = True
        mock_qa_layout.return_value = True
        with tempfile.TemporaryDirectory() as tmp_dir:
            td = Path(tmp_dir)
            svg = td / "01_test.svg"
            create_minimal_svg(svg)
            spec = td / "spec_lock.md"
            spec.write_text("# Spec", encoding="utf-8")

            render_svg(src=svg, check=True, spec_path=str(spec))
            _, kwargs = mock_qa_layout.call_args
            self.assertEqual(kwargs["spec_path"], str(spec))


if __name__ == "__main__":
    unittest.main()
