"""Durable lifecycle regressions: process loss, scoped cleanup, budget and retry."""
import json
import os
import signal
import subprocess
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_lifecycle as lifecycle
import test_resources as resources
from worker_control import WorkerControl
from workload_state import Client
import workload_state
from test_worker_control import FakeClient
from test_workload_lifecycle import ENV, fixture


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {**ENV, 'RUN_ID': '', 'CONTROLLER_NAME': 'controller',
                                          'COMPUTE_NODE_NAMES': 'compute1 compute2',
                                          'GCP_PROJECT_ID': 'project', 'GCP_ZONE': 'zone'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.root_patch = patch.object(lifecycle, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.client = FakeClient(self.root / 'state')
        self.client.deadline = None
        self.client.run_check = None
        self.control = WorkerControl(self.client)
        self.path = self.root / 'artifacts' / ENV['ENVIRONMENT_NAME'] / 'autoscaler-run-test'
        self.path.mkdir(parents=True)
        self.manager = lifecycle.RunLifecycle(self.client, self.control)
        self.manager.path = self.path
        self.manager.record = {'version': 1, 'run_id': self.path.name, 'owner_id': 'owner', 'attempt': 1,
                               'identity': self.control.identity(self.control.observe()),
                               'deadline_epoch': time.time() + 3600}
        self.manager.update('running')
        self.control.write(self.client.state / 'experiment-run.json',
                           {'run_id': self.path.name, 'path': str(self.path)})

    def test_process_loss_keeps_run_and_blocks_duplicate(self):
        fresh = lifecycle.RunLifecycle(self.client, self.control)
        with self.assertRaisesRegex(RuntimeError, 'unfinished experiment'):
            fresh.require_idle()
        self.assertEqual(fresh.record['state'], 'running')

    def test_sigterm_escapes_subprocess_wait_without_eintr_retry(self):
        script = '''
import sys
from run_lifecycle import Cancelled, install_signal_handlers
from workload_state import command
install_signal_handlers()
print('ready', flush=True)
try:
    command([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=20)
except Cancelled:
    print('cancelled', flush=True)
else:
    raise SystemExit('signal was swallowed')
'''
        env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'scripts')}
        with subprocess.Popen([sys.executable, '-c', script], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
            self.assertEqual(proc.stdout.readline().strip(), 'ready')
            time.sleep(0.2)
            proc.send_signal(signal.SIGTERM)
            try:
                stdout, stderr = proc.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                self.fail('SIGTERM was swallowed during subprocess wait')
            self.assertEqual(proc.returncode, 0, stderr)
            self.assertIn('cancelled', stdout)

    def test_cancel_requires_exact_id_and_survives_state_updates(self):
        with self.assertRaisesRegex(RuntimeError, 'RUN_ID'):
            lifecycle.local_action(self.client, 'test-cancel', 'wrong')
        lifecycle.local_action(self.client, 'test-cancel', self.path.name)
        self.manager.update('running')
        with self.assertRaises(lifecycle.Cancelled):
            self.manager.check()
        self.assertEqual((self.path / 'cancel.json').stat().st_mode & 0o777, 0o600)

    def test_deadline_persists_across_restart(self):
        self.manager.record['deadline_epoch'] = time.time() - 1
        self.manager.update('interrupted')
        fresh = lifecycle.RunLifecycle(self.client, self.control)
        with self.assertRaisesRegex(TimeoutError, 'whole experiment deadline'):
            fresh.check()

    def test_expired_resume_does_not_delete(self):
        self.manager.record['deadline_epoch'] = time.time() - 1
        with patch.dict(os.environ, {'RUN_ID': self.path.name}), patch.object(self.manager, 'identity'), \
                patch.object(self.manager, 'clean') as clean:
            with self.assertRaisesRegex(TimeoutError, 'deadline expired'):
                self.manager.execute('test-resume')
            clean.assert_not_called()

    def test_cleanup_failure_remains_active_and_is_retryable(self):
        with patch.object(lifecycle, 'host_budget', return_value=(time.time() + 7200, {})), \
                patch.object(self.manager, 'inspect', side_effect=RuntimeError('API unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'API unavailable'):
                self.manager.clean()
        record = lifecycle.RunLifecycle(self.client, self.control).record
        self.assertEqual(record['state'], 'cleanup_failed')
        self.assertIsNone(self.client.run_check)
        self.assertIn('API unavailable', record['reason'])

    def test_reconcile_refuses_foreign_run_and_replacement(self):
        pod = {'kind': 'Pod', 'metadata': {'name': 'infra-probe-x', 'namespace': 'default',
                                         'uid': 'new', 'labels': {resources.RUN: 'different'}}}
        self.client.snapshot = lambda _: fixture()
        with patch.object(self.manager, 'identity', return_value={}), \
                patch.object(lifecycle, 'residues', return_value=[('w', pod)]):
            with self.assertRaisesRegex(RuntimeError, 'other experiment'):
                self.manager.inspect(self.path / 'inspect')
            pod['metadata']['labels'][resources.RUN] = 'owner'
            original = json.loads(json.dumps(pod))
            original['metadata']['uid'] = 'original'
            destination = self.path / 'autoscaler-cycle-attempt-001' / 'api-created.json'
            self.control.write(destination, original)
            with self.assertRaisesRegex(RuntimeError, 'UID changed'):
                self.manager.inspect(self.path / 'inspect-2')

    def test_cleanup_deletes_only_selected_run(self):
        own = {'kind': 'Pod', 'metadata': {'name': 'own', 'namespace': 'default', 'uid': 'own',
                                         'labels': {resources.RUN: 'owner'}}}
        foreign = {'kind': 'Pod', 'metadata': {'name': 'foreign', 'uid': 'foreign',
                                             'labels': {resources.RUN: 'other'}}}
        with patch.object(resources, 'residues', side_effect=[[('w', own), ('w', foreign)], [('w', foreign)]]), \
                patch.object(resources, 'save'), patch.object(self.client, 'get', return_value={}), \
                patch.object(resources, 'delete_owned') as delete:
            resources.cleanup(self.client, self.path, 'owner')
            delete.assert_called_once_with(self.client, 'w', own)

    def test_latest_attempt_uid_wins_independent_of_directory_listing_order(self):
        pod = {'kind': 'Pod', 'metadata': {'name': 'infra-probe-x', 'namespace': 'default',
                                         'uid': 'latest', 'labels': {resources.RUN: 'owner'}}}
        old = self.path / 'autoscaler-cycle-attempt-001/api-created.json'
        new = self.path / 'autoscaler-cycle-attempt-002/api-created.json'
        original = json.loads(json.dumps(pod))
        original['metadata']['uid'] = 'old'
        self.control.write(old, original)
        self.control.write(new, pod)
        self.client.snapshot = lambda _: fixture()
        with patch.object(self.manager, 'identity', return_value={}), \
                patch.object(lifecycle, 'residues', return_value=[('w', pod)]), \
                patch.object(Path, 'glob', return_value=[new, old]):
            self.manager.inspect(self.path / 'inspect')

    def test_host_budget_uses_earliest_stop_and_fails_closed(self):
        rows = [{'name': name, 'status': 'RUNNING', 'lastStartTimestamp': '2026-09-24T00:00:00Z',
                 'scheduling': {'maxRunDuration': {'seconds': seconds}}}
                for name, seconds in [('controller', 36000), ('compute1', 35000), ('compute2', 36000)]]
        with patch.object(lifecycle, 'command', return_value=json.dumps(rows)):
            deadline, _ = lifecycle.host_budget(self.client)
            self.assertEqual(deadline, 1790208000 + 35000)
        rows[-1]['status'] = 'TERMINATED'
        with patch.object(lifecycle, 'command', return_value=json.dumps(rows)):
            with self.assertRaisesRegex(RuntimeError, 'stopped'):
                lifecycle.host_budget(self.client)

    def test_client_command_budget_includes_whole_run(self):
        client = Client()
        client.run_check = lambda: 2
        self.assertEqual(client.remaining(30), 2)

    def test_evidence_write_failure_preserves_previous_complete_json(self):
        destination = self.path / 'evidence.json'
        workload_state.save(destination, {'version': 'original'})
        with patch.object(workload_state.os, 'replace', side_effect=OSError('disk error')):
            with self.assertRaisesRegex(OSError, 'disk error'):
                workload_state.save(destination, {'version': 'replacement'})
        self.assertEqual(json.loads(destination.read_text()), {'version': 'original'})
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.path.glob('.evidence.json.*')), [])

    def test_cleanup_of_partially_created_worker_and_orphan_port(self):
        before = fixture(2)
        before['machines']['items'][-1]['spec']['providerID'] = None
        before['machines']['items'][-1]['status'].pop('nodeRef')
        after = fixture(1)
        removed = lifecycle.cleanup_integrity(fixture(1), before, after)
        self.assertEqual(len(removed), 1)
        after['nova']['ports'].append({'id': 'leaked-new-port', 'device_id': ''})
        with self.assertRaisesRegex(RuntimeError, 'unaccounted ports'):
            lifecycle.cleanup_integrity(fixture(1), before, after)

    def test_resume_cleans_then_creates_distinct_attempt(self):
        old = self.path / 'autoscaler-cycle-attempt-001'
        old.mkdir()
        (old / 'result.json').write_text('{"state":"cancelled"}')
        events = []
        def clean():
            events.append('clean')
            self.manager.update('cleaned')
        def run(client, path, owner_id):
            events.append('run')
            self.assertEqual(owner_id, 'owner')
            self.assertEqual(path.name, 'autoscaler-cycle-attempt-002')
        with patch.dict(os.environ, {'RUN_ID': self.path.name}), patch.object(self.manager, 'identity'), \
                patch.object(self.manager, 'clean', side_effect=clean), \
                patch.object(self.manager, 'inspect', return_value=(fixture(), {})), \
                patch.object(lifecycle, 'command', return_value='ok'), patch('autoscaler_cycle.run', side_effect=run):
            self.manager.execute('test-resume')
        self.assertEqual(events, ['clean', 'run'])
        self.assertEqual(self.manager.record['state'], 'passed')
        self.assertEqual(json.loads((old / 'result.json').read_text())['state'], 'cancelled')


if __name__ == '__main__':
    unittest.main()
