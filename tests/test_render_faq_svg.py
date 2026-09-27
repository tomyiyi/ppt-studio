import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("render_faq_svg", ROOT / "scripts" / "render_faq_svg.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RenderFaqTests(unittest.TestCase):
    def _run(self, plan, intent, out):
        out.mkdir(parents=True, exist_ok=True)
        pp = out / "plan.json"; ip = out / "intent.json"
        pp.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
        intent["source_plan_sha256"] = hashlib.sha256(pp.read_bytes()).hexdigest()
        ip.write_text(json.dumps(intent, ensure_ascii=False, indent=2) + "\n")
        old = sys.argv
        try:
            sys.argv = ["render_faq_svg.py", str(pp), str(ip), "-o", str(out / "rendered")]
            MODULE.main()
        finally:
            sys.argv = old
        return out / "rendered" / "02_faq.svg"

    def test_deterministic_two_to_four_pair_render(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for count in (2, 4):
                items = [{"question": f"question {i}", "answer": f"answer {i}"} for i in range(count)]
                plan = {"schema":"ppt-studio-slide-plan/v1", "slides":[{"id":"02","kind":"content","blocks":[{"type":"faq","items":items}]}]}
                intent = {"schema":"ppt-studio-layout-intent/v1","slides":[{"id":"02","layout":"faq"}]}
                first = self._run(plan, intent, root / f"a{count}").read_bytes()
                second = self._run(plan, intent, root / f"b{count}").read_bytes()
                self.assertEqual(first, second)
                self.assertIn(b'width="1280"', first)
                self.assertIn(b'height="720"', first)
                self.assertEqual(first.count(b'<rect x="80"'), count)

    def test_text_budget_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            items = [{"question":"q" * 31,"answer":"a" * 4},{"question":"q2","answer":"a2"}]
            plan = {"schema":"ppt-studio-slide-plan/v1", "slides":[{"id":"02","kind":"content","blocks":[{"type":"faq","items":items}]}]}
            intent = {"schema":"ppt-studio-layout-intent/v1","slides":[{"id":"02","layout":"faq"}]}
            with self.assertRaises(SystemExit): self._run(plan, intent, root)


if __name__ == "__main__":
    unittest.main()
