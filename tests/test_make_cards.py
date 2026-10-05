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

    def test_versioned_svg_output_prioritized(self):
        v3 = self.root / "svg_output_v3"
        v3.mkdir()
        (v3 / "01_v3.svg").write_text("<svg/>", encoding="utf-8")
        with ExitStack() as stack:
            for p in self.patches():
                stack.enter_context(p)
            result = make_cards(self.root, check=False)
        self.assertEqual([p.name for p in result], ["01_v3.svg"])

    def test_load_spec_colors_prioritizes_versioned_spec_lock(self):
        from scripts.make_cards import load_spec_colors
        (self.root / "spec_lock.md").write_text("## colors\n- accent: #111111\n", encoding="utf-8")
        (self.root / "spec_lock_v2.md").write_text("## colors\n- accent: #22C55E\n", encoding="utf-8")
        colors = load_spec_colors(self.root)
        self.assertEqual(colors["accent"], "#22C55E")

    def test_resolve_project_dir_auto_discovery_versioned(self):
        from scripts.make_cards import resolve_project_dir
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "projects" / "my_proj"
            (proj / "svg_output_v2").mkdir(parents=True)
            (proj / "svg_output_v2" / "01.svg").write_text("<svg/>", encoding="utf-8")
            resolved = resolve_project_dir(base_dir=base)
            self.assertEqual(resolved, proj.resolve())

    def test_resolve_project_dir_explicit_subfolders_and_file(self):
        from scripts.make_cards import resolve_project_dir
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "custom_proj"
            (proj / "svg_output").mkdir(parents=True)
            (proj / "svg_output" / "01.svg").write_text("<svg/>", encoding="utf-8")
            spec = proj / "spec_lock.md"
            spec.write_text("# spec", encoding="utf-8")
            self.assertEqual(resolve_project_dir(str(spec)), proj.resolve())
            for sub_name in ("cards", "notes", "render", "render_cards", "images", "output"):
                sub = proj / sub_name
                sub.mkdir(parents=True, exist_ok=True)
                self.assertEqual(resolve_project_dir(str(sub)), proj.resolve())

    def test_resolve_project_dir_auto_discovery_from_subfolder_and_file(self):
        from scripts.make_cards import resolve_project_dir
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "custom_proj"
            (proj / "svg_output").mkdir(parents=True)
            (proj / "svg_output" / "01.svg").write_text("<svg/>", encoding="utf-8")
            spec = proj / "spec_lock.md"
            spec.write_text("# spec", encoding="utf-8")
            self.assertEqual(resolve_project_dir(base_dir=spec), proj.resolve())
            for sub_name in ("cards", "notes", "render", "render_cards", "images", "output"):
                sub = proj / sub_name
                sub.mkdir(parents=True, exist_ok=True)
                self.assertEqual(resolve_project_dir(base_dir=sub), proj.resolve())


    def test_load_deck_title_prioritizes_versioned_spec_lock(self):
        from scripts.make_cards import load_deck_title
        (self.root / "spec_lock.md").write_text("# 旧项目\n\n## canvas\n", encoding="utf-8")
        (self.root / "spec_lock_v2.md").write_text("# 新版项目\n\n## canvas\n", encoding="utf-8")
        title = load_deck_title(self.root)
        self.assertEqual(title, "新版项目")

    def test_load_spec_roles_from_svg_child_dir(self):
        from scripts.make_cards import load_spec_roles
        (self.root / "card_spec.md").write_text("## typography\n- statement 80\n", encoding="utf-8")
        roles = load_spec_roles(self.root / "svg_output")
        self.assertEqual(roles["statement"], 80)

    def test_make_cards_forwards_base_dir_and_qa_check(self):
        from scripts.make_cards import main
        qa_called = []

        def mock_qa(target, spec_path=None, base_dir=None):
            qa_called.append((target, spec_path, base_dir))
            return True

        with ExitStack() as stack:
            for p in self.patches():
                stack.enter_context(p)
            stack.enter_context(patch("scripts.make_cards.run_qa_cards", side_effect=mock_qa))
            result = make_cards(self.root, check=True, base_dir=self.root)
            self.assertEqual(len(result), 2)
            self.assertEqual(len(qa_called), 1)
            self.assertEqual(qa_called[0][2], self.root.resolve())

        # Test main forwards base_dir
        with ExitStack() as stack:
            for p in self.patches():
                stack.enter_context(p)
            ret = main([str(self.root), "--check"], base_dir=self.root)
            self.assertEqual(ret, 0)


if __name__ == "__main__":
    unittest.main()
