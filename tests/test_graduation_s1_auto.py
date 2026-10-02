"""Automatic S1 actions require complete evidence and an eligible destination."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from graduation_s1_auto import POLICY, S1Automatic, candidate_reasons, diagnose, requests


class AutomaticS1Tests(unittest.TestCase):
    def setUp(self):
        self.cpu = dict(usage_usec=100, user_usec=80, system_usec=20,
                        nr_periods=0, nr_throttled=0, throttled_usec=0)
        self.metrics = dict(cpu_utilization=.99, cpu_pressure_some=.12,
                            memory_pressure_some=0, io_pressure_some=0,
                            memory_available=2 * 1024**3)
        self.sample = dict(requests=300, duplicate_indexes=False,
                           max_sample_gap_seconds=.21, failures=0,
                           latency_ms={'p95': 180})
        self.baseline = dict(failures=0, latency_ms={'p95': 90})

    def diagnosis(self, **changes):
        args = dict(baseline=self.baseline, sample=self.sample, metrics=self.metrics,
                    cpu_before=self.cpu, cpu_after=self.cpu, baseline_pressure=.001, rate=5)
        args.update(changes)
        return diagnose(**args)

    def test_sustained_candidate_evidence(self):
        self.assertTrue(self.diagnosis()['trigger'])
        self.assertTrue(self.diagnosis(sample={**self.sample, 'failures': 300,
                                              'latency_ms': {'p95': None}})['trigger'])

    def test_incomplete_or_alternative_cause_never_triggers(self):
        cases = [dict(sample={**self.sample, 'requests': 200}),
                 dict(sample={**self.sample, 'duplicate_indexes': True}),
                 dict(sample={**self.sample, 'max_sample_gap_seconds': 4}),
                 dict(sample={**self.sample, 'latency_ms': {'p95': 100}}),
                 dict(metrics={**self.metrics, 'cpu_utilization': .2}),
                 dict(metrics={**self.metrics, 'cpu_pressure_some': .001}),
                 dict(metrics={**self.metrics, 'io_pressure_some': .03}),
                 dict(metrics={**self.metrics, 'memory_pressure_some': .03}),
                 dict(cpu_after={'error': 'unavailable'}),
                 dict(cpu_after={**self.cpu, 'nr_throttled': 1}),
                 dict(cpu_after={**self.cpu, 'usage_usec': 99})]
        for args in cases:
            with self.subTest(args=args):
                self.assertFalse(self.diagnosis(**args)['trigger'])

    def candidate(self, node=None, pods=None, spec=None, metrics=None):
        node = node or {'metadata': {'name': 'worker-b', 'labels': {'kubernetes.io/hostname': 'worker-b'}},
                       'spec': {}, 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}],
                                            'allocatable': {'cpu': '2', 'memory': '2Gi'}}}
        spec = spec or {'containers': [{'resources': {'requests': {'cpu': '250m', 'memory': '64Mi'}}}]}
        metrics = metrics or {**self.metrics, 'cpu_utilization': .1, 'cpu_pressure_some': .001}
        return candidate_reasons(node, pods or [], spec, 'compute-a', {'compute_host': 'compute-b'}, metrics)

    def test_destination_filters(self):
        self.assertEqual(self.candidate(), [])
        node = {'metadata': {'name': 'worker-b', 'labels': {}}, 'spec': {'unschedulable': True,
                'taints': [{'key': 'maintenance', 'effect': 'NoSchedule'}]},
                'status': {'conditions': [{'type': 'Ready', 'status': 'True'}],
                           'allocatable': {'cpu': '100m', 'memory': '32Mi'}}}
        reasons = self.candidate(node=node)
        self.assertTrue({'node_not_schedulable', 'untolerated_taint', 'insufficient_cpu',
                         'insufficient_memory'} <= set(reasons))
        self.assertIn('destination_cpu_busy', self.candidate(metrics=self.metrics))
        spec = {'containers': [], 'affinity': {'nodeAffinity': {
            'requiredDuringSchedulingIgnoredDuringExecution': {'nodeSelectorTerms': []}}}}
        self.assertIn('node_affinity', self.candidate(spec=spec))
        self.assertIn('node_selector', self.candidate(spec={'nodeSelector': {'disk': 'ssd'}}))

    def test_sidecar_and_init_requests_are_reserved(self):
        spec = {'containers': [{'resources': {'requests': {'cpu': '250m'}}}],
                'initContainers': [{'restartPolicy': 'Always', 'resources': {'requests': {'cpu': '100m'}}},
                                   {'resources': {'requests': {'cpu': '1'}}}]}
        self.assertEqual(str(requests(spec, 'cpu')), '1.100')

    def test_no_destination_means_no_deployment_mutation(self):
        runner = S1Automatic.__new__(S1Automatic)
        runner.s1 = Mock()
        runner.client = Mock()
        runner.client.cluster = "cluster"
        identity = dict(pod_uid='pod', nova_id='vm', image_id='image', container_id='container', restart_count=0)
        deployment = {'metadata': {'uid': 'deployment'}, 'spec': {'replicas': 1,
            'strategy': {'type': 'RollingUpdate', 'rollingUpdate': {'maxSurge': 1, 'maxUnavailable': 0}}}}
        record = {'service_before': identity, 'deployment_before': deployment, 'server_id': 'competitor',
                  'service_compute_host': 'compute-a'}
        runner.s1.verify.return_value = identity
        runner.s1.placement.return_value = {'compute_host': 'compute-a'}
        runner.server = Mock(return_value={'status': 'ACTIVE', 'OS-EXT-SRV-ATTR:host': 'compute-a'})
        runner.s1.obj.return_value = deployment
        runner.client.get.return_value = {'items': []}
        runner.write = Mock()
        with self.assertRaisesRegex(RuntimeError, 'no eligible destination'):
            runner.move_service(record)
        runner.s1.k.assert_not_called()
        self.assertEqual(runner.write.call_args.args[1], 'deferred')

    def test_existing_pods_consume_capacity(self):
        pods = [{'spec': {'nodeName': 'worker-b', 'containers': [
                    {'resources': {'requests': {'cpu': '2', 'memory': '1Gi'}}}]}}]
        self.assertIn('insufficient_cpu', self.candidate(pods=pods))
        pods[0]['status'] = {'phase': 'Succeeded'}
        self.assertNotIn('insufficient_cpu', self.candidate(pods=pods))

    def recovery_runner(self):
        runner = S1Automatic.__new__(S1Automatic)
        runner.s1 = Mock()
        runner.s1.k.return_value = '{}'
        runner.event = Mock()
        runner.write = Mock()
        record = {'rate': 5, 'baseline_window': {'latency_ms': {'p95': 90}}}
        good = {**self.sample, 'latency_ms': {'p95': 100}}
        bad = {**self.sample, 'latency_ms': {'p95': 110}}
        return runner, record, good, bad

    def test_stabilization_resets_after_bad_window_and_requires_three(self):
        runner, record, good, bad = self.recovery_runner()
        with patch('graduation_s1_auto.time.sleep'), \
                patch('graduation_s1_auto.summarize_window', side_effect=[good, bad, good, good, good]):
            runner.observe_recovery(record, 'load')
        self.assertEqual([call.args[1]['consecutive'] for call in runner.event.call_args_list], [1, 0, 1, 2, 3])
        self.assertEqual(len(record['stabilization_observations']), 5)
        self.assertEqual(record['stabilization_windows'], [good] * 3)
        self.assertEqual(runner.write.call_args.args[1], 'service-stable')
        self.assertTrue(all('patch' not in call.args for call in runner.s1.k.call_args_list))

    def test_stabilization_is_bounded_and_does_not_claim_recovery(self):
        runner, record, _, bad = self.recovery_runner()
        with patch('graduation_s1_auto.time.sleep'), \
                patch('graduation_s1_auto.summarize_window', return_value=bad):
            runner.observe_recovery(record, 'load')
        self.assertEqual(len(record['stabilization_observations']), POLICY['recovery_max_windows'])
        self.assertEqual(runner.write.call_args.args[1], 'recovery-needs-review')
        self.assertIsNone(runner.write.call_args.kwargs['recovery_confirmed_at'])


if __name__ == '__main__':
    unittest.main()
