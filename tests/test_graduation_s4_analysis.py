"""Offline S4 analysis keeps proxy errors and controller delays separate."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / d) for d in ('experiments', 'evaluation')]
from graduation_s4_analyze import confirmed_capacity_result, difference, error_kind, stable_success


class AnalysisTests(unittest.TestCase):
    def test_error_categories_keep_api_path_separate_from_service_endpoints(self):
        self.assertEqual(error_kind({'ok': False, 'error': 'Unable to connect to the server: timeout'}),
                         'api_proxy_unavailable')
        self.assertEqual(error_kind({'ok': False, 'error': 'no endpoints available for service'}),
                         'no_endpoints')
        self.assertEqual(error_kind({'ok': True}), 'ok')

    def test_stable_success_is_after_last_failure(self):
        samples = [{'time': f'2026-09-26T00:00:{second:02d}Z', 'ok': good}
                   for second, good in [(0, True), (5, False)] + [(i, True) for i in range(6, 38)]]
        start, end = stable_success(samples, samples[1]['time'])
        self.assertEqual(start, '2026-09-26T00:00:06Z')
        self.assertEqual(end, '2026-09-26T00:00:36Z')
        self.assertEqual(difference(end, start), 30)
        self.assertEqual(stable_success(samples[:3], samples[1]['time']), (start, None))

    def test_online_capacity_verdict_requires_observed_stable_interval(self):
        record = {'target': {'nova_id': 'worker-a'}, 'injected_at': '2026-09-27T00:00:00Z'}
        timeline = [
            {'time': '2026-09-27T00:03:25.000Z', 'capacity_state': 'recovered'},
            {'time': '2026-09-27T00:03:39.700Z', 'capacity_state': 'recovered'},
            {'time': '2026-09-27T00:03:55.345Z', 'capacity_state': 'recovered'},
        ]
        result = {'state': 'passed', 'target': record['target'],
                  'capacity': {'state': 'recovered'},
                  'capacity_recovered_at': timeline[-1]['time'], 'capacity_seconds': 235.345}
        self.assertEqual(confirmed_capacity_result(result, timeline, record), timeline[-1]['time'])
        result['capacity_recovered_at'] = '2026-09-27T00:03:55Z'
        with self.assertRaisesRegex(RuntimeError, 'recovered snapshot'):
            confirmed_capacity_result(result, timeline, record)


if __name__ == '__main__':
    unittest.main()
