import unittest
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from scripts.qa_image_pipeline import main, run_image_qa


class TestImageQAPipeline(unittest.TestCase):
    SCRIPT = Path(__file__).parents[1] / "scripts" / "qa_image_pipeline.py"
    FIXTURE = Path(__file__).parents[1] / "projects/agentflow-os-launch/images/cover_bg.png"

    def test_all_stages_pass(self):
        with patch("scripts.qa_image_pipeline._resolve_and_dedup_targets", return_value=([Path("a.png")], [])), \
             patch("scripts.qa_image_pipeline.check_images", return_value={"ok": True}), \
             patch("scripts.qa_image_pipeline.check_crop_panel", return_value=(True, {"x": 1}, [])), \
             patch("scripts.qa_image_pipeline.check_boost_ink", return_value=(True, {"x": 2}, [])):
            result = run_image_qa("a.png")
        self.assertEqual((result["ok"], result["total"], result["passed"]), (True, 1, 1))
        self.assertEqual(result["items"][0]["stage"], "complete")

    def test_prepare_failure_short_circuits_later_stages(self):
        with patch("scripts.qa_image_pipeline._resolve_and_dedup_targets", return_value=([Path("a.png")], [])), \
             patch("scripts.qa_image_pipeline.check_images", return_value={"ok": False, "failures": [{"code": "FILE_NOT_FOUND", "reason": "missing"}]}), \
             patch("scripts.qa_image_pipeline.check_crop_panel") as crop, \
             patch("scripts.qa_image_pipeline.check_boost_ink") as boost:
            result = run_image_qa("a.png")
        self.assertFalse(result["ok"])
        self.assertEqual(result["items"][0]["stage"], "prepare")
        crop.assert_not_called()
        boost.assert_not_called()

    def test_crop_failure_short_circuits_boost(self):
        with patch("scripts.qa_image_pipeline._resolve_and_dedup_targets", return_value=([Path("a.png")], [])), \
             patch("scripts.qa_image_pipeline.check_images", return_value={"ok": True}), \
             patch("scripts.qa_image_pipeline.check_crop_panel", return_value=(False, {}, ["dark"])), \
             patch("scripts.qa_image_pipeline.check_boost_ink") as boost:
            result = run_image_qa("a.png")
        self.assertEqual(result["items"][0]["stage"], "crop")
        boost.assert_not_called()

    def test_mixed_batch_keeps_success_and_failure(self):
        with patch("scripts.qa_image_pipeline._resolve_and_dedup_targets", return_value=([Path("a.png")], [{"file": "missing.png", "name": "missing.png", "code": "FILE_NOT_FOUND", "reason": "missing"}])), \
             patch("scripts.qa_image_pipeline.check_images", return_value={"ok": True}), \
             patch("scripts.qa_image_pipeline.check_crop_panel", return_value=(True, {}, [])), \
             patch("scripts.qa_image_pipeline.check_boost_ink", return_value=(True, {}, [])):
            result = run_image_qa(["a.png", "missing.png"])
        self.assertEqual((result["total"], result["passed"], result["failed"]), (2, 1, 1))
        self.assertTrue(any(item["ok"] for item in result["items"]))
        self.assertTrue(any(item["stage"] == "prepare" for item in result["items"]))

    def test_duplicate_resolution_is_consumed_once(self):
        with patch("scripts.qa_image_pipeline._resolve_and_dedup_targets", return_value=([Path("a.png")], [])) as resolve, \
             patch("scripts.qa_image_pipeline.check_images", return_value={"ok": True}), \
             patch("scripts.qa_image_pipeline.check_crop_panel", return_value=(True, {}, [])), \
             patch("scripts.qa_image_pipeline.check_boost_ink", return_value=(True, {}, [])):
            result = run_image_qa(["a.png", "a.png"])
        resolve.assert_called_once()
        self.assertEqual(result["total"], 1)

    def test_order_and_verbose_do_not_change_business_result(self):
        def run(value, verbose):
            with patch("scripts.qa_image_pipeline._resolve_and_dedup_targets", return_value=([Path("a.png"), Path("b.png")], [])), \
                 patch("scripts.qa_image_pipeline.check_images", return_value={"ok": True}), \
                 patch("scripts.qa_image_pipeline.check_crop_panel", return_value=(True, {}, [])), \
                 patch("scripts.qa_image_pipeline.check_boost_ink", return_value=(True, {}, [])):
                return run_image_qa(value, verbose=verbose)
        self.assertEqual(run(["a.png", "b.png"], False), run(["b.png", "a.png"], True))

    def test_cli_success_and_json(self):
        completed = subprocess.run([sys.executable, str(self.SCRIPT), str(self.FIXTURE), "--json"], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual((payload["total"], payload["passed"], payload["failed"]), (1, 1, 0))
        self.assertEqual(payload["items"][0]["stage"], "complete")

    def test_cli_mixed_failure_keeps_json_parseable(self):
        completed = subprocess.run([sys.executable, str(self.SCRIPT), str(self.FIXTURE), "/tmp/qa-image-missing.png", "--json"], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertEqual((payload["total"], payload["passed"], payload["failed"]), (2, 1, 1))
        self.assertTrue(any(item.get("code") == "FILE_NOT_FOUND" for item in payload["items"]))

    def test_cli_usage_error_is_two(self):
        completed = subprocess.run([sys.executable, str(self.SCRIPT), "--unknown"], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 2)

    def test_cli_without_target_is_two(self):
        completed = subprocess.run([sys.executable, str(self.SCRIPT)], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 2)

    def test_run_image_qa_with_base_dir(self):
        with patch("scripts.qa_image_pipeline._resolve_and_dedup_targets", return_value=([Path("/proj/a.png")], [])) as mock_resolve, \
             patch("scripts.qa_image_pipeline.check_images", return_value={"ok": True}) as mock_check, \
             patch("scripts.qa_image_pipeline.check_crop_panel", return_value=(True, {"x": 1}, [])), \
             patch("scripts.qa_image_pipeline.check_boost_ink", return_value=(True, {"x": 2}, [])):
            result = run_image_qa("a.png", base_dir="/proj")
        mock_resolve.assert_called_once_with("a.png", base_dir="/proj")
        mock_check.assert_called_once_with(Path("/proj/a.png"), size=None, verbose=False)
        self.assertTrue(result["ok"])

    def test_main_with_base_dir(self):
        with patch("scripts.qa_image_pipeline.run_image_qa", return_value={"ok": True, "total": 1, "passed": 1, "failed": 0, "items": []}) as mock_qa:
            code = main(["a.png"], base_dir="/proj")
        self.assertEqual(code, 0)
        mock_qa.assert_called_once_with(["a.png"], verbose=True, base_dir="/proj")


if __name__ == "__main__":
    unittest.main()
