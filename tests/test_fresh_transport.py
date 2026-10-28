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
    def test_existing_watcher_helper_and_reader_share_one_repair_and_mutations_delegate_once(self):
        from fresh_transport import coordinate_reconnect
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{'WORKLOAD_LOCAL_API_PORT':'16444'}):
            state={'ready':False};barrier=threading.Barrier(2);call=Mock(side_effect=lambda *a,**k:state.update(ready=True) or 0)
            wrapped=coordinate_reconnect(call,folder,Path('/repo'))
            def watcher():barrier.wait();wrapped(['/repo/scripts/gcp-workload-api-tunnel.sh','ensure'],'watch.log',timeout=60)
            def reader():
                barrier.wait()
                with transport_lock(folder,lambda:60):
                    if not state['ready']:call('reader ensure')
            with patch('fresh_transport.listener_reachable',side_effect=lambda port:state['ready']):
                threads=[threading.Thread(target=watcher),threading.Thread(target=reader)]
                for t in threads:t.start()
                for t in threads:t.join(3)
                self.assertTrue(all(not t.is_alive() for t in threads));self.assertEqual(call.call_count,1)
            call.reset_mock();wrapped(['kubectl','delete','job','owned'],'mutation.log',timeout=5);self.assertEqual(call.call_count,1)

    def test_watcher_helper_keeps_original_cumulative_repair_deadline(self):
        from fresh_transport import coordinate_reconnect
        clock=Clock()
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{'WORKLOAD_LOCAL_API_PORT':'16444'}),patch('fresh_transport.listener_reachable',return_value=False):
            def late(*args,**kwargs):clock.sleep(61);return 0
            with self.assertRaisesRegex(TimeoutError,'deadline'):
                coordinate_reconnect(late,folder,'/repo',clock=clock)(['/repo/scripts/gcp-workload-api-tunnel.sh','ensure'],'watch.log',timeout=60)
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


