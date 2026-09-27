import json, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import render_status_heatmap_svg as renderer

class StatusHeatmapRendererTests(unittest.TestCase):
    def slide(self, items=None):
        return {"type":"content","layout":"status-heatmap","title":"Operational Risk Heatmap","blocks":[{"type":"status-heatmap","periods":["W1","W2","W3","W4"],"items":items or [{"item":"Planning","statuses":["High","Medium","Low","Low"]},{"item":"Execution","statuses":["Medium","Medium","Low","Low"]},{"item":"Recovery","statuses":["High","High","Medium","Low"]}]}]}
    def test_deterministic_and_grid(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/"a.svg"; b=Path(d)/"b.svg"
            renderer.render(self.slide(),a); renderer.render(self.slide(),b)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            text=a.read_text()
            self.assertEqual(text.count("<rect "),13)
            self.assertEqual(text.count("Low"),5)
    def test_invalid_schema_rejected(self):
        bad=self.slide([{"item":"Planning","statuses":["Critical","Low","Low","Low"]}]*3)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError): renderer.render(bad,Path(d)/"x.svg")
    def test_count_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError): renderer.render(self.slide([{"item":"P","statuses":["Low"]}]*2),Path(d)/"x.svg")
if __name__=="__main__": unittest.main()
