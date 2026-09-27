import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.deliver_preview import deliver_preview, validate_attestation_for_preview


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


if __name__ == "__main__":
    unittest.main()
