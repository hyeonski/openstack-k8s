"""S1's direct HTTP workload and baseline sampler produce auditable records."""
from contextlib import redirect_stdout
import datetime as dt
import fcntl
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'kubernetes/graduation-s1'))
from app import Handler
from graduation_s1 import S1, analyze_rows, host_cpu_pressure, host_cpu_utilization, pod_cpu_delta
from graduation_s1_contention import (S1Contention, load_job, recovery_controls,
                                      stress_user_data, summarize_window)
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
    def test_recovery_requires_same_image_and_persistent_source_contention(self):
        record = {'service_compute_host': 'compute02', 'server_id': 'server-1',
                  'service_before': {'image_id': 'image-1'}}
        moved = {'image_id': 'image-1'}
        metrics = {'baseline': {'compute02': {'cpu_pressure_some': .005}},
                   'relocated': {'compute02': {'cpu_utilization': .98,
                                              'cpu_pressure_some': .08}},
                   'completion': {'compute02': {'cpu_utilization': .98,
                                               'cpu_pressure_some': .08}}}
        contender = {'id': 'server-1', 'status': 'ACTIVE',
                     'OS-EXT-SRV-ATTR:host': 'compute02'}
        self.assertTrue(all(recovery_controls(record, moved, metrics, contender).values()))
        metrics['relocated']['compute02'] = {'cpu_utilization': .05,
                                              'cpu_pressure_some': .001}
        self.assertFalse(recovery_controls(record, moved, metrics, contender)[
            'source_contention_persisted'])
        metrics['relocated']['compute02'] = {'cpu_utilization': .98,
                                              'cpu_pressure_some': .08}
        metrics['completion']['compute02'] = {'cpu_utilization': .05,
                                               'cpu_pressure_some': .001}
        self.assertFalse(recovery_controls(record, moved, metrics, contender)[
            'source_contention_at_completion'])
        metrics['completion']['compute02'] = {'cpu_utilization': .98,
                                               'cpu_pressure_some': .08}
        moved['image_id'] = 'image-2'
        self.assertFalse(recovery_controls(record, moved, metrics, contender)['image_unchanged'])
        moved['image_id'] = 'image-1'
        contender['status'] = 'SHUTOFF'
        self.assertFalse(recovery_controls(record, moved, metrics, contender)[
            'competitor_active_on_source'])

    def test_contention_windows_and_bounded_guest_stress(self):
        start = dt.datetime(2026, 9, 26, tzinfo=dt.timezone.utc).timestamp()
        rows = [{'time': dt.datetime.fromtimestamp(start + offset, dt.timezone.utc).isoformat(),
                 'index': offset, 'ok': offset != 2, 'latency_ms': 10 + offset}
                for offset in range(4)]
        window = summarize_window(rows, start + 1, start + 4)
        self.assertEqual((window['requests'], window['successes'], window['failures']),
                         (3, 2, 1))
        self.assertEqual(window['latency_ms']['p95'], 12.9)
        self.assertFalse(window['duplicate_indexes'])
        job = load_job('sample', 'control-plane', 5, 100000, 780)
        self.assertEqual(job['spec']['template']['spec']['nodeName'], 'control-plane')
        self.assertEqual(job['metadata']['labels']['openstack-k8s.dev/experiment'],
                         'graduation-s1')
        self.assertIn('time.sleep(1200)', stress_user_data(780))
        self.assertIn('timeout 1230s', stress_user_data(780))
        self.assertIn('time.sleep(2160)', stress_user_data(1800))
        self.assertIn('timeout 2190s', stress_user_data(1800))

    def test_pod_cpu_counters_must_exist_and_remain_monotonic(self):
        before = {'usage_usec': 100, 'user_usec': 80, 'system_usec': 20,
                  'nr_periods': 10, 'nr_throttled': 0, 'throttled_usec': 0}
        after = {**before, 'usage_usec': 150, 'user_usec': 120,
                 'system_usec': 30, 'nr_periods': 12}
        self.assertEqual(pod_cpu_delta(before, after),
                         ({'usage_usec': 50, 'user_usec': 40, 'system_usec': 10,
                           'nr_periods': 2, 'nr_throttled': 0, 'throttled_usec': 0}, []))
        self.assertTrue(pod_cpu_delta({'error': 'cgroup unavailable'}, after)[1])
        self.assertTrue(pod_cpu_delta(before, {'usage_usec': 150})[1])
        self.assertTrue(pod_cpu_delta(before, {**after, 'nr_periods': 9})[1])

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


