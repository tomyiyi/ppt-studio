import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from plan_markdown import parse_markdown

class MetricParserTests(unittest.TestCase):
    def test_metric_list(self):
        slides=parse_markdown('# A\n\n## K\n\n- A: 1\n- B: 2')
        self.assertEqual(slides[1]['blocks'][0]['type'], 'metric-list')
        self.assertEqual(slides[1]['blocks'][0]['items'][0]['value'], '1')
    def test_invalid_count(self):
        with self.assertRaisesRegex(ValueError, 'metric list requires 2-4'):
            parse_markdown('# A\n\n## K\n\n- A: 1')

if __name__ == '__main__': unittest.main()
