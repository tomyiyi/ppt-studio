import json, tempfile, unittest
from pathlib import Path
import importlib.util
SPEC=importlib.util.spec_from_file_location("r",Path(__file__).parents[1]/"scripts/render_gantt_schedule_svg.py"); M=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)
class GanttRendererTests(unittest.TestCase):
    def setUp(self):
        self.slide={"type":"content","layout":"gantt-schedule","title":"Schedule","blocks":[{"type":"gantt-schedule","items":[{"task":"A","start":1,"end":2},{"task":"B","start":2,"end":5},{"task":"C","start":6,"end":6}]}]}
    def test_deterministic_and_widths(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/"a.svg"; b=Path(d)/"b.svg"; M.render(self.slide,a); M.render(self.slide,b)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            text=a.read_text(); self.assertIn('width="156.67"',text); self.assertIn('width="313.33"',text)
    def test_invalid_count(self):
        s=json.loads(json.dumps(self.slide)); s["blocks"][0]["items"]=s["blocks"][0]["items"][:2]
        with self.assertRaises(ValueError): M.render(s,Path(tempfile.mkdtemp())/"x.svg")
if __name__=="__main__": unittest.main()
