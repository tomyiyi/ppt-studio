import unittest
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch

from scripts.qa_project import run_project_qa


class TestProjectQA(unittest.TestCase):
    def _patch_all(self, stack, image=True, layout=True, cards=True, long_card=True):
        return [
            stack.enter_context(patch("scripts.qa_project.run_image_qa", return_value={"ok": image})),
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

    def test_layout_failure_is_located(self):
        with ExitStack() as stack:
            mocks = self._patch_all(stack, layout=False)
            result = run_project_qa("/tmp/project", image_targets=["a.png"])
        self.assertEqual(result["failed_stage"], "layout")
        mocks[2].assert_not_called()

    def test_cards_failure_is_located(self):
        with ExitStack() as stack:
            mocks = self._patch_all(stack, cards=False)
            result = run_project_qa("/tmp/project", image_targets=["a.png"])
        self.assertEqual(result["failed_stage"], "cards")
        mocks[3].assert_not_called()

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
        mocks[1].assert_called_once_with("l", verbose=False)
        mocks[2].assert_called_once_with("c", verbose=False)
        mocks[3].assert_called_once_with("d", verbose=False)


if __name__ == "__main__":
    unittest.main()
