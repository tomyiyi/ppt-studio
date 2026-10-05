import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.qa_project import (
    build_qa_attestation,
    main,
    qa_project,
    resolve_project_dir,
    run_project_qa,
    write_qa_attestation,
)


class TestProjectQA(unittest.TestCase):
    def _patch_all(self, stack, image=True, assets=True, layout=True, cards=True, long_card=True):
        return [
            stack.enter_context(patch("scripts.qa_project.run_image_qa", return_value={"ok": image})),
            stack.enter_context(patch("scripts.qa_project.run_qa_assets", return_value={"ok": assets})),
            stack.enter_context(patch("scripts.qa_project.run_qa_layout", return_value=layout)),
            stack.enter_context(patch("scripts.qa_project.run_qa_cards", return_value=cards)),
            stack.enter_context(patch("scripts.qa_project.run_qa_long_card", return_value=long_card)),
        ]

    def test_all_stages_pass_and_execute_in_order(self):
        calls = []
        with ExitStack() as stack:
            mocks = self._patch_all(stack)
            for mock in mocks:
                mock.side_effect = lambda *a, _m=mock, **k: (calls.append(_m), _m.return_value)[1]
            result = run_project_qa(Path("/tmp/project"), image_targets=["a.png"])
        self.assertTrue(result["ok"])
        self.assertEqual([m for m in calls], list(mocks))

    def test_image_failure_stops_project(self):
        with ExitStack() as stack:
            mocks = self._patch_all(stack, image=False)
            result = run_project_qa("/tmp/project", image_targets=["missing.png"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_stage"], "image")
        mocks[1].assert_not_called()
        mocks[2].assert_not_called()
        mocks[3].assert_not_called()
        mocks[4].assert_not_called()

    def test_assets_failure_is_located(self):
        with ExitStack() as stack:
            mocks = self._patch_all(stack, assets=False)
            result = run_project_qa("/tmp/project", image_targets=["a.png"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_stage"], "assets")
        self.assertTrue(result["stages"]["image"]["ok"])
        mocks[2].assert_not_called()
        mocks[3].assert_not_called()
        mocks[4].assert_not_called()

    def test_layout_failure_is_located(self):
        with ExitStack() as stack:
            mocks = self._patch_all(stack, layout=False)
            result = run_project_qa("/tmp/project", image_targets=["a.png"])
        self.assertEqual(result["failed_stage"], "layout")
        mocks[3].assert_not_called()
        mocks[4].assert_not_called()

    def test_cards_failure_is_located(self):
        with ExitStack() as stack:
            mocks = self._patch_all(stack, cards=False)
            result = run_project_qa("/tmp/project", image_targets=["a.png"])
        self.assertEqual(result["failed_stage"], "cards")
        mocks[4].assert_not_called()

    def test_long_card_failure_is_located(self):
        with ExitStack() as stack:
            self._patch_all(stack, long_card=False)
            result = run_project_qa("/tmp/project", image_targets=["a.png"])
        self.assertEqual(result["failed_stage"], "long_card")

    def test_targets_are_forwarded_without_changing_existing_gates(self):
        with ExitStack() as stack:
            mocks = self._patch_all(stack)
            run_project_qa("/tmp/project", image_targets=["a.png"], layout_target="l", cards_target="c", long_card_target="d")
        mocks[0].assert_called_once_with(["a.png"], verbose=False)
        mocks[1].assert_called_once_with(Path("/tmp/project"))
        mocks[2].assert_called_once_with("l", verbose=False)
        mocks[3].assert_called_once_with("c", verbose=False)
        mocks[4].assert_called_once_with("d", verbose=False)

    def test_attestation_success_is_derived_from_all_stages(self):
        result = {"ok": True, "failed_stage": None, "stages": {
            "image": {"ok": True}, "assets": {"ok": True}, "layout": {"ok": True},
            "cards": {"ok": True}, "long_card": {"ok": True},
        }}
        attestation = build_qa_attestation(result)
        self.assertEqual(attestation["schema_version"], 1)
        self.assertTrue(attestation["overall"])

    def test_attestation_preserves_failed_stage_and_reason(self):
        result = {"ok": False, "failed_stage": "image", "stages": {
            "image": {"ok": False, "code": "FILE_NOT_FOUND", "reason": "missing"},
        }}
        attestation = build_qa_attestation(result)
        self.assertFalse(attestation["overall"])
        self.assertEqual(attestation["failed_stage"], "image")
        self.assertEqual(attestation["stages"]["image"]["code"], "FILE_NOT_FOUND")

    def test_attestation_round_trips_through_json(self):
        result = {"ok": True, "failed_stage": None, "stages": {
            name: {"ok": True} for name in ("image", "assets", "layout", "cards", "long_card")
        }}
        self.assertEqual(json.loads(json.dumps(build_qa_attestation(result))), build_qa_attestation(result))

    def test_write_attestation_is_readable_and_matches_memory(self):
        result = {"ok": True, "failed_stage": None, "stages": {
            name: {"ok": True} for name in ("image", "assets", "layout", "cards", "long_card")
        }}
        output = Path(self.id().replace(".", "_") + ".json")
        try:
            expected = write_qa_attestation(result, output)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), expected)
        finally:
            output.unlink(missing_ok=True)

    def test_failed_result_never_becomes_success_attestation(self):
        result = {"ok": True, "failed_stage": "cards", "stages": {
            "image": {"ok": True}, "assets": {"ok": True}, "layout": {"ok": True},
            "cards": {"ok": False}, "long_card": {"ok": True},
        }}
        self.assertFalse(build_qa_attestation(result)["overall"])

    def test_write_failure_does_not_leave_partial_destination(self):
        result = {"ok": True, "failed_stage": None, "stages": {
            name: {"ok": True} for name in ("image", "assets", "layout", "cards", "long_card")
        }}
        with self.assertRaises((NotADirectoryError, FileNotFoundError, FileExistsError)):
            write_qa_attestation(result, "/dev/null/qa-attestation.json")

    def test_cli_success(self):
        with ExitStack() as stack:
            self._patch_all(stack)
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["/tmp/mock-project"])
            self.assertEqual(code, 0)
            self.assertIn("✓ 项目客观质量门禁全量通过", buf.getvalue())

    def test_cli_failure(self):
        with ExitStack() as stack:
            self._patch_all(stack, layout=False)
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["/tmp/mock-project"])
            self.assertEqual(code, 1)
            self.assertIn("✗ 项目客观质量门禁失败 (阶段: layout)", buf.getvalue())

    def test_cli_json_mode(self):
        with ExitStack() as stack:
            self._patch_all(stack)
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["/tmp/mock-project", "--json"])
            self.assertEqual(code, 0)
            data = json.loads(buf.getvalue())
            self.assertTrue(data["ok"])
            self.assertIsNone(data["failed_stage"])

    def test_cli_writes_attestation(self):
        with tempfile.TemporaryDirectory() as td:
            attestation_path = Path(td) / "qa.json"
            with ExitStack() as stack:
                self._patch_all(stack)
                code = main(["/tmp/mock-project", "--attestation", str(attestation_path)])
            self.assertEqual(code, 0)
            self.assertTrue(attestation_path.exists())
            data = json.loads(attestation_path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], 1)
            self.assertTrue(data["overall"])

    def test_cli_subprocess_invocation(self):
        script = Path(__file__).resolve().parent.parent / "scripts" / "qa_project.py"
        fixture = Path(__file__).resolve().parent.parent / "projects" / "agentflow-os-launch"
        completed = subprocess.run(
            [sys.executable, str(script), str(fixture), "--json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        data = json.loads(completed.stdout)
        self.assertTrue(data["ok"])
        self.assertIn("stages", data)

    def test_cli_subprocess_invocation_default_auto_discovery(self):
        script = Path(__file__).resolve().parent.parent / "scripts" / "qa_project.py"
        fixture = Path(__file__).resolve().parent.parent / "projects" / "agentflow-os-launch"
        completed = subprocess.run(
            [sys.executable, str(script), "--json"],
            cwd=fixture,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        data = json.loads(completed.stdout)
        self.assertTrue(data["ok"])
        self.assertIn("stages", data)


class TestResolveProjectDir(unittest.TestCase):
    def test_alias(self):
        self.assertIs(qa_project, run_project_qa)

    def test_explicit_path_preserved(self):
        target = Path("/tmp/custom-project")
        resolved = resolve_project_dir(str(target))
        self.assertEqual(resolved, target.resolve())

    def test_explicit_subfolder_falls_back_to_parent(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "my_project"
            sub = proj / "images"
            sub.mkdir(parents=True)
            self.assertEqual(resolve_project_dir(sub), proj.resolve())

    def test_explicit_versioned_svg_subfolder_falls_back_to_parent(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "my_project"
            sub = proj / "svg_output_v4"
            sub.mkdir(parents=True)
            self.assertEqual(resolve_project_dir(sub), proj.resolve())

    def test_current_dir_when_already_project(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "spec_lock.md").touch()
            self.assertEqual(resolve_project_dir(".", base_dir=proj), proj.resolve())

    def test_current_dir_with_versioned_svg_output_is_project(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            sub = proj / "svg_output_v3"
            sub.mkdir(parents=True)
            (sub / "01.svg").touch()
            self.assertEqual(resolve_project_dir(".", base_dir=proj), proj.resolve())

    def test_subfolder_in_current_dir_falls_back_to_parent(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            sub = proj / "cards"
            sub.mkdir(parents=True)
            (proj / "spec_lock.md").touch()
            self.assertEqual(resolve_project_dir(None, base_dir=sub), proj.resolve())

    def test_versioned_svg_subfolder_in_current_dir_falls_back_to_parent(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            sub = proj / "svg_output_v2"
            sub.mkdir(parents=True)
            (proj / "spec_lock.md").touch()
            self.assertEqual(resolve_project_dir(None, base_dir=sub), proj.resolve())

    def test_discovers_unique_project_under_projects_folder(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            projects_dir = root / "projects"
            p1 = projects_dir / "alpha"
            (p1 / "images").mkdir(parents=True)
            self.assertEqual(resolve_project_dir(".", base_dir=root), p1.resolve())

    def test_discovers_unique_versioned_project_under_projects_folder(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            projects_dir = root / "projects"
            p1 = projects_dir / "gamma"
            sub = p1 / "svg_output_v4"
            sub.mkdir(parents=True)
            (sub / "01.svg").touch()
            self.assertEqual(resolve_project_dir(".", base_dir=root), p1.resolve())

    def test_multiple_projects_raises_value_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            projects_dir = root / "projects"
            p1 = projects_dir / "alpha"
            p2 = projects_dir / "beta"
            (p1 / "images").mkdir(parents=True)
            (p2 / "cards").mkdir(parents=True)
            with self.assertRaises(ValueError) as ctx:
                resolve_project_dir(".", base_dir=root)
            self.assertIn("发现多个项目", str(ctx.exception))

    def test_explicit_spec_file_falls_back_to_parent(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "spec_proj"
            proj.mkdir(parents=True)
            spec_file = proj / "spec_lock.md"
            spec_file.write_text("# spec\n", encoding="utf-8")
            self.assertEqual(resolve_project_dir(spec_file), proj.resolve())

    def test_explicit_card_spec_file_falls_back_to_parent(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "card_proj"
            proj.mkdir(parents=True)
            card_spec = proj / "card_spec.md"
            card_spec.write_text("# card spec\n", encoding="utf-8")
            self.assertEqual(resolve_project_dir(card_spec), proj.resolve())

    def test_explicit_render_and_output_subfolders_fall_back_to_parent(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "my_project"
            for sub_name in ("render", "render_cards", "output"):
                sub = proj / sub_name
                sub.mkdir(parents=True, exist_ok=True)
                self.assertEqual(resolve_project_dir(sub), proj.resolve())

    def test_current_dir_with_card_spec_is_project(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "card_spec.md").touch()
            self.assertEqual(resolve_project_dir(".", base_dir=proj), proj.resolve())

    def test_resolve_project_dir_subfolder_and_base_dir(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "my_project"
            proj.mkdir(parents=True)
            sub_svg = proj / "svg_output"
            sub_svg.mkdir()
            (sub_svg / "01.svg").write_text("<svg></svg>", encoding="utf-8")
            sub_img = proj / "images"
            sub_img.mkdir()
            spec_file = proj / "spec_lock.md"
            spec_file.write_text("# Spec\n", encoding="utf-8")

            self.assertEqual(resolve_project_dir(sub_svg), proj.resolve())
            self.assertEqual(resolve_project_dir(sub_img), proj.resolve())
            self.assertEqual(resolve_project_dir(spec_file), proj.resolve())
            self.assertEqual(resolve_project_dir(str(sub_svg)), proj.resolve())
            self.assertEqual(resolve_project_dir(base_dir=sub_svg), proj.resolve())
            self.assertEqual(resolve_project_dir(base_dir=spec_file), proj.resolve())
            self.assertEqual(resolve_project_dir("svg_output", base_dir=proj), proj.resolve())

    def test_resolve_project_dir_fallback_without_cpm(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "my_project"
            proj.mkdir(parents=True)
            sub_svg = proj / "svg_output"
            sub_svg.mkdir()
            (sub_svg / "01.svg").write_text("<svg></svg>", encoding="utf-8")
            sub_img = proj / "images"
            sub_img.mkdir()
            spec_file = proj / "spec_lock.md"
            spec_file.write_text("# Spec\n", encoding="utf-8")

            with patch("scripts.qa_project._cpm_resolve_project_dir", None):
                self.assertEqual(resolve_project_dir(sub_svg), proj.resolve())
                self.assertEqual(resolve_project_dir(sub_img), proj.resolve())
                self.assertEqual(resolve_project_dir(spec_file), proj.resolve())
                self.assertEqual(resolve_project_dir(base_dir=sub_svg), proj.resolve())
                self.assertEqual(resolve_project_dir(base_dir=spec_file), proj.resolve())
                self.assertEqual(resolve_project_dir("svg_output", base_dir=proj), proj.resolve())
                self.assertEqual(resolve_project_dir(None, base_dir=sub_svg), proj.resolve())

    def test_run_project_qa_and_main_with_base_dir(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "my_project"
            proj.mkdir(parents=True)
            sub_svg = proj / "svg_output"
            sub_svg.mkdir()
            (sub_svg / "01.svg").write_text("<svg></svg>", encoding="utf-8")
            (proj / "spec_lock.md").write_text("# Spec\n", encoding="utf-8")

            with ExitStack() as stack:
                stack.enter_context(patch("scripts.qa_project.run_image_qa", return_value={"ok": True}))
                stack.enter_context(patch("scripts.qa_project.run_qa_assets", return_value={"ok": True}))
                stack.enter_context(patch("scripts.qa_project.run_qa_layout", return_value=True))
                stack.enter_context(patch("scripts.qa_project.run_qa_cards", return_value=True))
                stack.enter_context(patch("scripts.qa_project.run_qa_long_card", return_value=True))

                res = run_project_qa(".", base_dir=proj)
                self.assertTrue(res["ok"])

                res_sub = run_project_qa("svg_output", base_dir=proj)
                self.assertTrue(res_sub["ok"])

                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = main([".", "--json"], base_dir=sub_svg)
                self.assertEqual(rc, 0)
                data = json.loads(buf.getvalue())
                self.assertTrue(data["ok"])

    def test_run_project_qa_forwards_base_dir_to_sub_qas(self):
        with ExitStack() as stack:
            img_mock = stack.enter_context(patch("scripts.qa_project.run_image_qa", return_value={"ok": True}))
            assets_mock = stack.enter_context(patch("scripts.qa_project.run_qa_assets", return_value={"ok": True}))
            layout_mock = stack.enter_context(patch("scripts.qa_project.run_qa_layout", return_value=True))
            cards_mock = stack.enter_context(patch("scripts.qa_project.run_qa_cards", return_value=True))
            long_card_mock = stack.enter_context(patch("scripts.qa_project.run_qa_long_card", return_value=True))

            res = run_project_qa(
                "/tmp/proj",
                image_targets=["img.png"],
                layout_target="l",
                cards_target="c",
                long_card_target="d",
                base_dir="/tmp/base",
            )
            self.assertTrue(res["ok"])
            img_mock.assert_called_once_with(["img.png"], verbose=False, base_dir="/tmp/base")
            assets_mock.assert_called_once_with(Path("/tmp/proj"), base_dir="/tmp/base")
            layout_mock.assert_called_once_with("l", verbose=False, base_dir="/tmp/base")
            cards_mock.assert_called_once_with("c", verbose=False, base_dir="/tmp/base")
            long_card_mock.assert_called_once_with("d", verbose=False, base_dir="/tmp/base")

    def test_run_project_qa_forwards_base_dir_fallback_on_typeerror(self):
        def mock_layout(*args, **kwargs):
            if "base_dir" in kwargs:
                raise TypeError("unexpected keyword argument 'base_dir'")
            return True

        def mock_cards(*args, **kwargs):
            if "base_dir" in kwargs:
                raise TypeError("unexpected keyword argument 'base_dir'")
            return True

        def mock_long_card(*args, **kwargs):
            if "base_dir" in kwargs:
                raise TypeError("unexpected keyword argument 'base_dir'")
            return True

        with ExitStack() as stack:
            stack.enter_context(patch("scripts.qa_project.run_image_qa", return_value={"ok": True}))
            stack.enter_context(patch("scripts.qa_project.run_qa_assets", return_value={"ok": True}))
            layout_mock = stack.enter_context(patch("scripts.qa_project.run_qa_layout", side_effect=mock_layout))
            cards_mock = stack.enter_context(patch("scripts.qa_project.run_qa_cards", side_effect=mock_cards))
            long_card_mock = stack.enter_context(patch("scripts.qa_project.run_qa_long_card", side_effect=mock_long_card))

            res = run_project_qa(
                "/tmp/proj",
                image_targets=["img.png"],
                layout_target="l",
                cards_target="c",
                long_card_target="d",
                base_dir="/tmp/base",
            )
            self.assertTrue(res["ok"])
            self.assertEqual(layout_mock.call_count, 2)
            self.assertEqual(cards_mock.call_count, 2)
            self.assertEqual(long_card_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
