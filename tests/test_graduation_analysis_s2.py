"""S2 window analysis must recompute raw windows and skip negative cases."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / d) for d in ('scripts', 'evaluation')]
from graduation_analysis_s2 import analyse


def window(latency, upload, egress, rate=2_500_000):
    rows = [{'index': i, 'ok': True, 'bytes': 262144, 'latency_ms': latency + i} for i in range(120)]
    return {'rows': rows, 'elapsed': 60.0,
            'progress_before': {'bytes': 0}, 'progress_after': {'bytes': upload},
            'qdisc_before': [{'bytes': 0, 'overlimits': 0, 'drops': 0, 'options': {'rate': rate}}],
            'qdisc_after': [{'bytes': egress, 'overlimits': 5, 'drops': 0, 'options': {'rate': rate}}]}


class AnalysisS2Tests(unittest.TestCase):
    def test_condition_summary_uses_raw_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / 'run'
            evidence.mkdir()
            names = {'baseline': (100, 0), 'uncontrolled-0': (400, 110_000_000), 'uncontrolled-1': (420, 110_000_000),
                     'split-unlimited': (450, 110_000_000), 'fixed-0': (104, 12_000_000), 'fixed-1': (106, 12_000_000),
                     'stable-0': (110, 24_000_000), 'stable-1': (112, 24_000_000)}
            for name, (latency, upload) in names.items():
                (evidence / f'{name}.json').write_text(json.dumps(window(latency, upload, upload + 31_500_000)))
            (evidence / 'run.json').write_text(json.dumps({'policy_changes': [{'time': 't', 'kbps': 10000, 'burst_kbits': 250}]}))
            (root / 'campaign.json').write_text(json.dumps({'cases': {
                's2-fixed-first-01': {'id': 's2-fixed-first-01', 'scenario': 's2', 'evidence': str(evidence)},
                's2-qos-rejection': {'id': 's2-qos-rejection', 'scenario': 's2', 'negative': True, 'evidence': str(evidence)}}}))
            result = analyse(root)
        self.assertEqual([r['id'] for r in result['runs']], ['s2-fixed-first-01'])
        self.assertEqual(result['summary']['fixed']['upload_mbps']['median'], 1.6)
        self.assertEqual(result['summary']['split-unlimited']['runs'], 1)
        self.assertGreater(result['summary']['split-unlimited']['p95_ms']['median'],
                           result['summary']['fixed']['p95_ms']['median'])
        self.assertEqual(result['summary']['dynamic-stable']['failures'], 0)


if __name__ == '__main__':
    unittest.main()
