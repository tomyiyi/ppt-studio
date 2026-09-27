import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.deliver_preview import deliver_preview, main, validate_attestation_for_preview


def valid_attestation(**overrides):
    data = {
        "schema_version": 1,
        "overall": True,
        "stages": {name: {"ok": True} for name in ("image", "layout", "cards", "long_card")},
    }
    data.update(overrides)
    return data


class TestDeliverPreview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.attestation = self.root / "qa.json"
        self.output = self.root / "preview.html"
        self.attestation.write_text(json.dumps(valid_attestation()), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_attestation_calls_existing_builder_and_creates_html(self):
        with patch("scripts.deliver_preview.build_preview", return_value=self.output) as builder:
            result = deliver_preview(self.attestation, "svg_output", self.output)
        self.assertEqual(result, self.output)
        builder.assert_called_once_with(src="svg_output", out=self.output, title=None, cards=False, check=False)

    def test_missing_attestation_does_not_call_builder_or_create_output(self):
        with patch("scripts.deliver_preview.build_preview") as builder:
            with self.assertRaises(ValueError):
                deliver_preview(self.root / "missing.json", "svg_output", self.output)
        builder.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_invalid_json_does_not_call_builder(self):
        self.attestation.write_text("not json", encoding="utf-8")
        with patch("scripts.deliver_preview.build_preview") as builder:
            with self.assertRaises(ValueError):
                deliver_preview(self.attestation, "svg_output", self.output)
        builder.assert_not_called()

    def test_unsupported_schema_does_not_call_builder(self):
        self.attestation.write_text(json.dumps(valid_attestation(schema_version=2)), encoding="utf-8")
        with patch("scripts.deliver_preview.build_preview") as builder:
            with self.assertRaises(ValueError):
                deliver_preview(self.attestation, "svg_output", self.output)
        builder.assert_not_called()

    def test_overall_false_does_not_call_builder(self):
        self.attestation.write_text(json.dumps(valid_attestation(overall=False)), encoding="utf-8")
        with patch("scripts.deliver_preview.build_preview") as builder:
            with self.assertRaises(ValueError):
                deliver_preview(self.attestation, "svg_output", self.output)
        builder.assert_not_called()

    def test_failed_stage_blocks_even_when_overall_is_true_and_preserves_existing_output(self):
        data = valid_attestation()
        data["stages"]["cards"]["ok"] = False
        self.attestation.write_text(json.dumps(data), encoding="utf-8")
        self.output.write_text("existing-preview", encoding="utf-8")
        with patch("scripts.deliver_preview.build_preview") as builder:
            with self.assertRaises(ValueError):
                deliver_preview(self.attestation, "svg_output", self.output)
        builder.assert_not_called()
        self.assertEqual(self.output.read_text(encoding="utf-8"), "existing-preview")

    def test_validator_requires_all_four_stages(self):
        data = valid_attestation()
        del data["stages"]["long_card"]
        self.attestation.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(ValueError):
            validate_attestation_for_preview(self.attestation)

    def test_empty_output_raises_error(self):
        with self.assertRaises(ValueError):
            deliver_preview(self.attestation, "svg_output", "")

    def test_directory_output_raises_error(self):
        with self.assertRaises(IsADirectoryError):
            deliver_preview(self.attestation, "svg_output", self.root)


class TestDeliverPreviewCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.attestation = self.root / "qa.json"
        self.attestation.write_text(json.dumps(valid_attestation()), encoding="utf-8")
        self.output = self.root / "preview.html"

    def tearDown(self):
        self.temp.cleanup()

    def test_cli_positional_both(self):
        buf = io.StringIO()
        with patch("scripts.deliver_preview.build_preview", return_value=self.output) as builder:
            with redirect_stdout(buf):
                code = main(["projects/mock", str(self.output), "--attestation", str(self.attestation)])
        self.assertEqual(code, 0)
        builder.assert_called_once_with(src="projects/mock", out=str(self.output), title=None, cards=False, check=False)
        self.assertIn("[✓] 已交付翻页预览", buf.getvalue())

    def test_cli_flags_src_and_output(self):
        buf = io.StringIO()
        with patch("scripts.deliver_preview.build_preview", return_value=self.output) as builder:
            with redirect_stdout(buf):
                code = main([
                    "--attestation", str(self.attestation),
                    "--src", "projects/mock",
                    "--output", str(self.output),
                ])
        self.assertEqual(code, 0)
        builder.assert_called_once_with(src="projects/mock", out=str(self.output), title=None, cards=False, check=False)

    def test_cli_single_positional_html_output(self):
        buf = io.StringIO()
        with patch("scripts.deliver_preview.build_preview", return_value=self.output) as builder:
            with redirect_stdout(buf):
                code = main([str(self.output), "--attestation", str(self.attestation)])
        self.assertEqual(code, 0)
        builder.assert_called_once_with(src=None, out=str(self.output), title=None, cards=False, check=False)

    def test_cli_flag_src_positional_output(self):
        buf = io.StringIO()
        with patch("scripts.deliver_preview.build_preview", return_value=self.output) as builder:
            with redirect_stdout(buf):
                code = main(["--src", "projects/mock", str(self.output), "--attestation", str(self.attestation)])
        self.assertEqual(code, 0)
        builder.assert_called_once_with(src="projects/mock", out=str(self.output), title=None, cards=False, check=False)

    def test_cli_missing_output(self):
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = main(["--attestation", str(self.attestation)])
        self.assertEqual(code, 1)
        self.assertIn("[err] 交付翻页预览时必须指定输出路径", err_buf.getvalue())

    def test_cli_directory_output_fails(self):
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = main(["--attestation", str(self.attestation), "--output", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("[err] 交付目标不能是已存在目录", err_buf.getvalue())

    def test_cli_failed_attestation(self):
        failed = self.root / "failed.json"
        failed.write_text(json.dumps(valid_attestation(overall=False)), encoding="utf-8")
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = main(["--attestation", str(failed), "--output", str(self.output)])
        self.assertEqual(code, 1)
        self.assertIn("[err] QA_NOT_PASSED", err_buf.getvalue())

    def test_cli_cards_flag(self):
        with patch("scripts.deliver_preview.build_preview", return_value=self.output) as builder:
            with redirect_stdout(io.StringIO()):
                code = main([
                    "--attestation", str(self.attestation),
                    "--output", str(self.output),
                    "--cards",
                ])
        self.assertEqual(code, 0)
        builder.assert_called_once_with(src=None, out=str(self.output), title=None, cards=True, check=False)

    def test_cli_title_flag(self):
        with patch("scripts.deliver_preview.build_preview", return_value=self.output) as builder:
            with redirect_stdout(io.StringIO()):
                code = main([
                    "--attestation", str(self.attestation),
                    "--output", str(self.output),
                    "--title", "Custom Preview",
                ])
        self.assertEqual(code, 0)
        builder.assert_called_once_with(src=None, out=str(self.output), title="Custom Preview", cards=False, check=False)


if __name__ == "__main__":
    unittest.main()
