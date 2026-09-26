"""The shared environment gate must never rebuild or restart healthy hosts."""
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from graduation_env import Environment


def config(root, hosts=('controller', 'compute1', 'compute2')):
    return {'root': str(root), 'state_dir': str(root / '.state' / 'test'),
            'environment': 'test', 'project': 'project', 'zone': 'zone',
            'cluster': 'workload', 'namespace': 'ns', 'hosts': list(hosts)}


class FakeCommands:
    def __init__(self, status):
        self.status = dict(status)
        self.calls = []

    def run(self, args, timeout=60):
        args = [str(arg) for arg in args]
        self.calls.append(args)
        if args[:3] == ['gcloud', 'compute', 'instances']:
            if args[3] == 'describe':
                name = args[4]
                if name not in self.status:
                    raise RuntimeError('host missing')
                return json.dumps({'name': name, 'status': self.status[name],
                                   'id': 'id-' + name})
            if args[3] == 'start':
                self.status[args[4]] = 'RUNNING'
                return ''
            if args[3] == 'stop':
                self.status[args[4]] = 'TERMINATED'
                return ''
        return ''

    def starts(self):
        return [call[4] for call in self.calls
                if call[:4] == ['gcloud', 'compute', 'instances', 'start']]

    def stops(self):
        return [call[4] for call in self.calls
                if call[:4] == ['gcloud', 'compute', 'instances', 'stop']]


class FakeKubernetes:
    def __init__(self, worker_ready=True):
        self.worker_ready = worker_ready

    def run(self, args, timeout=60):
        args = [str(arg) for arg in args]
        ready = [{'type': 'Ready', 'status': 'True'}]
        not_ready = [{'type': 'Ready', 'status': 'False'}]
        node = lambda name, labels, conditions: {
            'metadata': {'name': name, 'labels': labels},
            'spec': {}, 'status': {'conditions': conditions},
        }
        if 'nodes' in args:
            if 'management.yaml' in args[2]:
                return json.dumps({'items': [node('management', {}, ready)]})
            return json.dumps({'items': [
                node('control-plane', {'node-role.kubernetes.io/control-plane': ''}, ready),
                node('worker', {}, ready if self.worker_ready else not_ready),
            ]})
        if 'machinedeployment' in args:
            return json.dumps({'metadata': {'uid': 'md'}, 'spec': {'replicas': 1},
                               'status': {'replicas': 1, 'readyReplicas': 1,
                                          'availableReplicas': 1}})
        if 'cluster' in args:
            return json.dumps({'metadata': {'uid': 'cluster'}})
        raise AssertionError(args)


class ReadyEnvironment(Environment):
    def check_local_inputs(self):
        pass

    def wait_cluster(self, seconds=900):
        return {'worker_desired': 2, 'cluster_uid': 'cluster', 'md_uid': 'md'}

    def cluster_ready(self):
        return self.wait_cluster()


