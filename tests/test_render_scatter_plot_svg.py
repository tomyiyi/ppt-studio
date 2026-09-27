import json, tempfile, unittest
from pathlib import Path
import importlib.util
SPEC=importlib.util.spec_from_file_location("r",Path(__file__).parents[1]/"scripts/render_scatter_plot_svg.py"); M=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)
class ScatterRendererTests(unittest.TestCase):
    def setUp(self):
        self.slide={"type":"content","layout":"scatter-plot","title":"Workload","blocks":[{"type":"scatter-data","items":[{"label":"A","x":0,"y":10},{"label":"B","x":10,"y":20},{"label":"C","x":5,"y":15}]}]}
    def test_deterministic_and_points(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/"a.svg"; b=Path(d)/"b.svg"; M.render(self.slide,a); M.render(self.slide,b)
            self.assertEqual(a.read_bytes(),b.read_bytes()); self.assertEqual(a.read_text().count("<circle"),3)
    def test_equal_axes_legal(self):
        s=json.loads(json.dumps(self.slide)); s["blocks"][0]["items"]=[{"label":"A","x":1,"y":2},{"label":"B","x":1,"y":2},{"label":"C","x":1,"y":2}]
        with tempfile.TemporaryDirectory() as d: M.render(s,Path(d)/"x.svg")
    def test_invalid_count(self):
        s=json.loads(json.dumps(self.slide)); s["blocks"][0]["items"]=s["blocks"][0]["items"][:2]
        with self.assertRaises(ValueError): M.render(s,Path(tempfile.mkdtemp())/"x.svg")
if __name__=="__main__": unittest.main()
