import tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import render_target_progress_svg as renderer
class TargetProgressTests(unittest.TestCase):
    def slide(self, items=None):
        return {"type":"content","layout":"target-progress","title":"Delivery Targets","blocks":[{"type":"target-progress","items":items or [{"metric":"A","actual":72,"target":90},{"metric":"B","actual":95,"target":95},{"metric":"C","actual":110,"target":90}]}]}
    def test_mapping_and_determinism(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/"a.svg"; b=Path(d)/"b.svg"; renderer.render(self.slide(),a); renderer.render(self.slide(),b)
            self.assertEqual(a.read_bytes(),b.read_bytes()); t=a.read_text(); self.assertEqual(t.count("<rect "),7); self.assertIn('width="712.00"',t)
    def test_zero_actual_valid_and_bad_target_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            renderer.render(self.slide([{"metric":"A","actual":0,"target":10},{"metric":"B","actual":1,"target":2},{"metric":"C","actual":2,"target":3}]),Path(d)/"x.svg")
            with self.assertRaises(ValueError): renderer.render(self.slide([{"metric":"A","actual":1,"target":0},{"metric":"B","actual":1,"target":2},{"metric":"C","actual":2,"target":3}]),Path(d)/"y.svg")
if __name__=="__main__": unittest.main()