class SSHReadTests(unittest.TestCase):
    def read(self, invoke, *, identity=None, timeout=30):
        from fresh_transport import retry_ssh_read
        clock=Clock();identity=identity or Mock()
        with tempfile.TemporaryDirectory() as folder:
            result=retry_ssh_read(invoke,timeout=timeout,identity=identity,label='progress',
                evidence=folder,clock=clock,sleep=clock.sleep)
            rows=[json.loads(x) for x in (Path(folder)/'ssh-read-attempts.jsonl').read_text().splitlines()]
        return result,rows,clock,identity

    def test_iap4047_retry_succeeds_only_after_same_target_identity(self):
        invoke=Mock(side_effect=[RuntimeError("IAP4047 Failed to lookup instance"),'actual raw bytes'])
        result,rows,clock,identity=self.read(invoke)
        self.assertEqual(result,'actual raw bytes');self.assertEqual(invoke.call_count,2)
        self.assertEqual(identity.call_count,2)
        self.assertEqual(clock.now,1)
        self.assertEqual(invoke.call_args.args[0],29)
        self.assertTrue(all(row['observation_filled'] is False for row in rows))
        self.assertNotIn('captured',rows[0])

    def test_continued_failure_is_bounded_to_three_attempts(self):
        invoke=Mock(side_effect=RuntimeError('SSH broken pipe'))
        with self.assertRaisesRegex(TimeoutError,'attempt limit'):
            self.read(invoke)
        self.assertEqual(invoke.call_count,3)

    def test_original_deadline_includes_identity_and_backoff(self):
        from fresh_transport import retry_ssh_read
        clock=Clock();calls=[]
        def invoke(left):calls.append(left);clock.sleep(2);raise RuntimeError('connection reset')
        def identity(remaining):clock.sleep(2);remaining()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(TimeoutError,'deadline'):
                retry_ssh_read(invoke,timeout=4,identity=identity,label='raw',evidence=folder,clock=clock,sleep=clock.sleep)
        self.assertEqual(calls,[4]);self.assertEqual(clock.now,4)

    def test_permanent_permission_configuration_and_missing_vm_errors_return_once(self):
        for error in ['Forbidden','Permission denied','Invalid argument project','Not found instance','certificate verification failed']:
            invoke=Mock(side_effect=RuntimeError(error));identity=Mock()
            with self.assertRaises(RuntimeError):self.read(invoke,identity=identity)
            self.assertEqual(invoke.call_count,1);identity.assert_not_called()

    def test_changed_vm_or_namespace_stops_before_read_retry(self):
        for error in ['VM identity/existence changed','namespace/run UID changed']:
            invoke=Mock(side_effect=RuntimeError('IAP4047 Failed to lookup instance'))
            identity=Mock(side_effect=RuntimeError(error))
            with self.assertRaisesRegex(RuntimeError,'changed'):self.read(invoke,identity=identity)
            self.assertEqual(invoke.call_count,1)

    def test_mutations_and_arbitrary_shells_never_enter_read_boundary(self):
        from fresh_transport import SSHReadBoundary
        runner=Mock();runner.record={'run_id':'owned'}
        reader=SSHReadBoundary(runner)
        for script in ['sudo touch /owned/stop','sudo reboot','kubectl delete pod x',
                'curl -fsS http://198.18.0.2:8090/progress; sudo reboot',
                'sudo cat /other/fresh-api.jsonl','sudo cat /var/lib/openstack-k8s-graduation/owned/fresh-api.jsonl; reboot']:
            with self.assertRaises(ValueError):reader.remote(script)
        runner.remote.assert_not_called()

    def test_bounded_remote_file_has_three_total_reads_not_nine_and_keeps_raw_bytes(self):
        from fresh_transport import retry_ssh_read
        from fresh_collection import remote_file
        from fresh_evidence import Evidence
        clock=Clock();invoke=Mock(side_effect=[RuntimeError('connection reset'),RuntimeError('broken pipe'),'original\nraw\n'])
        with tempfile.TemporaryDirectory() as folder:
            ev=Evidence(folder)
            def remote(script,timeout):
                return retry_ssh_read(invoke,timeout=timeout,identity=Mock(),label=script,evidence=folder,clock=clock,sleep=clock.sleep)
            self.assertEqual(remote_file(ev,remote,'/owned/raw','requests.jsonl',bounded=True),'original\nraw\n')
            self.assertEqual((Path(folder)/'requests.jsonl').read_bytes(),b'original\nraw\n')
            collection=[json.loads(l) for l in (Path(folder)/'collection-attempts.jsonl').read_text().splitlines()]
            self.assertEqual(len(collection),1)
        self.assertEqual(invoke.call_count,3)

    def test_lost_probe_stop_ack_reads_applied_state_without_repeating_mutation(self):
        from fresh_transport import stop_probe_once
        runner=Mock();runner.record={'run_id':'owned'};runner.client.remaining.side_effect=lambda limit:limit
        runner.remote.side_effect=RuntimeError('SSH broken pipe');runner.read_remote.return_value='stopped'
        stop_probe_once(runner,'/var/lib/openstack-k8s-graduation/owned/fresh-api.jsonl.stop')
        self.assertEqual(runner.remote.call_count,1)
        self.assertEqual(runner.read_remote.call_count,1)
        self.assertIn('test -e',runner.read_remote.call_args.args[0])

    def test_unconfirmed_stop_is_not_replayed_or_assumed_success(self):
        from fresh_transport import stop_probe_once
        runner=Mock();runner.record={'run_id':'owned'};runner.client.remaining.side_effect=lambda limit:limit
        runner.remote.side_effect=RuntimeError('SSH broken pipe');runner.read_remote.return_value=''
        with self.assertRaisesRegex(RuntimeError,'broken pipe'):
            stop_probe_once(runner,'/var/lib/openstack-k8s-graduation/owned/fresh-api.jsonl.stop')
        self.assertEqual(runner.remote.call_count,1)

    def test_openstack_read_boundary_does_not_accept_set_delete_or_foreign_port(self):
        from fresh_transport import SSHReadBoundary
        runner=Mock();runner.record={'workers':[{'port':{'id':'owned'}}],'policy_id':'policy','rule_id':'rule'}
        for args in [('port','set','owned'),('port','delete','owned'),('port','show','foreign'),('server','stop','owned')]:
            with self.assertRaises(ValueError):SSHReadBoundary(runner).admin_json(args)
        runner.admin_json.assert_not_called()

    def test_owned_source_domstate_reads_once_and_keeps_original_host(self):
        from fresh_transport import SSHReadBoundary
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{'CONTROLLER_NAME':'controller'}):
            runner=Mock();runner.ev.directory=Path(folder)
            runner.record={'run_id':'run','source':{'host':'compute','instance_name':'instance-0001'}}
            runner.client.remaining.side_effect=lambda limit:limit;runner.remote.return_value='SHUTOFF\n'
            self.assertEqual(SSHReadBoundary(runner).remote('sudo docker exec nova_libvirt virsh domstate instance-0001',host='compute'),'SHUTOFF\n')
            self.assertEqual(runner.remote.call_count,1)
            self.assertEqual(runner.remote.call_args.kwargs['host'],'compute')
            with self.assertRaises(ValueError):SSHReadBoundary(runner).remote('sudo docker exec nova_libvirt virsh domstate instance-0001',host='foreign')
            self.assertEqual(runner.remote.call_count,1)

    def test_gcp4047_identity_checks_expected_id_project_zone_and_run_uid(self):
        from fresh_transport import SSHReadBoundary
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            runner=SimpleNamespace(ev=SimpleNamespace(directory=Path(folder)),profile={'project':'project','zone':'zone'},
                record={'environment_run_id':'env','fresh_attempt':str(Path(folder).resolve()),'namespace_uid':'nsuid','run_id':'run'},
                client=SimpleNamespace(state=Path(folder),cluster='workload'),ns='graduation-s2',runtime=Mock())
            runner.runtime.environment.return_value={'run_id':'env','final_hosts':{'host':{'id':'123'}}}
            host={'name':'host','id':'123','status':'RUNNING','zone':'zones/zone'}
            ns={'metadata':{'uid':'nsuid','labels':{'openstack-k8s.dev/experiment':'run'}}}
            with patch.dict('os.environ',{'GCP_PROJECT_ID':'project','GCP_ZONE':'zone'}),patch('workload_state.command',side_effect=[json.dumps(host),json.dumps(ns)]) as command:
                SSHReadBoundary(runner).identity('host',lambda:10)
                self.assertIn('--project=project',command.call_args_list[0].args[0])
                self.assertIn('--zone=zone',command.call_args_list[0].args[0])
            host['id']='other'
            with patch.dict('os.environ',{'GCP_PROJECT_ID':'project','GCP_ZONE':'zone'}),patch('workload_state.command',return_value=json.dumps(host)) as command:
                with self.assertRaisesRegex(RuntimeError,'VM identity'):SSHReadBoundary(runner).identity('host',lambda:10)
                self.assertEqual(command.call_count,1)


if __name__ == '__main__': unittest.main()
