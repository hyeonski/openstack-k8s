"""Offline S4 analysis keeps proxy errors and controller delays separate."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from graduation_s4_analyze import difference, error_kind, stable_success


class AnalysisTests(unittest.TestCase):
    def test_error_categories_keep_api_path_separate_from_service_endpoints(self):
        self.assertEqual(error_kind({'ok': False, 'error': 'Unable to connect to the server: timeout'}),
                         'api_proxy_unavailable')
        self.assertEqual(error_kind({'ok': False, 'error': 'no endpoints available for service'}),
                         'no_endpoints')
        self.assertEqual(error_kind({'ok': True}), 'ok')

    def test_stable_success_is_after_last_failure(self):
        samples = [{'time': f'2026-09-26T00:00:{second:02d}Z', 'ok': good}
                   for second, good in ((0, True), (5, False), (6, True), (37, True))]
        start, end = stable_success(samples, samples[1]['time'])
        self.assertEqual(start, '2026-09-26T00:00:06Z')
        self.assertEqual(end, '2026-09-26T00:00:37Z')
        self.assertEqual(difference(end, start), 31)
        self.assertEqual(stable_success(samples[:3], samples[1]['time']), (start, None))


if __name__ == '__main__':
    unittest.main()
