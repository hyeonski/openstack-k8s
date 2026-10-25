"""Per-layer signal table must read raw snapshots and keep negative cases out."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / d) for d in ('scripts', 'evaluation')]
from graduation_analysis_signals import analyse, summarise


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))


def window(p95, failures=0):
    return {'start': 't', 'failures': failures, 'latency_ms': {'p95': p95}}


class SignalTests(unittest.TestCase):
    def test_summarise_kinds(self):
        self.assertEqual(summarise([True, False, None]), '1/2 true')
        self.assertEqual(summarise([1, 3, 2]), 'median 2 (1~3)')
        self.assertEqual(summarise(['ACTIVE', 'ACTIVE']), 'ACTIVE x2')

    def test_s1_and_s4_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            s1 = root / 's1'
            service = {'pod_uid': 'p', 'state': 'ready', 'restart_count': 0}
            write(s1 / 'run.json', {'service_compute_host': 'c2', 'target_compute_host': 'c1', 'service_before': service,
                                    'service_after': service, 'baseline_window': window(70)})
            metrics = {'c2': {'cpu_utilization': .99, 'cpu_pressure_some': .24, 'memory_pressure_some': 0,
                              'io_pressure_some': .01},
                       'c1': {'cpu_utilization': .1, 'cpu_pressure_some': 0, 'memory_pressure_some': 0,
                              'io_pressure_some': 0}}
            write(s1 / 'decisions.jsonl', '\n'.join(json.dumps(
                {'kind': 'diagnosis', 'window': window(p), 'host_metrics': metrics,
                 'pod_cpu_delta': {'nr_throttled': 0}}) for p in (150, 154)) + '\n')
            write(s1 / 'contender-server.json', {'OS-EXT-SRV-ATTR:host': 'c2'})
            write(s1 / 'placement-before.json', {'service': {'compute_host': 'c2'}})
            s4 = root / 's4'
            write(s4 / 'analysis' / 'summary.json', {'target': {'node': 'w1', 'nova_id': 'v1'},
                                                     'service': {'failures': 29, 'requests': 220}})
            write(s4 / 'observations' / '0000.json', {
                'nodes': {'items': [{'metadata': {'name': 'w1'}, 'status': {'conditions': [
                    {'type': 'Ready', 'status': 'Unknown'}]}, 'spec': {'taints': [{'key': 'node.kubernetes.io/unreachable'}]}}]},
                'pods': {'items': [{'spec': {'nodeName': 'w1'}, 'status': {'conditions': [
                    {'type': 'Ready', 'status': 'False'}]}}]},
                'nova': [{'ID': 'v1', 'Status': 'SHUTOFF'}]})
            write(root / 'campaign.json', {'cases': [
                {'id': 's1-no-action-01', 'scenario': 's1', 'mode': 'no-action', 'accepted': True, 'evidence': str(s1)},
                {'id': 's1-no-destination', 'scenario': 's1', 'mode': 'no-destination', 'negative': True,
                 'accepted': True, 'evidence': str(s1)},
                {'id': 's4-normal-01', 'scenario': 's4', 'mode': 'normal', 'accepted': True, 'evidence': str(s4)}]})
            result = analyse(root)
        runs = {r['id']: r['signals'] for r in result['runs']}
        self.assertEqual(set(runs), {'s1-no-action-01', 's4-normal-01'})
        self.assertEqual(runs['s1-no-action-01']['service.p95_ratio'], 2.2)
        self.assertTrue(runs['s1-no-action-01']['infrastructure.same_compute_as_contender'])
        self.assertTrue(runs['s1-no-action-01']['kubernetes.pod_ready_unchanged'])
        self.assertEqual(runs['s4-normal-01']['kubernetes.target_node_ready'], 'Unknown')
        self.assertEqual(runs['s4-normal-01']['infrastructure.target_vm_status'], 'SHUTOFF')


if __name__ == '__main__':
    unittest.main()
