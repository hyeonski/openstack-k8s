"""S1's direct HTTP workload and baseline sampler produce auditable records."""
from contextlib import redirect_stdout
import datetime as dt
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'kubernetes/graduation-s1'))
from app import Handler
from graduation_s1 import analyze_rows, host_cpu_pressure, host_cpu_utilization
from loadgen import run


class S1ServiceTests(unittest.TestCase):
    def invoke(self, path):
        handler = Handler.__new__(Handler)
        handler.path = path
        handler.wfile = io.BytesIO()
        status = []
        handler.send_response = lambda code: status.append(code)
        handler.send_header = lambda *_args: None
        handler.end_headers = lambda: None
        handler.send_error = lambda code, *_args: status.append(code)
        handler.do_GET()
        return status[0], handler.wfile.getvalue()

    def test_work_response_is_deterministic_and_health_is_separate(self):
        self.assertEqual(self.invoke('/healthz'), (200, b'ok\n'))
        first = json.loads(self.invoke('/work?rounds=10000')[1])
        second = json.loads(self.invoke('/work?rounds=10000')[1])
        self.assertEqual(first, second)
        self.assertEqual(first['rounds'], 10000)
        self.assertEqual(self.invoke('/work?rounds=1')[0], 400)

    def test_loadgen_emits_every_scheduled_request_and_analyzes_measurement(self):
        stream = io.StringIO()
        def response(_url, _phase, index, _timeout):
            return {'kind': 'request', 'phase': 'warmup' if index < 10 else 'measure',
                    'index': index, 'time': dt.datetime.now(dt.timezone.utc).isoformat(),
                    'ok': True, 'status': 200, 'latency_ms': 1}
        with patch('loadgen.request', side_effect=response), redirect_stdout(stream):
            run('http://example.invalid/work', 10, 1, 2, 2, 5)
        rows = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual(len(rows), 30)
        self.assertEqual(sum(row['phase'] == 'warmup' for row in rows), 10)
        report = analyze_rows(rows, 10, 2, 1)
        self.assertEqual(report['requests'], 20)
        self.assertEqual(report['successes'], 20)
        self.assertFalse(report['missing_or_duplicate_indexes'])
        self.assertIsNotNone(report['latency_ms']['p95'])


class S1AnalysisTests(unittest.TestCase):
    def test_compute_cpu_delta_and_unexpected_request_index(self):
        before = {'cpu_ticks': [10, 0, 10, 80, 0, 0, 0, 0]}
        after = {'cpu_ticks': [30, 0, 20, 150, 0, 0, 0, 0]}
        self.assertEqual(host_cpu_utilization(before, after), 0.3)
        before.update(time='2026-09-26T00:00:00+00:00', cpu_pressure=['some total=100'])
        after.update(time='2026-09-26T00:00:10+00:00', cpu_pressure=['some total=100100'])
        self.assertEqual(host_cpu_pressure(before, after), 0.01)
        stamp = dt.datetime(2026, 9, 26, tzinfo=dt.timezone.utc).isoformat()
        rows = [{'index': 2, 'phase': 'measure', 'time': stamp,
                 'ok': True, 'latency_ms': 1}]
        self.assertTrue(analyze_rows(rows, 1, 1, 0)['missing_or_duplicate_indexes'])

    def test_missing_request_and_http_error_are_visible(self):
        stamp = dt.datetime(2026, 9, 26, tzinfo=dt.timezone.utc).isoformat()
        rows = [{'index': 1, 'phase': 'measure', 'time': stamp,
                 'ok': False, 'latency_ms': 20, 'error': 'HTTPError'}]
        result = analyze_rows(rows, 2, 1)
        self.assertTrue(result['missing_or_duplicate_indexes'])
        self.assertEqual(result['errors'], {'HTTPError': 1})
        self.assertEqual(result['successful_rps'], 0)


if __name__ == '__main__':
    unittest.main()
