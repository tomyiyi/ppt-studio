import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from scripts.deliver_project import deliver_artifact_set, deliver_project, load_valid_attestation, main


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


if __name__ == "__main__":
    unittest.main()
