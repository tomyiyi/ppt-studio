import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "run_test_gates.py"


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


if __name__ == "__main__":
    unittest.main()
