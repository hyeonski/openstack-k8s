"""Evaluation controls must retain non-successes and refuse changed evidence."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from graduation_evaluation import schedule, Campaign, interruption_ready
from graduation_evaluation_case import EvaluationS1, OrderedWorkers, run_s3_step
from graduation_evaluation_verify import percentile, verify_s2, verify_negative
from graduation_s1_contention import S1Contention
from graduation_s2 import S2
from graduation_s4_run import require_fresh_fixture


class EvaluationTests(unittest.TestCase):
    def test_cohort_has_five_repeats_and_counterbalanced_orders(self):
        profile = json.loads((ROOT / 'config/graduation-evaluation.json').read_text())
        cases = schedule(profile)
        self.assertEqual(len(cases), 34)
        self.assertEqual(len({x['id'] for x in cases}), 34)
        for scenario, mode in [('s1', 'automatic'), ('s1', 'no-action'), ('s3', 'automatic'), ('s3', 'runbook'), ('s4', 'normal')]:
            self.assertEqual(sum(c['scenario'] == scenario and c['mode'] == mode for c in cases), 5)
        self.assertEqual([c['mode'] for c in cases if c['scenario'] == 's2' and not c['negative']],
                         ['fixed-first', 'dynamic-first', 'fixed-first', 'dynamic-first', 'fixed-first'])
        self.assertEqual(sum(c['negative'] for c in cases), 4)
        self.assertEqual([c['id'] for c in cases[:2]], ['s4-normal-01', 's4-interrupt-resume'])

    def test_no_action_validity_does_not_claim_recovery(self):
        runner = EvaluationS1.__new__(EvaluationS1)
        runner.mode = 'no-action'
        summary = {'latency_recovery_within_1_2x': False, 'recovery_checks': {'no_action': True}}
        result = runner.evaluation_result(summary, True)
        self.assertEqual(result['state'], 'control_valid')
        self.assertFalse(result['latency_recovery_within_1_2x'])
        self.assertEqual(runner.evaluation_result(copy.deepcopy(summary), False)['state'], 'needs_review')
        summary['recovery_checks']['no_action'] = False
        self.assertEqual(runner.evaluation_result(summary, True)['state'], 'needs_review')

    def test_automatic_recovery_still_requires_original_checks(self):
        runner = S1Contention.__new__(S1Contention)
        for valid, recovered, checks in [(False, True, True), (True, False, True), (True, True, False)]:
            summary = {'latency_recovery_within_1_2x': recovered, 'recovery_checks': {'all': checks}}
            self.assertEqual(runner.evaluation_result(summary, valid)['state'], 'needs_review')

    def test_no_action_refuses_external_pod_movement(self):
        runner = EvaluationS1.__new__(EvaluationS1)
        runner.mode, runner.s1 = 'no-action', Mock()
        before = dict(pod_uid='a', node='node-a', nova_id='vm', image_id='image', container_id='container', restart_count=0)
        with self.assertRaisesRegex(RuntimeError, 'changed by another actor'):
            runner.verify_intervention({'service_before': before}, {**before, 'pod_uid': 'b'})

    def test_dynamic_policy_backs_off_once_without_reexploration(self):
        runner = S2.__new__(S2)
        runner.set_rate = Mock()
        good = dict(complete=True, failures=0, p95_ms=100, upload_bytes=100)
        bad = {**good, 'p95_ms': 200}
        runner.window = Mock(side_effect=[good, good, bad, good, good])
        history, windows = runner.dynamic_windows(100)
        self.assertEqual([x.args[0] for x in runner.set_rate.call_args_list], [6000, 10000, 14000, 10000])
        self.assertEqual(history[-1], {'rate': 14000, 'healthy': False})
        self.assertEqual(len(windows), 2)

    def test_dynamic_policy_stops_at_floor_and_cap(self):
        runner = S2.__new__(S2)
        runner.set_rate = Mock()
        bad = dict(complete=True, failures=1, p95_ms=100, upload_bytes=100)
        runner.window = Mock(return_value=bad)
        with self.assertRaisesRegex(RuntimeError, 'minimum allowed'):
            runner.dynamic_windows(100)
        self.assertEqual(runner.set_rate.call_count, 1)
        runner.set_rate.reset_mock()
        runner.window = Mock(return_value={**bad, 'failures': 0})
        history, _ = runner.dynamic_windows(100)
        self.assertEqual([x['rate'] for x in history], [6000, 10000, 14000, 18000])
        self.assertEqual(runner.set_rate.call_count, 5)

    def test_frozen_source_change_is_rejected(self):
        runner = Campaign.__new__(Campaign)
        runner.data = {'source_sha256': {'controller.py': 'old'}}
        with patch('graduation_evaluation.hashes', return_value={'controller.py': 'new'}):
            with self.assertRaisesRegex(RuntimeError, 'frozen evaluation source changed'):
                runner.check_source()

    def test_s4_repeat_requires_finalization_and_new_fixture_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            prior = {'environment_run_id': 'env', 'phase': 'completed', 'evidence': directory,
                     'preparation_run_id': 'prep-old', 'mhc_uid': 'mhc-old'}
            prepared = {'environment_run_id': 'env', 'run_id': 'prep-new', 'mhc_uid': 'mhc-new'}
            with self.assertRaisesRegex(RuntimeError, 'new restored fixture'):
                require_fresh_fixture(prior, prepared)
            (Path(directory) / 'finalization.json').write_text(json.dumps({'fixture_phase': 'restored'}))
            require_fresh_fixture(prior, prepared)
            for changed in ({'run_id': 'prep-old'}, {'mhc_uid': 'mhc-old'}):
                with self.assertRaisesRegex(RuntimeError, 'new restored fixture'):
                    require_fresh_fixture(prior, {**prepared, **changed})
            with self.assertRaisesRegex(RuntimeError, 'new restored fixture'):
                require_fresh_fixture({**prior, 'phase': 'failed'}, prepared)

    def test_s4_interruption_requires_current_injected_run(self):
        with tempfile.TemporaryDirectory() as directory:
            observed = Path(directory) / 'observations'
            observed.mkdir()
            (observed / '0000.json').write_text('{}')
            record = dict(run_id='current', environment_run_id='env', phase='injected',
                          created='2026-10-02T12:00:01+00:00', injected_at='2026-10-02T12:01:00+00:00', evidence=directory)
            started = '2026-10-02T12:00:00+00:00'
            self.assertTrue(interruption_ready(record, 'prior', 'env', started))
            self.assertFalse(interruption_ready(record, 'current', 'env', started))
            for changes in ({'phase': 'completed'}, {'environment_run_id': 'old-env'},
                            {'created': '2026-10-02T11:00:00+00:00'}, {'injected_at': None}, {'created': 'invalid'}):
                self.assertFalse(interruption_ready({**record, **changes}, 'prior', 'env', started))
            (observed / '0000.json').unlink()
            self.assertFalse(interruption_ready(record, 'prior', 'env', started))

    def test_interpolated_quantile_matches_contract(self):
        self.assertEqual(percentile([0, 10]), 9.5)
        self.assertIsNone(percentile([]))
        self.assertEqual(percentile([7]), 7)

    def test_negative_audit_does_not_trust_passed_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def put(name, value):
                (root / name).write_text(json.dumps(value))
            pod = {'metadata': {'uid': 'pod'}, 'spec': {'nodeName': 'node'}}
            port = {'id': 'port', 'device_id': 'vm', 'qos_policy_id': None}
            rule = {'id': 'rule', 'max_kbps': 6000, 'max_burst_kbps': 600, 'direction': 'egress'}
            raw = {'before': {'pod': pod, 'port': port, 'rule': rule},
                   'after': {'pods': [pod], 'port': port, 'rule': rule}}
            put('expected-rejection.json', {'passed': True, 'checks': {'request_rejected': True}})
            put('run.json', {})
            put('negative-raw.json', raw)
            self.assertTrue(all(verify_negative(root, 's2').values()))
            raw['after']['port'] = {**port, 'qos_policy_id': 'unexpected'}
            put('negative-raw.json', raw)
            self.assertFalse(verify_negative(root, 's2')['raw_port_policy_unchanged'])

    def test_s2_audit_detects_missing_requests_and_tampered_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def put(name, value):
                (root / name).write_text(json.dumps(value))
            names = ['baseline', 'uncontrolled-0', 'uncontrolled-1', 'fixed-0', 'fixed-1', 'stable-0', 'stable-1']
            raw = {'rows': [{'index': i, 'ok': True, 'latency_ms': 100} for i in range(120)],
                   'progress_before': {'bytes': 0}, 'progress_after': {'bytes': 100},
                   'qdisc_before': [{'bytes': 0}], 'qdisc_after': [{'bytes': 600}], 'elapsed': 60}
            expected = dict(p95_ms=100, upload_bytes=100, egress_bps=80)
            put('summary.json', {'windows': {name: expected for name in names}})
            pod = {'status': {'containerStatuses': [{'imageID': 'image'}]}}
            put('run.json', {'workers': [{'host': 'osk8s-compute02'}, {'host': 'osk8s-compute01'}],
                             'policy_changes': [{'burst_kbits': 250, 'kbps': 6000, 'ovs': [['if', 6000, 250]]}],
                             'api_before': pod, 'upload_before': pod})
            payload = hashlib.sha256(b'0').digest() * (1024 * 1024 // 32)
            put('upload-integrity.json', {'rows': [[0, len(payload), hashlib.sha256(payload).hexdigest()]], 'bytes': len(payload), 'all_files_valid': True})
            for name in names:
                put(name + '.json', raw)
            checks, _, _ = verify_s2(root)
            self.assertTrue(all(checks.values()))
            raw['rows'].pop()
            put('baseline.json', raw)
            checks, _, _ = verify_s2(root)
            self.assertFalse(checks['baseline_sample_indexes'])
            changed = {'windows': {name: dict(expected) for name in names}}
            changed['windows']['fixed-0']['p95_ms'] = 99
            put('summary.json', changed)
            checks, _, _ = verify_s2(root)
            self.assertFalse(checks['fixed-0_metrics'])
            put('upload-integrity.json', {'rows': [], 'bytes': 0, 'all_files_valid': True})
            checks, _, _ = verify_s2(root)
            self.assertFalse(checks['upload_manifest_complete'])


if __name__ == '__main__':
    unittest.main()
