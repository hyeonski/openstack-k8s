"""Exact statistics for the decision analysis must match known small-sample values."""
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / d) for d in ('scripts', 'evaluation')]
from graduation_analysis_decisions import clopper_pearson, cliffs_delta, mann_whitney_exact, ranks, wilcoxon_exact


class DecisionStatisticsTests(unittest.TestCase):
    def test_clopper_pearson_known_bounds(self):
        self.assertEqual(clopper_pearson(5, 5), (0.4782, 1.0))
        self.assertEqual(clopper_pearson(1, 1), (0.025, 1.0))
        self.assertEqual(clopper_pearson(0, 5), (0.0, 0.5218))
        lower, upper = clopper_pearson(3, 10)
        self.assertAlmostEqual(lower, 0.0667, places=3)
        self.assertAlmostEqual(upper, 0.6525, places=3)

    def test_mann_whitney_complete_separation(self):
        result = mann_whitney_exact([1, 2, 3, 4, 5], [6, 7, 8, 9, 10])
        self.assertEqual(result['u'], 0)
        self.assertEqual(result['p_two_sided'], round(2 / 252, 4))
        self.assertEqual(cliffs_delta([1, 2], [3, 4]), -1.0)

    def test_mann_whitney_identical_groups_is_not_significant(self):
        self.assertEqual(mann_whitney_exact([1, 2, 3], [1, 2, 3])['p_two_sided'], 1.0)

    def test_wilcoxon_all_same_direction(self):
        result = wilcoxon_exact([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
        self.assertEqual(result['positive_differences'], 5)
        self.assertEqual(result['p_two_sided'], 0.0625)

    def test_midranks(self):
        self.assertEqual(ranks([3, 1, 3, 2]), [3.5, 1.0, 3.5, 2.0])


if __name__ == '__main__':
    unittest.main()
