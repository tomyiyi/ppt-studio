import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from assign_layout_intent import assign_layout

class MetricIntentTests(unittest.TestCase):
    def test_metric_layout(self):
        slide={'kind':'content','blocks':[{'type':'metric-list','items':[{'label':'A','value':'1'},{'label':'B','value':'2'}]}]}
        self.assertEqual(assign_layout(slide), 'metric-highlights')
    def test_mixed_rejected(self):
        slide={'kind':'content','blocks':[{'type':'metric-list','items':[]},{'type':'quote','lines':['x']}]}
        with self.assertRaises(ValueError): assign_layout(slide)

if __name__ == '__main__': unittest.main()
