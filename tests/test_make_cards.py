import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from scripts.make_cards import make_cards


class TestMakeCardsAtomicOutput(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        (self.root / "svg_output").mkdir(parents=True)
        (self.root / "svg_output" / "01_cover.svg").write_text("<svg/>", encoding="utf-8")
        (self.root / "svg_output" / "02_detail.svg").write_text("<svg/>", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def patches(self, qa_result=True):
        return (
            patch("scripts.make_cards.parse_page", return_value=([], None, None)),
            patch("scripts.make_cards.pick", return_value={
                "primary": {"text": "主句"}, "kind": "statement", "metrics": [],
            }),
            patch("scripts.make_cards.card_svg", side_effect=lambda *args, **kwargs: f"<svg>{args[0]}</svg>"),
            patch("scripts.make_cards.run_qa_cards", return_value=qa_result),
        )

    def test_success_replaces_entire_cards_directory(self):
        out = self.root / "cards"
        out.mkdir()
        (out / "old.svg").write_text("old", encoding="utf-8")
        with ExitStack() as stack:
            for p in self.patches():
                stack.enter_context(p)
            result = make_cards(self.root, check=True)
        self.assertEqual(sorted(p.name for p in result), ["01_cover.svg", "02_detail.svg"])
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["01_cover.svg", "02_detail.svg"])
        self.assertFalse(any(p.name.startswith(".cards") for p in self.root.iterdir()))

    def test_qa_failure_preserves_old_directory_and_cleans_staging(self):
        out = self.root / "cards"
        out.mkdir()
        old = out / "old.svg"
        old.write_text("old", encoding="utf-8")
        with ExitStack() as stack:
            for p in self.patches(qa_result=False):
                stack.enter_context(p)
            with self.assertRaises(RuntimeError):
                make_cards(self.root, check=True)
        self.assertEqual(old.read_text(encoding="utf-8"), "old")
        self.assertEqual([p.name for p in out.iterdir()], ["old.svg"])
        self.assertFalse(any(p.name.startswith(".cards") for p in self.root.iterdir()))

    def test_only_preserves_unselected_existing_cards_until_commit(self):
        out = self.root / "cards"
        out.mkdir()
        (out / "02_detail.svg").write_text("old-detail", encoding="utf-8")
        with ExitStack() as stack:
            for p in self.patches():
                stack.enter_context(p)
            result = make_cards(self.root, only="01", check=False)
        self.assertEqual([p.name for p in result], ["01_cover.svg"])
        self.assertEqual((out / "02_detail.svg").read_text(encoding="utf-8"), "old-detail")


if __name__ == "__main__":
    unittest.main()
