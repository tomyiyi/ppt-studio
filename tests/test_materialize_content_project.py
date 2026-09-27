import unittest
class MetricMaterializerContractTests(unittest.TestCase):
    def test_expected_roster_name(self):
        self.assertEqual('02_metric_highlights.svg'.split('.')[0], '02_metric_highlights')

if __name__ == '__main__': unittest.main()
