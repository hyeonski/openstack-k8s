"""Offline transport regressions; no experiment or cloud mutations."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / d) for d in ('evaluation', 'scripts', 'experiments')]
from fresh_transport import retry_read, read_command, transient_transport_error, transport_lock


class Clock:
    def __init__(self): self.now = 0
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds


class TransportTests(unittest.TestCase):
    def run_read(self, invoke, args, *, timeout=30, identity=None, reconnect=None, data=None):
        clock = Clock()
        identity = identity or Mock()
        reconnect = reconnect or Mock()
        with tempfile.TemporaryDirectory() as folder:
            result = retry_read(invoke, args, timeout=timeout, identity=identity,
                reconnect=reconnect, evidence=folder, data=data,
                clock=clock, sleep=clock.sleep)
            log = Path(folder) / 'transport-read-attempts.jsonl'
            records = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, records, clock

    def test_wait_disconnect_reconnect_same_job_completion_and_real_logs(self):
        events = []
        invoke = Mock(side_effect=[RuntimeError('connection reset by peer'), 'job/owned complete'])
        identity = Mock(side_effect=lambda remaining: events.append(('uid', remaining())))
        reconnect = Mock(side_effect=lambda remaining: events.append(('repair', remaining())))
        result, records, clock = self.run_read(invoke,
            ['-n', 'ns', 'wait', '--for=condition=complete', 'job/owned', '--timeout=30s'],
            identity=identity, reconnect=reconnect)
        self.assertEqual(result, 'job/owned complete')
        self.assertEqual([event[0] for event in events], ['repair', 'uid', 'uid'])
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(invoke.call_args.kwargs['timeout'], 29)
        self.assertIn('--timeout=29.0s', invoke.call_args.args[0])
        self.assertEqual(len(records), 2)
        self.assertTrue(all(row['observation_filled'] is False for row in records))
        self.assertNotIn('captured', records[0])

    def test_get_and_logs_are_retried_but_exec_and_mutations_are_once(self):
        for args in (['get', 'job', 'owned', '-o', 'json'], ['logs', 'job/owned']):
            invoke = Mock(side_effect=[RuntimeError('connection refused'), 'actual bytes'])
            result, _, _ = self.run_read(invoke, args)
            self.assertEqual(result, 'actual bytes')
            self.assertEqual(invoke.call_count, 2)
        for args in (['patch', 'deployment', 'http'], ['delete', 'job', 'owned'],
                     ['create', '-f', '-'], ['exec', 'pod', '--', 'get'],
                     ['rollout', 'restart', 'deployment/http']):
            invoke = Mock(side_effect=RuntimeError('connection reset'))
            with self.assertRaisesRegex(RuntimeError, 'connection reset'):
                self.run_read(invoke, args)
            self.assertEqual(invoke.call_count, 1)

    def test_changed_job_uid_stops_before_second_read(self):
        invoke = Mock(side_effect=RuntimeError('connection refused'))
        identity = Mock(side_effect=RuntimeError('Job UID changed'))
        with self.assertRaisesRegex(RuntimeError, 'Job UID changed'):
            self.run_read(invoke, ['wait', 'job/owned'], identity=identity)
        self.assertEqual(invoke.call_count, 1)

    def test_permanent_error_is_not_retried(self):
        for error in ('Forbidden', 'Unauthorized', 'NotFound', 'permission denied',
                      'timed out waiting for condition'):
            invoke = Mock(side_effect=RuntimeError(error))
            reconnect = Mock()
            with self.assertRaisesRegex(RuntimeError, error):
                self.run_read(invoke, ['get', 'job', 'owned'], reconnect=reconnect)
            self.assertEqual(invoke.call_count, 1)
            reconnect.assert_not_called()

    def test_repeated_errors_have_fixed_attempt_cap(self):
        invoke = Mock(side_effect=RuntimeError('connection refused'))
        with self.assertRaisesRegex(RuntimeError, 'connection refused'):
            self.run_read(invoke, ['logs', 'job/owned'])
        self.assertEqual(invoke.call_count, 3)

    def test_reconnect_identity_and_backoff_share_original_total_deadline(self):
        clock = Clock(); calls = []
        def invoke(args, **kwargs):
            calls.append(kwargs['timeout']);clock.sleep(4)
            raise RuntimeError('connection reset')
        def reconnect(remaining):
            clock.sleep(remaining())
            remaining()
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(TimeoutError, 'deadline'):
            retry_read(invoke, ['wait', 'job/owned', '--timeout=10s'], timeout=10,
                identity=Mock(), reconnect=reconnect, evidence=folder,
                clock=clock, sleep=clock.sleep)
        self.assertEqual(calls, [10])
        self.assertEqual(clock.now, 10)

    def test_reconnect_delays_never_reset_kubectl_wait_timeout(self):
        clock = Clock(); calls = []
        def invoke(args, **kwargs):
            calls.append((args, kwargs['timeout']))
            if len(calls) == 1:
                clock.sleep(4);raise RuntimeError('Broken pipe')
            return 'complete'
        def reconnect(remaining): clock.sleep(5);remaining()
        with tempfile.TemporaryDirectory() as folder:
            retry_read(invoke, ['wait', 'job/owned', '--timeout=30s'], timeout=30,
                identity=Mock(), reconnect=reconnect, evidence=folder,
                clock=clock, sleep=clock.sleep)
        self.assertEqual(calls[1][1], 20)
        self.assertIn('--timeout=20.0s', calls[1][0])

    def test_read_classifier_handles_flags_and_rejects_mutation_payload(self):
        self.assertTrue(read_command(['-n', 'ns', 'rollout', 'status', 'deployment/http']))
        self.assertFalse(read_command(['get', 'job'], data='payload'))
        self.assertFalse(transient_transport_error(RuntimeError('Forbidden connection refused')))

    def test_success_returned_after_deadline_is_not_accepted(self):
        clock = Clock()
        def invoke(*args, **kwargs): clock.sleep(11);return 'late'
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(TimeoutError):
            retry_read(invoke, ['get', 'job'], timeout=10, identity=Mock(),
                reconnect=Mock(), evidence=folder, clock=clock, sleep=clock.sleep)

    def test_shared_reconnect_lock_prevents_two_repair_processes(self):
        with tempfile.TemporaryDirectory() as folder:
            state = {'reachable':False, 'repairs':0};barrier=threading.Barrier(2)
            def caller():
                barrier.wait();end=time.monotonic()+2
                def remaining():
                    value=end-time.monotonic()
                    if value<=0:raise TimeoutError()
                    return value
                with transport_lock(folder, remaining):
                    if not state['reachable']:
                        state['repairs']+=1;time.sleep(.02);state['reachable']=True
            threads=[threading.Thread(target=caller) for _ in range(2)]
            for t in threads:t.start()
            for t in threads:t.join(3)
            self.assertTrue(all(not t.is_alive() for t in threads))
            self.assertEqual(state['repairs'],1)

    def test_s1_actual_wrapper_preserves_job_uid_and_collects_same_logs(self):
        from fresh_scenarios import FreshS1
        with tempfile.TemporaryDirectory() as folder:
            runner=FreshS1.__new__(FreshS1);runner.ev=SimpleNamespace(directory=Path(folder))
            record={'fresh_attempt':str(Path(folder).resolve()),'job_uid':'uid-original','job_name':'owned'}
            runner.read=Mock(return_value=record)
            calls=[]
            def k(*args, **kwargs):
                calls.append(args)
                if args[:3]==('get','job','owned'):return json.dumps({'metadata':{'uid':'uid-original'}})
                if sum('logs' in a for a in calls)==1:raise RuntimeError('connection refused')
                return 'actual request log'
            runner.s1=SimpleNamespace(k=k)
            runner.client=SimpleNamespace(k=Mock(),state=Path(folder),deadline=None,remaining=lambda n:n)
            with patch.dict('os.environ',{'WORKLOAD_LOCAL_API_PORT':'16444'}), \
                 patch('fresh_transport.listener_reachable',return_value=False), \
                 patch('fresh_scenarios.subprocess.run',return_value=SimpleNamespace(returncode=0)) as repair:
                with runner.transport_reads():
                    self.assertEqual(runner.s1.k('logs','job/owned',timeout=5),'actual request log')
                self.assertEqual(repair.call_count,1)
            self.assertEqual(sum(args[:3]==('get','job','owned') for args in calls),2)
            self.assertEqual(sum('logs' in args for args in calls),2)
            self.assertIs(runner.s1.k,k)

    def test_s1_client_get_retry_checks_uid_without_changing_shared_deadline(self):
        from fresh_scenarios import FreshS1
        with tempfile.TemporaryDirectory() as folder:
            runner=FreshS1.__new__(FreshS1);runner.ev=SimpleNamespace(directory=Path(folder))
            runner.read=Mock(return_value={'fresh_attempt':str(Path(folder).resolve()),'job_uid':'one','job_name':'owned'})
            runner.s1=SimpleNamespace(k=Mock(return_value='{"metadata":{"uid":"one"}}'))
            original=Mock();runner.client=SimpleNamespace(k=original,state=Path(folder),
                cluster='cluster',deadline=None,remaining=lambda n:n)
            with patch.dict('os.environ',{'WORKLOAD_LOCAL_API_PORT':'16444'}), \
                 patch('fresh_transport.listener_reachable',return_value=True), \
                 patch('workload_state.command',side_effect=[RuntimeError('connection reset'),'{"items":[]}']) as command:
                with runner.transport_reads():
                    self.assertEqual(runner.client.k('w','get','pods','-o','json'),'{"items":[]}')
                self.assertEqual(command.call_count,2)
                self.assertLess(command.call_args.kwargs['timeout'],30)
            self.assertIsNone(runner.client.deadline)
            self.assertIs(runner.client.k,original)

    def test_actual_s1_wrapper_rejects_replaced_job_before_reissuing_logs(self):
        from fresh_scenarios import FreshS1
        with tempfile.TemporaryDirectory() as folder:
            runner=FreshS1.__new__(FreshS1);runner.ev=SimpleNamespace(directory=Path(folder))
            runner.read=Mock(return_value={'fresh_attempt':str(Path(folder).resolve()),'job_uid':'one','job_name':'owned'})
            calls=[]
            def k(*args,**kwargs):
                calls.append(args)
                if args[0]=='logs':raise RuntimeError('connection refused')
                return '{"metadata":{"uid":"replacement"}}'
            runner.s1=SimpleNamespace(k=k);runner.client=SimpleNamespace(k=Mock(),state=Path(folder))
            with patch.dict('os.environ',{'WORKLOAD_LOCAL_API_PORT':'16444'}),patch('fresh_transport.listener_reachable',return_value=True):
                with runner.transport_reads(),self.assertRaisesRegex(RuntimeError,'Job UID changed'):
                    runner.s1.k('logs','job/owned',timeout=5)
            self.assertEqual(sum(args[0]=='logs' for args in calls),1)

    def test_identity_changed_during_retried_wait_rejects_success(self):
        invoke=Mock(side_effect=[RuntimeError('connection reset'),'complete'])
        identity=Mock(side_effect=[None,RuntimeError('Job UID changed during read')])
        with self.assertRaisesRegex(RuntimeError,'UID changed during read'):
            self.run_read(invoke,['wait','job/owned'],identity=identity)
        self.assertEqual(invoke.call_count,2)


if __name__ == '__main__': unittest.main()
