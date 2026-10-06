import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.deliver_project import (
    deliver_artifact_set,
    deliver_project,
    load_valid_attestation,
    main,
    validate_delivered_artifact,
)


def valid_attestation(**overrides):
    data = {
        "schema_version": 1,
        "overall": True,
        "stages": {name: {"ok": True} for name in ("image", "layout", "cards", "long_card")},
    }
    data.update(overrides)
    return data


class TestDeliverProject(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.attestation = self.root / "qa.json"
        self.source = self.root / "source.mp4"
        self.destination = self.root / "published" / "source.mp4"
        self.source.write_bytes(b"artifact")

    def tearDown(self):
        self.temp.cleanup()

    def write_attestation(self, data):
        self.attestation.write_text(json.dumps(data), encoding="utf-8")

    def test_valid_attestation_allows_delivery(self):
        self.write_attestation(valid_attestation())
        self.assertEqual(deliver_project(self.attestation, self.source, self.destination), self.destination)
        self.assertEqual(self.destination.read_bytes(), b"artifact")

    def test_overall_false_blocks_without_destination(self):
        self.write_attestation(valid_attestation(overall=False))
        with self.assertRaises(ValueError):
            deliver_project(self.attestation, self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_additional_failed_stage_blocks_delivery(self):
        data = valid_attestation()
        data["stages"]["assets"] = {"ok": False}
        self.write_attestation(data)
        with self.assertRaises(ValueError) as ctx:
            deliver_project(self.attestation, self.source, self.destination)
        self.assertIn("QA attestation 存在未通过阶段", str(ctx.exception))
        self.assertFalse(self.destination.exists())

    def test_additional_passed_stage_allows_delivery(self):
        data = valid_attestation()
        data["stages"]["assets"] = {"ok": True}
        self.write_attestation(data)
        self.assertEqual(deliver_project(self.attestation, self.source, self.destination), self.destination)
        self.assertEqual(self.destination.read_bytes(), b"artifact")

    def test_failed_stage_blocks_without_destination(self):
        data = valid_attestation()
        data["stages"]["cards"]["ok"] = False
        self.write_attestation(data)
        with self.assertRaises(ValueError):
            deliver_project(self.attestation, self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_missing_attestation_fails_closed(self):
        with self.assertRaises(ValueError):
            deliver_project(self.attestation, self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_invalid_json_fails_closed(self):
        self.attestation.write_text("not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            deliver_project(self.attestation, self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_unsupported_schema_fails_closed(self):
        self.write_attestation(valid_attestation(schema_version=2))
        with self.assertRaises(ValueError):
            deliver_project(self.attestation, self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_missing_source_has_no_destination_side_effect(self):
        self.write_attestation(valid_attestation())
        with self.assertRaises(FileNotFoundError):
            deliver_project(self.attestation, self.root / "missing.mp4", self.destination)
        self.assertFalse(self.destination.exists())

    def test_empty_source_blocks_delivery(self):
        self.write_attestation(valid_attestation())
        empty_source = self.root / "empty.mp4"
        empty_source.write_bytes(b"")
        with self.assertRaises(ValueError) as ctx:
            deliver_project(self.attestation, empty_source, self.destination)
        self.assertIn("交付源产物为空文件 (0 字节)", str(ctx.exception))
        self.assertFalse(self.destination.exists())

    def test_deliver_project_with_check_success(self):
        self.write_attestation(valid_attestation())
        with patch("scripts.deliver_project.run_qa_video", return_value=True) as qa_mock:
            delivered = deliver_project(self.attestation, self.source, self.destination, check=True)
        self.assertEqual(delivered, self.destination)
        self.assertEqual(self.destination.read_bytes(), b"artifact")
        qa_mock.assert_called_once()

    def test_deliver_project_with_check_failure_raises_and_preserves_target(self):
        self.write_attestation(valid_attestation())
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        self.destination.write_bytes(b"existing-content")
        with patch("scripts.deliver_project.run_qa_video", return_value=False) as qa_mock:
            with self.assertRaises(RuntimeError) as ctx:
                deliver_project(self.attestation, self.source, self.destination, check=True)
        self.assertIn("产物客观质量门禁未通过", str(ctx.exception))
        self.assertEqual(self.destination.read_bytes(), b"existing-content")

    def test_deliver_project_srt_with_check_success(self):
        self.write_attestation(valid_attestation())
        srt_source = self.root / "source.srt"
        srt_dest = self.root / "published" / "source.srt"
        srt_source.write_bytes(b"1\n00:00:01,000 --> 00:00:02,000\nhi\n")
        with patch("scripts.deliver_project.run_qa_subtitles", return_value=True) as qa_mock:
            delivered = deliver_project(self.attestation, srt_source, srt_dest, check=True)
        self.assertEqual(delivered, srt_dest)
        self.assertTrue(srt_dest.is_file())
        qa_mock.assert_called_once()

    def card_sources(self):
        first = self.root / "01.svg"
        second = self.root / "02.svg"
        first.write_bytes(b"<svg>one</svg>")
        second.write_bytes(b"<svg>two</svg>")
        return [first, second]

    def test_artifact_set_copies_all_cards_and_replaces_directory(self):
        sources = self.card_sources()
        self.write_attestation(valid_attestation())
        destination = self.root / "cards"
        destination.mkdir()
        (destination / "old.svg").write_bytes(b"old")
        delivered = deliver_artifact_set(self.attestation, sources, destination)
        self.assertEqual([path.name for path in delivered], ["01.svg", "02.svg"])
        self.assertEqual(sorted(path.name for path in destination.iterdir()), ["01.svg", "02.svg"])
        self.assertEqual((destination / "01.svg").read_bytes(), sources[0].read_bytes())

    def test_artifact_set_missing_source_preserves_existing_directory(self):
        sources = self.card_sources()
        missing = self.root / "missing.svg"
        self.write_attestation(valid_attestation())
        destination = self.root / "cards"
        destination.mkdir()
        old = destination / "old.svg"
        old.write_bytes(b"old")
        with self.assertRaises(FileNotFoundError):
            deliver_artifact_set(self.attestation, [sources[0], missing], destination)
        self.assertEqual(old.read_bytes(), b"old")
        self.assertEqual([path.name for path in destination.iterdir()], ["old.svg"])

    def test_artifact_set_requires_cards_stage(self):
        self.write_attestation(valid_attestation())
        data = valid_attestation()
        data["stages"]["cards"]["ok"] = False
        self.write_attestation(data)
        with self.assertRaises(ValueError):
            deliver_artifact_set(self.attestation, self.card_sources(), self.root / "cards")

    def test_artifact_set_rejects_duplicate_source(self):
        source = self.card_sources()[0]
        self.write_attestation(valid_attestation())
        with self.assertRaises(ValueError):
            deliver_artifact_set(self.attestation, [source, source], self.root / "cards")

    def test_artifact_set_rejects_non_svg(self):
        source = self.root / "card.txt"
        source.write_text("not svg", encoding="utf-8")
        self.write_attestation(valid_attestation())
        with self.assertRaises(ValueError):
            deliver_artifact_set(self.attestation, [source], self.root / "cards")

    def test_empty_card_source_blocks_delivery(self):
        sources = self.card_sources()
        sources[0].write_bytes(b"")
        self.write_attestation(valid_attestation())
        with self.assertRaises(ValueError) as ctx:
            deliver_artifact_set(self.attestation, sources, self.root / "cards")
        self.assertIn("卡片源产物为空文件 (0 字节)", str(ctx.exception))

    def test_deliver_artifact_set_with_check_success(self):
        sources = self.card_sources()
        self.write_attestation(valid_attestation())
        destination = self.root / "cards"
        with patch("scripts.deliver_project.run_qa_cards", return_value=True) as qa_mock:
            delivered = deliver_artifact_set(self.attestation, sources, destination, check=True)
        self.assertEqual([path.name for path in delivered], ["01.svg", "02.svg"])
        self.assertTrue((destination / "01.svg").is_file())
        qa_mock.assert_called_once()

    def test_deliver_artifact_set_with_check_failure_preserves_existing_directory(self):
        sources = self.card_sources()
        self.write_attestation(valid_attestation())
        destination = self.root / "cards"
        destination.mkdir()
        (destination / "old.svg").write_bytes(b"old-card")
        with patch("scripts.deliver_project.run_qa_cards", return_value=False) as qa_mock:
            with self.assertRaises(RuntimeError) as ctx:
                deliver_artifact_set(self.attestation, sources, destination, check=True)
        self.assertIn("卡片集客观质量门禁未通过", str(ctx.exception))
        self.assertEqual((destination / "old.svg").read_bytes(), b"old-card")
        self.assertFalse((destination / "01.svg").exists())


class TestDeliverProjectCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.attestation = self.root / "qa.json"
        self.attestation.write_text(json.dumps(valid_attestation()), encoding="utf-8")
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"artifact")
        self.destination = self.root / "published" / "source.mp4"

    def tearDown(self):
        self.temp.cleanup()

    def test_cli_single_delivery_positional(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([str(self.source), str(self.destination), "--attestation", str(self.attestation)])
        self.assertEqual(code, 0)
        self.assertTrue(self.destination.is_file())
        self.assertEqual(self.destination.read_bytes(), b"artifact")
        self.assertIn("[✓] 已交付产物", buf.getvalue())

    def test_cli_single_delivery_flags(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([
                "--attestation", str(self.attestation),
                "--source", str(self.source),
                "--destination", str(self.destination),
            ])
        self.assertEqual(code, 0)
        self.assertTrue(self.destination.is_file())
        self.assertEqual(self.destination.read_bytes(), b"artifact")

    def test_cli_single_delivery_missing_source(self):
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = main([
                "--attestation", str(self.attestation),
                "--source", str(self.root / "missing.mp4"),
                "--destination", str(self.destination),
            ])
        self.assertEqual(code, 1)
        self.assertIn("[err]", err_buf.getvalue())
        self.assertFalse(self.destination.exists())

    def test_cli_single_delivery_missing_args(self):
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = main(["--attestation", str(self.attestation)])
        self.assertEqual(code, 1)
        self.assertIn("[err]", err_buf.getvalue())

    def test_cli_failed_attestation(self):
        failed_attestation = self.root / "failed_qa.json"
        failed_attestation.write_text(json.dumps(valid_attestation(overall=False)), encoding="utf-8")
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = main([str(self.source), str(self.destination), "--attestation", str(failed_attestation)])
        self.assertEqual(code, 1)
        self.assertIn("[err]", err_buf.getvalue())
        self.assertFalse(self.destination.exists())

    def test_cli_artifact_set_delivery(self):
        c1 = self.root / "01.svg"
        c2 = self.root / "02.svg"
        c1.write_bytes(b"<svg>1</svg>")
        c2.write_bytes(b"<svg>2</svg>")
        dest_dir = self.root / "cards_out"

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([
                "--attestation", str(self.attestation),
                "--sources", str(c1), str(c2),
                "--destination-dir", str(dest_dir),
            ])
        self.assertEqual(code, 0)
        self.assertTrue((dest_dir / "01.svg").is_file())
        self.assertTrue((dest_dir / "02.svg").is_file())
        self.assertIn("[✓] 已交付卡片集: 2 张", buf.getvalue())

    def test_cli_artifact_set_destination_fallback(self):
        c1 = self.root / "01.svg"
        c1.write_bytes(b"<svg>1</svg>")
        dest_dir = self.root / "cards_out2"

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([
                "--attestation", str(self.attestation),
                "--sources", str(c1),
                "--destination", str(dest_dir),
            ])
        self.assertEqual(code, 0)
        self.assertTrue((dest_dir / "01.svg").is_file())

    def test_cli_conflict_sources_and_source(self):
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = main([
                "--attestation", str(self.attestation),
                "--sources", str(self.source),
                "--source", str(self.source),
                "--destination-dir", str(self.root / "out"),
            ])
        self.assertEqual(code, 1)
        self.assertIn("不能同时指定单一产物与卡片集交付源", err_buf.getvalue())

    def test_cli_artifact_set_missing_dest(self):
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = main([
                "--attestation", str(self.attestation),
                "--sources", str(self.source),
            ])
        self.assertEqual(code, 1)
        self.assertIn("交付卡片集时必须指定", err_buf.getvalue())

    def test_cli_single_delivery_check_flag(self):
        buf = io.StringIO()
        with patch("scripts.deliver_project.run_qa_video", return_value=True) as qa_mock:
            with redirect_stdout(buf):
                code = main([
                    "--attestation", str(self.attestation),
                    "--source", str(self.source),
                    "--destination", str(self.destination),
                    "--check",
                ])
        self.assertEqual(code, 0)
        self.assertTrue(self.destination.is_file())
        self.assertIn("[✓] 已交付产物", buf.getvalue())
        qa_mock.assert_called_once()

    def test_cli_single_delivery_check_failure(self):
        err_buf = io.StringIO()
        with patch("scripts.deliver_project.run_qa_video", return_value=False):
            with redirect_stderr(err_buf):
                code = main([
                    "--attestation", str(self.attestation),
                    "--source", str(self.source),
                    "--destination", str(self.destination),
                    "--check",
                ])
        self.assertEqual(code, 1)
        self.assertIn("[err] 产物客观质量门禁未通过", err_buf.getvalue())
        self.assertFalse(self.destination.exists())

    def test_cli_artifact_set_delivery_check_flag(self):
        c1 = self.root / "01.svg"
        c2 = self.root / "02.svg"
        c1.write_bytes(b"<svg>1</svg>")
        c2.write_bytes(b"<svg>2</svg>")
        dest_dir = self.root / "cards_checked_out"
        buf = io.StringIO()
        with patch("scripts.deliver_project.run_qa_cards", return_value=True) as qa_mock:
            with redirect_stdout(buf):
                code = main([
                    "--attestation", str(self.attestation),
                    "--sources", str(c1), str(c2),
                    "--destination-dir", str(dest_dir),
                    "--check",
                ])
        self.assertEqual(code, 0)
        self.assertTrue((dest_dir / "01.svg").is_file())
        self.assertIn("[✓] 已交付卡片集: 2 张", buf.getvalue())
        qa_mock.assert_called_once()

    def test_cli_artifact_set_delivery_check_failure(self):
        c1 = self.root / "01.svg"
        c1.write_bytes(b"<svg>1</svg>")
        dest_dir = self.root / "cards_checked_fail"
        err_buf = io.StringIO()
        with patch("scripts.deliver_project.run_qa_cards", return_value=False):
            with redirect_stderr(err_buf):
                code = main([
                    "--attestation", str(self.attestation),
                    "--sources", str(c1),
                    "--destination-dir", str(dest_dir),
                    "--check",
                ])
        self.assertEqual(code, 1)
        self.assertIn("[err] 卡片集客观质量门禁未通过", err_buf.getvalue())
        self.assertFalse(dest_dir.exists())

    def test_cli_verbose_flag_single_delivery(self):
        buf = io.StringIO()
        with patch("scripts.deliver_project.run_qa_video", return_value=True) as qa_mock:
            with redirect_stdout(buf):
                code = main([
                    "--attestation", str(self.attestation),
                    "--source", str(self.source),
                    "--destination", str(self.destination),
                    "--check",
                    "--verbose",
                ])
        self.assertEqual(code, 0)
        self.assertTrue(self.destination.is_file())
        # QA 在原子移动前对临时文件执行（实现：先校验临时文件再 os.replace），
        # 因此断言 mock 以临时文件路径（而非目标路径）被调用一次。
        qa_mock.assert_called_once()
        qa_path = Path(qa_mock.call_args[0][0])
        self.assertNotEqual(qa_path, self.destination)
        self.assertEqual(qa_path.parent, self.destination.parent)
        self.assertTrue(qa_path.name.startswith(f".{self.destination.name}."))
        self.assertTrue(qa_mock.call_args[1].get("verbose"))

    def test_cli_verbose_flag_artifact_set(self):
        c1 = self.root / "01.svg"
        c1.write_bytes(b"<svg>1</svg>")
        dest_dir = self.root / "cards_verbose_out"
        buf = io.StringIO()
        with patch("scripts.deliver_project.run_qa_cards", return_value=True) as qa_mock:
            with redirect_stdout(buf):
                code = main([
                    "--attestation", str(self.attestation),
                    "--sources", str(c1),
                    "--destination-dir", str(dest_dir),
                    "--check",
                    "-v",
                ])
        self.assertEqual(code, 0)
        self.assertTrue((dest_dir / "01.svg").is_file())
        qa_mock.assert_called_once()
        self.assertTrue(qa_mock.call_args[1].get("verbose"))


class TestValidateDeliveredArtifact(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_validates_pptx(self):
        f = self.root / "deck.pptx"
        f.write_bytes(b"pptx")
        with patch("scripts.deliver_project.run_qa_pptx", return_value=True) as qa_mock:
            validate_delivered_artifact(f)
        qa_mock.assert_called_once_with(f, verbose=False)

    def test_validates_png(self):
        f = self.root / "long.png"
        f.write_bytes(b"png")
        with patch("scripts.deliver_project.run_qa_long_card", return_value=True) as qa_mock:
            validate_delivered_artifact(f)
        qa_mock.assert_called_once_with(f, verbose=False)

    def test_validates_html(self):
        f = self.root / "preview.html"
        f.write_bytes(b"html")
        with patch("scripts.deliver_project.run_qa_preview", return_value=True) as qa_mock:
            validate_delivered_artifact(f)
        qa_mock.assert_called_once_with(f, verbose=False)

    def test_validates_svg(self):
        f = self.root / "slide.svg"
        f.write_bytes(b"svg")
        with patch("scripts.deliver_project.run_qa_layout", return_value=True) as qa_mock:
            validate_delivered_artifact(f)
        qa_mock.assert_called_once_with(f, verbose=False)

    def test_validates_srt(self):
        f = self.root / "timeline.srt"
        f.write_bytes(b"srt")
        with patch("scripts.deliver_project.run_qa_subtitles", return_value=True) as qa_mock:
            validate_delivered_artifact(f)
        qa_mock.assert_called_once_with(f, verbose=False)

    def test_validates_srt_failure(self):
        f = self.root / "timeline.srt"
        f.write_bytes(b"bad-srt")
        with patch("scripts.deliver_project.run_qa_subtitles", return_value=False) as qa_mock:
            with self.assertRaises(RuntimeError) as ctx:
                validate_delivered_artifact(f)
        self.assertIn("产物客观质量门禁未通过", str(ctx.exception))

    def test_unknown_extension_passes(self):
        f = self.root / "data.json"
        f.write_bytes(b"{}")
        validate_delivered_artifact(f)

    def test_validate_delivered_artifact_empty_file_fails(self):
        f = self.root / "empty.unknown"
        f.write_bytes(b"")
        with self.assertRaises(RuntimeError) as ctx:
            validate_delivered_artifact(f)
        self.assertIn("产物客观质量门禁未通过", str(ctx.exception))
        self.assertIn("0 字节", str(ctx.exception))

    def test_validate_delivered_artifact_forwards_verbose(self):
        f = self.root / "deck.pptx"
        f.write_bytes(b"pptx")
        with patch("scripts.deliver_project.run_qa_pptx", return_value=True) as qa_mock:
            validate_delivered_artifact(f, verbose=True)
        qa_mock.assert_called_once_with(f, verbose=True)

    def test_validate_delivered_artifact_with_base_dir(self):
        proj = self.root / "subproj"
        proj.mkdir()
        f = proj / "deck.pptx"
        f.write_bytes(b"pptx")
        with patch("scripts.deliver_project.run_qa_pptx", return_value=True) as qa_mock:
            validate_delivered_artifact("deck.pptx", base_dir=proj)
        qa_mock.assert_called_once_with(f.resolve(), verbose=False, base_dir=proj.resolve())

    def test_validate_delivered_artifact_forwards_base_dir(self):
        proj = self.root / "subproj2"
        proj.mkdir()

        png_file = proj / "long.png"
        png_file.write_bytes(b"png")
        with patch("scripts.deliver_project.run_qa_long_card", return_value=True) as mock_lc:
            validate_delivered_artifact("long.png", base_dir=proj)
            mock_lc.assert_called_once_with(png_file.resolve(), verbose=False, base_dir=proj.resolve())

        html_file = proj / "preview.html"
        html_file.write_bytes(b"html")
        with patch("scripts.deliver_project.run_qa_preview", return_value=True) as mock_prev:
            validate_delivered_artifact("preview.html", base_dir=proj)
            mock_prev.assert_called_once_with(html_file.resolve(), verbose=False, base_dir=proj.resolve())

        svg_file = proj / "slide.svg"
        svg_file.write_bytes(b"<svg></svg>")
        with patch("scripts.deliver_project.run_qa_layout", return_value=True) as mock_layout:
            validate_delivered_artifact("slide.svg", base_dir=proj)
            mock_layout.assert_called_once_with(svg_file.resolve(), verbose=False, base_dir=proj.resolve())

        mp4_file = proj / "video.mp4"
        mp4_file.write_bytes(b"mp4")
        with patch("scripts.deliver_project.run_qa_video", return_value=True) as mock_video:
            validate_delivered_artifact("video.mp4", base_dir=proj)
            mock_video.assert_called_once_with(mp4_file.resolve(), verbose=False, base_dir=proj.resolve())

        srt_file = proj / "sub.srt"
        srt_file.write_bytes(b"1\n00:00:01,000 --> 00:00:02,000\nhi\n")
        with patch("scripts.deliver_project.run_qa_subtitles", return_value=True) as mock_srt:
            validate_delivered_artifact("sub.srt", base_dir=proj)
            mock_srt.assert_called_once_with(srt_file.resolve(), verbose=False, base_dir=proj.resolve())


class TestDeliverProjectBaseDir(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.proj = self.root / "proj_base"
        self.proj.mkdir()
        self.attestation = self.proj / "qa.json"
        self.attestation.write_text(json.dumps(valid_attestation()), encoding="utf-8")
        self.source = self.proj / "video.mp4"
        self.source.write_bytes(b"sample video bytes")

    def tearDown(self):
        self.temp.cleanup()

    def test_load_valid_attestation_with_base_dir(self):
        data = load_valid_attestation("qa.json", base_dir=self.proj)
        self.assertEqual(data["schema_version"], 1)

    def test_deliver_project_relative_paths_with_base_dir(self):
        out = deliver_project("qa.json", "video.mp4", "out/video.mp4", base_dir=self.proj)
        self.assertEqual(out, (self.proj / "out/video.mp4").resolve())
        self.assertTrue(out.is_file())
        self.assertEqual(out.read_bytes(), b"sample video bytes")

    def test_deliver_artifact_set_relative_paths_with_base_dir(self):
        c1 = self.proj / "01.svg"
        c2 = self.proj / "02.svg"
        c1.write_bytes(b"<svg>card 1</svg>")
        c2.write_bytes(b"<svg>card 2</svg>")
        out = deliver_artifact_set(
            "qa.json",
            ["01.svg", "02.svg"],
            "cards_delivered",
            base_dir=self.proj,
        )
        self.assertEqual(len(out), 2)
        target_dir = (self.proj / "cards_delivered").resolve()
        self.assertTrue((target_dir / "01.svg").is_file())
        self.assertTrue((target_dir / "02.svg").is_file())

    def test_deliver_artifact_set_with_check_forwards_base_dir(self):
        c1 = self.proj / "01.svg"
        c2 = self.proj / "02.svg"
        c1.write_bytes(b"<svg>card 1</svg>")
        c2.write_bytes(b"<svg>card 2</svg>")
        with patch("scripts.deliver_project.run_qa_cards", return_value=True) as mock_cards:
            out = deliver_artifact_set(
                "qa.json",
                ["01.svg", "02.svg"],
                "cards_checked",
                check=True,
                base_dir=self.proj,
            )
            self.assertEqual(len(out), 2)
            mock_cards.assert_called_once()
            _, kwargs = mock_cards.call_args
            self.assertEqual(kwargs.get("base_dir"), self.proj.resolve())

    def test_main_single_delivery_with_base_dir(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(
                ["video.mp4", "published/video.mp4", "--attestation", "qa.json"],
                base_dir=self.proj,
            )
        self.assertEqual(code, 0)
        delivered_path = self.proj / "published/video.mp4"
        self.assertTrue(delivered_path.is_file())
        self.assertEqual(delivered_path.read_bytes(), b"sample video bytes")

    def test_main_artifact_set_with_base_dir(self):
        c1 = self.proj / "01.svg"
        c2 = self.proj / "02.svg"
        c1.write_bytes(b"<svg>card 1</svg>")
        c2.write_bytes(b"<svg>card 2</svg>")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(
                [
                    "--attestation", "qa.json",
                    "--sources", "01.svg", "02.svg",
                    "--destination-dir", "cards_cli_out",
                ],
                base_dir=self.proj,
            )
        self.assertEqual(code, 0)
        target_dir = self.proj / "cards_cli_out"
        self.assertTrue((target_dir / "01.svg").is_file())
        self.assertTrue((target_dir / "02.svg").is_file())

    def test_main_single_delivery_with_base_dir_flag(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(
                [
                    "video.mp4",
                    "published/video_flag.mp4",
                    "--attestation",
                    "qa.json",
                    "--base-dir",
                    str(self.proj),
                ]
            )
        self.assertEqual(code, 0)
        delivered_path = self.proj / "published/video_flag.mp4"
        self.assertTrue(delivered_path.is_file())
        self.assertEqual(delivered_path.read_bytes(), b"sample video bytes")

    def test_main_artifact_set_with_base_dir_flag(self):
        c1 = self.proj / "c1.svg"
        c2 = self.proj / "c2.svg"
        c1.write_bytes(b"<svg>c1</svg>")
        c2.write_bytes(b"<svg>c2</svg>")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(
                [
                    "--attestation",
                    "qa.json",
                    "--sources",
                    "c1.svg",
                    "c2.svg",
                    "--destination-dir",
                    "cards_flag_out",
                    "--base-dir",
                    str(self.proj),
                ]
            )
        self.assertEqual(code, 0)
        target_dir = self.proj / "cards_flag_out"
        self.assertTrue((target_dir / "c1.svg").is_file())
        self.assertTrue((target_dir / "c2.svg").is_file())


class TestDeliverProjectModuleFaultTolerance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_validate_delivered_artifact_missing_modules_raise(self):
        mp4_file = self.root / "sample.mp4"
        mp4_file.write_bytes(b"video")
        with patch("scripts.deliver_project.run_qa_video", None):
            with self.assertRaises(RuntimeError) as cm:
                validate_delivered_artifact(mp4_file)
            self.assertIn("qa_video", str(cm.exception))

        pptx_file = self.root / "sample.pptx"
        pptx_file.write_bytes(b"pptx")
        with patch("scripts.deliver_project.run_qa_pptx", None):
            with self.assertRaises(RuntimeError) as cm:
                validate_delivered_artifact(pptx_file)
            self.assertIn("qa_pptx", str(cm.exception))

        png_file = self.root / "sample.png"
        png_file.write_bytes(b"png")
        with patch("scripts.deliver_project.run_qa_long_card", None):
            with self.assertRaises(RuntimeError) as cm:
                validate_delivered_artifact(png_file)
            self.assertIn("qa_long_card", str(cm.exception))

        html_file = self.root / "sample.html"
        html_file.write_bytes(b"html")
        with patch("scripts.deliver_project.run_qa_preview", None):
            with self.assertRaises(RuntimeError) as cm:
                validate_delivered_artifact(html_file)
            self.assertIn("qa_preview", str(cm.exception))

        svg_file = self.root / "sample.svg"
        svg_file.write_bytes(b"<svg></svg>")
        with patch("scripts.deliver_project.run_qa_layout", None):
            with self.assertRaises(RuntimeError) as cm:
                validate_delivered_artifact(svg_file)
            self.assertIn("qa_layout", str(cm.exception))

        srt_file = self.root / "sample.srt"
        srt_file.write_bytes(b"1\n00:00:01,000 --> 00:00:02,000\nhi\n")
        with patch("scripts.deliver_project.run_qa_subtitles", None):
            with self.assertRaises(RuntimeError) as cm:
                validate_delivered_artifact(srt_file)
            self.assertIn("qa_video", str(cm.exception))

    def test_deliver_artifact_set_check_missing_cards_module_raises(self):
        attestation = self.root / "qa.json"
        attestation.write_text(json.dumps(valid_attestation()), encoding="utf-8")
        c1 = self.root / "c1.svg"
        c1.write_bytes(b"<svg></svg>")
        dest = self.root / "cards"
        with patch("scripts.deliver_project.run_qa_cards", None):
            with self.assertRaises(RuntimeError) as cm:
                deliver_artifact_set(attestation, [c1], dest, check=True)
            self.assertIn("qa_cards", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
