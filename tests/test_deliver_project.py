import json
import tempfile
import unittest
from pathlib import Path

from scripts.deliver_project import deliver_project, load_valid_attestation


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


if __name__ == "__main__":
    unittest.main()