class EnvironmentTests(unittest.TestCase):
    def test_missing_cluster_input_fails_before_starting_hosts(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = FakeCommands({'controller': 'TERMINATED', 'compute1': 'TERMINATED',
                                     'compute2': 'TERMINATED'})
            with self.assertRaisesRegex(RuntimeError, 'missing management kubeconfig'):
                Environment(config(Path(directory)), commands).ensure()
            self.assertEqual(commands.calls, [])

    def test_cluster_gate_requires_ready_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configs = root / '.state' / 'test' / 'kubeconfigs'
            configs.mkdir(parents=True)
            (configs / 'management.yaml').write_text('test')
            (configs / 'workload.yaml').write_text('test')
            self.assertIsNone(Environment(config(root), FakeKubernetes(False)).cluster_ready())
            ready = Environment(config(root), FakeKubernetes(True)).cluster_ready()
            self.assertEqual(ready['worker_desired'], 1)
            self.assertEqual(ready['cluster_uid'], 'cluster')

    def test_transient_kubectl_timeout_is_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            class TransientEnvironment(Environment):
                def __init__(self, *args):
                    super().__init__(*args)
                    self.attempts = 0

                def cluster_ready(self):
                    self.attempts += 1
                    if self.attempts == 1:
                        raise subprocess.TimeoutExpired(['kubectl', 'get', 'nodes'], 1)
                    return {'worker_desired': 2}

            environment = TransientEnvironment(config(Path(directory)), FakeCommands({}))
            from unittest.mock import patch
            with patch('graduation_env.time.sleep'):
                self.assertEqual(environment.wait_cluster(seconds=5), {'worker_desired': 2})
            self.assertEqual(environment.attempts, 2)

    def test_transient_guest_recovery_failure_is_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            class GuestCommands(FakeCommands):
                def __init__(self):
                    super().__init__({'controller': 'RUNNING', 'compute1': 'RUNNING',
                                      'compute2': 'RUNNING'})
                    self.guest_calls = 0

                def run(self, args, timeout=60):
                    if Path(args[0]).name == 'start-workload-guests.sh':
                        self.guest_calls += 1
                        if self.guest_calls == 1:
                            raise RuntimeError('workload guest did not remain ACTIVE')
                        return 'workload guest stably ACTIVE'
                    return super().run(args, timeout=timeout)

            commands = GuestCommands()
            environment = ReadyEnvironment(config(root), commands)
            data = {}
            from unittest.mock import patch
            with patch('graduation_env.time.sleep'):
                environment.start_current_guests(data)
            self.assertEqual(commands.guest_calls, 2)
            self.assertEqual(data['guest_attempt'], 1)
            self.assertEqual(data['guest_recovery'], ['workload guest stably ACTIVE'])

    def test_healthy_environment_is_verified_without_host_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = FakeCommands({'controller': 'RUNNING', 'compute1': 'RUNNING',
                                     'compute2': 'RUNNING'})
            result = ReadyEnvironment(config(root), commands).ensure()
            self.assertEqual(result['phase'], 'ready')
            self.assertEqual(result['started_hosts'], [])
            self.assertEqual(commands.starts(), [])
            self.assertFalse(any('lab-up' in ' '.join(call) for call in commands.calls))

    def test_only_stopped_host_is_started_and_owned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = FakeCommands({'controller': 'RUNNING', 'compute1': 'TERMINATED',
                                     'compute2': 'RUNNING'})
            result = ReadyEnvironment(config(root), commands).ensure()
            self.assertEqual(commands.starts(), ['compute1'])
            self.assertEqual(result['started_hosts'], ['compute1'])
            self.assertEqual(result['initial_hosts']['controller']['status'], 'RUNNING')
            self.assertEqual(result['final_hosts']['compute1']['status'], 'RUNNING')

    def test_second_ensure_preserves_original_host_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = FakeCommands({'controller': 'RUNNING', 'compute1': 'TERMINATED',
                                     'compute2': 'RUNNING'})
            environment = ReadyEnvironment(config(root), commands)
            first = environment.ensure()
            second = environment.ensure()
            self.assertEqual(first['run_id'], second['run_id'])
            self.assertEqual(second['started_hosts'], ['compute1'])
            self.assertEqual(commands.starts(), ['compute1'])
            self.assertEqual(sum(Path(call[0]).name == 'gcp-openstack-recover.sh'
                                 for call in commands.calls), 1)
            self.assertEqual(sum(Path(call[0]).name == 'start-workload-guests.sh'
                                 for call in commands.calls), 1)

    def test_unhealthy_ready_record_runs_recovery_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = FakeCommands({'controller': 'RUNNING', 'compute1': 'RUNNING',
                                     'compute2': 'RUNNING'})

            class UnhealthyOnce(ReadyEnvironment):
                def __init__(self, *args):
                    super().__init__(*args)
                    self.reads = 0

                def cluster_ready(self):
                    self.reads += 1
                    return None if self.reads == 1 else super().cluster_ready()

            environment = ReadyEnvironment(config(root), commands)
            first = environment.ensure()
            recovered = UnhealthyOnce(config(root), commands).ensure()
            self.assertEqual(first['run_id'], recovered['run_id'])
            self.assertEqual(sum(Path(call[0]).name == 'gcp-openstack-recover.sh'
                                 for call in commands.calls), 2)

    def test_ready_fast_path_rejects_cluster_identity_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = FakeCommands({'controller': 'RUNNING', 'compute1': 'RUNNING',
                                     'compute2': 'RUNNING'})
            environment = ReadyEnvironment(config(root), commands)
            environment.ensure()

            class ChangedCluster(ReadyEnvironment):
                def cluster_ready(self):
                    return {'worker_desired': 2, 'cluster_uid': 'replacement', 'md_uid': 'md'}

            before = len(commands.calls)
            with self.assertRaisesRegex(RuntimeError, 'cluster identity changed'):
                ChangedCluster(config(root), commands).ensure()
            self.assertEqual(len(commands.calls) - before, 3)  # exact host reads only

    def test_down_stops_only_hosts_started_by_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = FakeCommands({'controller': 'RUNNING', 'compute1': 'TERMINATED',
                                     'compute2': 'RUNNING'})
            environment = ReadyEnvironment(config(root), commands)
            environment.ensure()
            closed = environment.down()
            self.assertEqual(closed['phase'], 'stopped')
            self.assertEqual(commands.stops(), ['compute1'])
            self.assertEqual(commands.status['controller'], 'RUNNING')

    def test_down_refuses_active_s4_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = FakeCommands({'controller': 'TERMINATED', 'compute1': 'TERMINATED',
                                     'compute2': 'TERMINATED'})
            environment = ReadyEnvironment(config(root), commands)
            prepared = environment.ensure()
            (root / '.state' / 'test' / 's4-preparation.json').write_text(json.dumps(
                {'environment_run_id': prepared['run_id'], 'phase': 'prepared'}))
            with self.assertRaisesRegex(RuntimeError, 'S4 fixture'):
                environment.down()
            self.assertEqual(commands.stops(), [])

    def test_failed_start_record_cannot_be_silently_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / '.state' / 'test'
            state.mkdir(parents=True)
            (state / 'graduation-environment.json').write_text(
                '{"phase": "failed", "start_attempted": ["compute1"]}')
            commands = FakeCommands({'controller': 'RUNNING', 'compute1': 'RUNNING',
                                     'compute2': 'RUNNING'})
            with self.assertRaisesRegex(RuntimeError, 'reconcile ownership'):
                ReadyEnvironment(config(root), commands).ensure()
            self.assertEqual(commands.calls, [])

    def test_missing_host_never_invokes_bootstrap_or_start(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = FakeCommands({'controller': 'RUNNING'})
            with self.assertRaisesRegex(RuntimeError, 'host missing'):
                ReadyEnvironment(config(Path(directory)), commands).ensure()
            self.assertEqual(commands.starts(), [])

    def test_interrupted_ensure_requires_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / '.state' / 'test'
            state.mkdir(parents=True)
            (state / 'graduation-environment.json').write_text('{"phase": "starting"}')
            commands = FakeCommands({'controller': 'RUNNING', 'compute1': 'RUNNING',
                                     'compute2': 'RUNNING'})
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                ReadyEnvironment(config(root), commands).ensure()
            self.assertEqual(commands.calls, [])

    def test_reconcile_attempted_host_start_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = FakeCommands({'controller': 'RUNNING', 'compute1': 'TERMINATED',
                                     'compute2': 'RUNNING'})
            environment = ReadyEnvironment(config(root), commands)
            first = environment.ensure()
            record_path = root / '.state' / 'test' / 'graduation-environment.json'
            interrupted = json.loads(record_path.read_text())
            interrupted['phase'] = 'starting'
            interrupted['started_hosts'] = []
            record_path.write_text(json.dumps(interrupted))
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                environment.ensure()
            reconciled = environment.reconcile()
            self.assertEqual(reconciled['started_hosts'], ['compute1'])
            resumed = environment.ensure()
            self.assertEqual(resumed['run_id'], first['run_id'])
            self.assertEqual(commands.starts(), ['compute1'])


if __name__ == '__main__':
    unittest.main()
