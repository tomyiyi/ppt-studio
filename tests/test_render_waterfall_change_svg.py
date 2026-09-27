import tempfile,unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import render_waterfall_change_svg as r
class T(unittest.TestCase):
 def p(self,x): return {"type":"content","layout":"waterfall-change","title":"Weekly Change Drivers","blocks":[{"type":"waterfall-data","items":x}]}
 def test_main(self):
  with tempfile.TemporaryDirectory() as d:
   o=Path(d)/"x.svg";r.render(self.p([{"driver":"A","delta":28},{"driver":"B","delta":17},{"driver":"C","delta":-9},{"driver":"D","delta":-6}]),o);s=o.read_text();self.assertEqual(s.count("<rect"),5);self.assertIn("NET 30",s)
 def test_cross_zero_and_invalid(self):
  with tempfile.TemporaryDirectory() as d:
   o=Path(d)/"x.svg";r.render(self.p([{"driver":"A","delta":5},{"driver":"B","delta":-9},{"driver":"C","delta":2}]),o)
   with self.assertRaises(ValueError):r.render(self.p([{"driver":"A","delta":1},{"driver":"B","delta":2}]),o)
 def test_deterministic(self):
  with tempfile.TemporaryDirectory() as d:
   a=Path(d)/"a";b=Path(d)/"b";p=self.p([{"driver":"A","delta":1.5},{"driver":"B","delta":-.5},{"driver":"C","delta":2}]);r.render(p,a);r.render(p,b);self.assertEqual(a.read_bytes(),b.read_bytes())
