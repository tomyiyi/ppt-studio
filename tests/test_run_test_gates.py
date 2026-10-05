import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "run_test_gates.py"

from scripts.run_test_gates import PROCESS_MODULES, discovered_modules, main, run_gate


class TestRunTestGates(unittest.TestCase):
    def test_process_module_is_explicit_and_fast_is_discovered(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('PROCESS_MODULES = {"tests.test_prepare_agnes_image"}', source)
        self.assertIn('glob("test_*.py")', source)

    def test_invalid_mode_is_rejected(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "unknown"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage:", proc.stdout)

    def test_script_is_importable(self):
        spec = importlib.util.spec_from_file_location("run_test_gates", SCRIPT)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        self.assertEqual(module.PROCESS_MODULES, {"tests.test_prepare_agnes_image"})

    def test_discovered_modules_with_path_and_str(self):
        mods_path = discovered_modules(ROOT)
        mods_str = discovered_modules(str(ROOT))
        self.assertEqual(mods_path, mods_str)
        self.assertTrue(len(mods_path) > 0)
        self.assertIn("tests.test_run_test_gates", mods_path)

    def test_discovered_modules_non_existent_tests(self):
        with tempfile.TemporaryDirectory() as td:
            mods = discovered_modules(td)
            self.assertEqual(mods, [])

    def test_run_gate_empty_modules(self):
        rc = run_gate("fast", [], ROOT)
        self.assertEqual(rc, 0)

    @patch("subprocess.run")
    def test_run_gate_with_str_root(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        rc = run_gate("fast", ["tests.test_sample"], str(ROOT))
        self.assertEqual(rc, 0)
        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args.kwargs["cwd"], ROOT.resolve())

    @patch("scripts.run_test_gates.run_gate", return_value=0)
    def test_main_with_base_dir(self, mock_gate):
        with tempfile.TemporaryDirectory() as td:
            tests_dir = Path(td) / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_fake.py").write_text("import unittest\n", encoding="utf-8")

            # test fast mode with base_dir
            rc_fast = main(["fast"], base_dir=td)
            self.assertEqual(rc_fast, 0)
            mock_gate.assert_called_with("fast", ["tests.test_fake"], Path(td).resolve())

            # test process mode with base_dir
            mock_gate.reset_mock()
            rc_proc = main(["process"], base_dir=Path(td))
            self.assertEqual(rc_proc, 0)
            mock_gate.assert_called_with("process", [], Path(td).resolve())

            # test all mode with base_dir
            mock_gate.reset_mock()
            rc_all = main(["all"], base_dir=td)
            self.assertEqual(rc_all, 0)
            self.assertEqual(mock_gate.call_count, 2)

            # test fast mode with --base-dir CLI flag
            mock_gate.reset_mock()
            rc_flag = main(["fast", "--base-dir", td])
            self.assertEqual(rc_flag, 0)
            mock_gate.assert_called_with("fast", ["tests.test_fake"], Path(td).resolve())


if __name__ == "__main__":
    unittest.main()
