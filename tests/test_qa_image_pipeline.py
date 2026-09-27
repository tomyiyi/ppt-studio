import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.qa_image_pipeline import run_image_qa


class TestImageQAPipeline(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
