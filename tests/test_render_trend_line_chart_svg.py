import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "render_trend_line_chart_svg.py"

class TrendRendererTests(unittest.TestCase):
    def run_renderer(self, items):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            plan={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01","kind":"cover","title":"D","blocks":[]},{"id":"02","kind":"content","title":"Trend","blocks":[{"type":"trend-series","items":items}]}]}
            plan_path=root/"plan.json"; intent_path=root/"intent.json"; out=root/"out"
            plan_path.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+"\n")
            intent={"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256(plan_path.read_bytes()).hexdigest(),"slides":[{"id":"01","layout":"cover"},{"id":"02","layout":"trend-line-chart"}]}
            intent_path.write_text(json.dumps(intent,ensure_ascii=False,indent=2)+"\n")
            result=subprocess.run(["python3",str(SCRIPT),str(plan_path),str(intent_path),"--spec","unused","-o",str(out)],capture_output=True,text=True)
            return result, (out/"02_trend_line_chart.svg").read_text() if (out/"02_trend_line_chart.svg").exists() else ""

    def test_valid_three_to_six_points_and_deterministic(self):
        items=[{"period":"W1","value":42},{"period":"W2","value":58},{"period":"W3","value":71}]
        first, svg1=self.run_renderer(items)
        second, svg2=self.run_renderer(items)
        self.assertEqual(first.returncode,0)
        self.assertEqual(first.stdout.strip(),"TREND_LINE_CHART_SVG_WRITTEN slides=02 layout=trend-line-chart")
        self.assertEqual(svg1,svg2)
        self.assertEqual(svg1.count("<circle "),3)
        self.assertIn('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',svg1)

    def test_all_equal_values_share_horizontal_line(self):
        result, svg=self.run_renderer([{"period":"A","value":5},{"period":"B","value":5},{"period":"C","value":5}])
        self.assertEqual(result.returncode,0)
        self.assertIn('cy="420.0"',svg)
        self.assertNotIn("nan",svg.lower())
        self.assertNotIn("inf",svg.lower())

if __name__ == "__main__":
    unittest.main()