class S1LifecycleTests(unittest.TestCase):
    def test_interrupted_contention_cleanup_saves_job_before_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            s1 = Mock()
            s1.lock_path = Path(directory) / 's1.lock'
            s1.client.state = Path(directory)
            s1.environment.return_value = {'run_id': 'env-1'}
            s1.obj.return_value = {'metadata': {'uid': 'job-uid',
                'labels': {'openstack-k8s.dev/experiment': 'graduation-s1'}}}
            s1.client.get.return_value = {'items': [{'metadata': {'name': 'probe'}}]}
            events = []
            def kubectl(*args, **_kwargs):
                if 'logs' in args:
                    events.append('logs')
                    return '{"index":0,"ok":true}\n'
                if args[0] == 'delete':
                    events.append('delete')
                return ''
            s1.k.side_effect = kubectl
            runner = S1Contention(s1)
            record = {'evidence': directory, 'phase': 'failed',
                      'environment_run_id': 'env-1', 'job_name': 'job',
                      'job_uid': 'job-uid'}
            runner.read = Mock(return_value=record)
            runner.write = Mock(side_effect=lambda saved, phase, **values:
                                saved.update(values, phase=phase))
            def remove(_record):
                events.append('contender')
                raise RuntimeError('Nova unavailable')
            runner.remove_competitor = Mock(side_effect=remove)
            with self.assertRaisesRegex(RuntimeError, 'Nova unavailable'):
                runner.cleanup()
            self.assertEqual(events, ['logs', 'delete', 'contender'])
            self.assertEqual((Path(directory) / 'http.jsonl').read_text(),
                             '{"index":0,"ok":true}\n')
            self.assertTrue(record['failure_evidence']['http_log_saved'])
            self.assertEqual(record['phase'], 'cleanup-failed')

    def test_failed_contention_saves_http_before_deleting_job(self):
        with tempfile.TemporaryDirectory() as directory:
            s1 = Mock()
            s1.client.state = Path(directory)
            s1.obj.return_value = {'metadata': {'uid': 'job-uid',
                'labels': {'openstack-k8s.dev/experiment': 'graduation-s1'}}}
            s1.client.get.return_value = {'items': [{'metadata': {'name': 'probe'}}]}
            s1.host_stat.return_value = {'time': '2026-09-26T00:00:00+00:00'}
            s1.cpu_stat.return_value = {'usage_usec': 1}
            events = []
            def kubectl(*args, **_kwargs):
                if 'logs' in args:
                    events.append('logs')
                    return '{"index":0,"ok":true}\n'
                if args[0] == 'delete':
                    events.append('delete')
                return ''
            s1.k.side_effect = kubectl
            runner = S1Contention(s1)
            runner.wait_probe_samples = Mock()
            runner.create_competitor = Mock(side_effect=RuntimeError('stress did not start'))
            def write(record, phase, **values):
                record.update(values, phase=phase)
            runner.write = Mock(side_effect=write)
            record = {'evidence': directory, 'rate': 5, 'rounds': 100000,
                      'seconds': 780, 'service_compute_host': 'compute02',
                      'target_compute_host': 'compute01',
                      'service_before': {'pod': 'http-pod'}}
            with patch('graduation_s1_contention.time.sleep'):
                with self.assertRaisesRegex(RuntimeError, 'stress did not start'):
                    runner.run_locked(record, 'control-plane')
            self.assertEqual(events, ['logs', 'delete'])
            self.assertEqual((Path(directory) / 'http.jsonl').read_text(),
                             '{"index":0,"ok":true}\n')
            captured = json.loads((Path(directory) / 'failure-evidence.json').read_text())
            self.assertTrue(captured['http_log_saved'])
            self.assertEqual(captured['http_log_lines'], 1)
            self.assertEqual(record['phase'], 'failed')

    def test_baseline_holds_preparation_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            s1 = S1(SimpleNamespace(state=Path(directory), cluster='cluster'))
            with s1.lock_path.open('a+') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(s1, '_baseline_locked') as measure:
                    with self.assertRaises(BlockingIOError):
                        s1.baseline(5, 100000, 60, 300, 5, 50)
                    measure.assert_not_called()
            def measure(*_args):
                with s1.lock_path.open('a+') as competing:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return {'state': 'complete'}
            with patch.object(s1, '_baseline_locked', side_effect=measure):
                self.assertEqual(s1.baseline(5, 100000, 60, 300, 5, 50),
                                 {'state': 'complete'})

    def test_cleanup_removes_owned_resources_before_worker_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            s1 = S1(SimpleNamespace(state=Path(directory), cluster='cluster', ns='system'))
            record = {'version': 1, 'phase': 'prepared', 'environment_run_id': 'env',
                      'cluster_uid': 'cluster-uid', 'md_uid': 'md-uid',
                      'namespace_uid': 'namespace-uid', 'original_mode': 'fixed',
                      'original_workers': 1, 'resource_uids': {}}
            namespace = {'metadata': {'uid': 'namespace-uid',
                                      'labels': {'openstack-k8s.dev/experiment': 'graduation-s1'}}}
            s1.read = Mock(return_value=record)
            s1.environment = Mock(return_value={'run_id': 'env'})
            s1.client.get = Mock(side_effect=lambda _where, kind, *_args: {
                'cluster': {'metadata': {'uid': 'cluster-uid'}},
                'machinedeployment': {'metadata': {'uid': 'md-uid'}},
                'pods,replicasets,deployments,services,configmaps,secrets,persistentvolumeclaims,jobs':
                    {'items': []}}[kind])
            seen_namespace = False
            def obj(kind, *_args):
                nonlocal seen_namespace
                if kind == 'namespace' and not seen_namespace:
                    seen_namespace = True
                    return namespace
                return None
            s1.obj = Mock(side_effect=obj)
            s1.k = Mock()
            def write(saved, phase, **values):
                saved.update(values, phase=phase)
            s1.write = Mock(side_effect=write)
            s1.require_identity = Mock(side_effect=RuntimeError('worker unstable'))
            with self.assertRaisesRegex(RuntimeError, 'worker unstable'):
                s1.cleanup()
            s1.k.assert_called_once_with('delete', 'namespace', 'graduation-s1',
                                         '--wait=true', '--timeout=5m', timeout=330)
            self.assertEqual(record['phase'], 'cleanup-failed')
            self.assertEqual(record['cleanup_stage'], 'worker-restore')
            self.assertTrue(record['resources_removed'])
            s1.require_identity = Mock(return_value=('fixed', {'workers': 1}))
            s1.worker = Mock(return_value=('fixed', {'workers': 1}))
            self.assertEqual(s1.cleanup()['phase'], 'restored')
            s1.k.assert_called_once()


if __name__ == '__main__':
    unittest.main()
