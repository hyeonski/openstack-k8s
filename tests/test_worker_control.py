"""Offline tests for durable worker ownership and interrupted transitions."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from worker_control import WorkerControl
from autoscaler_cycle import main, prepare_transport


class FakeClient:
    cluster = 'workload'
    ns = 'default'

    def __init__(self, state):
        self.state = state
        self.cluster_obj = {'metadata': {'uid': 'cluster-a'}}
        self.md = {'metadata': {'uid': 'md-a', 'generation': 1}, 'spec': {'replicas': 2},
                   'status': {'observedGeneration': 1, 'replicas': 2, 'readyReplicas': 2, 'availableReplicas': 2}}
        self.ca = {'metadata': {'uid': 'ca-a'}, 'spec': {'replicas': 1},
                   'status': {'replicas': 1, 'availableReplicas': 1}}
        self.calls = []

    def get(self, plane, resource, *args):
        if resource == 'cluster':
            return copy.deepcopy(self.cluster_obj)
        if resource == 'machinedeployment':
            return copy.deepcopy(self.md)
        if resource == 'deployment':
            return copy.deepcopy(self.ca)
        if resource == 'pods':
            return {'items': []}
        raise AssertionError(resource)

    def k(self, plane, *args):
        self.calls.append(args)
        if args[0] == 'scale':
            target = int(args[-1].split('=')[1])
            self.ca['spec']['replicas'] = target
            self.ca['status'] = {'replicas': target, 'availableReplicas': target}
        return ''


class WorkerControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = FakeClient(Path(self.tmp.name))
        self.env = patch.dict(os.environ, {'CLUSTER_AUTOSCALER_NAMESPACE': 'ca-system'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_mode_switch_and_manual_scale_preserve_fixed_mode(self):
        with patch('test_resources.residues', return_value=[]), WorkerControl(self.client) as control:
            control.switch_mode('fixed')
            self.assertEqual(control.read(control.state_path)['mode'], 'fixed')
            self.assertEqual(self.client.ca['spec']['replicas'], 0)
            control.begin_manual('3')
            self.client.md['spec']['replicas'] = 3
            self.client.md['status'].update(replicas=3, readyReplicas=3, availableReplicas=3)
            control.finish_manual()
            self.assertIsNone(control.read(control.journal_path))
            control.switch_mode('auto')
            self.assertEqual(control.read(control.state_path)['mode'], 'auto')
            self.assertEqual(self.client.ca['spec']['replicas'], 1)

    def test_interrupted_manual_restores_original_ca_only_after_md_settles(self):
        with WorkerControl(self.client) as control:
            control.begin_manual('3')
            self.client.ca['spec']['replicas'] = 0
            self.client.ca['status'] = {'replicas': 0, 'availableReplicas': 0}
            self.client.md['spec']['replicas'] = 3
            with self.assertRaisesRegex(RuntimeError, 'not stable'):
                control.recover()
            self.assertEqual(self.client.ca['spec']['replicas'], 0)
            self.assertIsNotNone(control.read(control.journal_path))
            self.client.md['status'].update(replicas=3, readyReplicas=3, availableReplicas=3)
            control.recover()
            self.assertEqual(self.client.ca['spec']['replicas'], 1)
            self.assertIsNone(control.read(control.journal_path))

    def test_success_restores_auto_only_after_target_convergence(self):
        with WorkerControl(self.client) as control:
            control.begin_manual('3')
            self.client.ca['spec']['replicas'] = 0
            self.client.ca['status'] = {'replicas': 0, 'availableReplicas': 0}
            self.client.md['spec']['replicas'] = 3
            with self.assertRaisesRegex(RuntimeError, 'not converged'):
                control.finish_manual()
            self.assertEqual(self.client.ca['spec']['replicas'], 0)
            self.assertIsNotNone(control.read(control.journal_path))
            self.client.md['status'].update(replicas=3, readyReplicas=3, availableReplicas=3)
            control.finish_manual()
            self.assertEqual(self.client.ca['spec']['replicas'], 1)
            self.assertIsNone(control.read(control.journal_path))

    def test_interrupted_mode_change_finishes_from_live_state(self):
        with WorkerControl(self.client) as control:
            mode, observed = control.preflight()
            self.assertEqual(mode, 'auto')
            control.write(control.journal_path, {'kind': 'mode', 'identity': control.identity(observed),
                                                 'from_mode': 'auto', 'target_mode': 'fixed'})
            self.client.ca['spec']['replicas'] = 0
            self.client.ca['status'] = {'replicas': 0, 'availableReplicas': 0}
            control.recover()
            self.assertEqual(control.read(control.state_path)['mode'], 'fixed')
            self.assertIsNone(control.read(control.journal_path))

    def test_committed_mode_with_leftover_journal_is_idempotent(self):
        with WorkerControl(self.client) as control:
            _, observed = control.preflight()
            control.write(control.journal_path, {'kind': 'mode', 'identity': control.identity(observed),
                                                 'from_mode': 'auto', 'target_mode': 'fixed'})
            self.client.ca['spec']['replicas'] = 0
            self.client.ca['status'] = {'replicas': 0, 'availableReplicas': 0}
            control.record_mode('fixed', control.observe())
            control.recover()
            self.assertEqual(control.read(control.state_path)['mode'], 'fixed')
            self.assertIsNone(control.read(control.journal_path))

    def test_external_change_and_cluster_replacement_fail_closed(self):
        with WorkerControl(self.client) as control:
            control.preflight()
            self.client.ca['spec']['replicas'] = 0
            self.client.ca['status'] = {'replicas': 0, 'availableReplicas': 0}
            with self.assertRaisesRegex(RuntimeError, 'auto mode requires'):
                control.preflight()
            self.client.ca['spec']['replicas'] = 1
            self.client.ca['status'] = {'replicas': 1, 'availableReplicas': 1}
            self.client.md['metadata']['uid'] = 'different'
            with self.assertRaisesRegex(RuntimeError, 'different cluster'):
                control.preflight()

    def test_second_local_operator_cannot_acquire_lock(self):
        with WorkerControl(self.client):
            with self.assertRaises(BlockingIOError):
                with WorkerControl(self.client):
                    pass

    def test_child_keeps_lock_after_parent_releases_it(self):
        with WorkerControl(self.client) as control:
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(1)'],
                                     pass_fds=(control.lock.fileno(),))
        try:
            with self.assertRaises(BlockingIOError):
                with WorkerControl(self.client):
                    pass
        finally:
            child.wait(timeout=3)
        with WorkerControl(self.client):
            pass

    def test_mode_change_keeps_journal_if_worker_moves_during_ca_stop(self):
        original = self.client.k
        def racing_scale(plane, *args):
            result = original(plane, *args)
            if args[0] == 'scale':
                self.client.md['spec']['replicas'] = 3
            return result
        self.client.k = racing_scale
        with patch('test_resources.residues', return_value=[]), WorkerControl(self.client) as control:
            with self.assertRaisesRegex(RuntimeError, 'changed during mode transition'):
                control.switch_mode('fixed')
            self.assertEqual(control.read(control.state_path)['mode'], 'auto')
            self.assertIsNotNone(control.read(control.journal_path))
            self.client.md['status'].update(replicas=3, readyReplicas=3, availableReplicas=3)
            control.recover()
            self.assertEqual(control.read(control.state_path)['mode'], 'fixed')

    def test_install_can_repair_auto_but_cannot_start_fixed_mode(self):
        with WorkerControl(self.client) as control:
            control.preflight()
            self.client.ca['status']['availableReplicas'] = 0
            control.preflight_install(True)
            self.client.ca['status']['availableReplicas'] = 1
            with patch('test_resources.residues', return_value=[]):
                control.switch_mode('fixed')
            with self.assertRaisesRegex(RuntimeError, 'override fixed'):
                control.preflight_install(True)

    def test_transport_is_ready_before_worker_control_reads(self):
        with patch('autoscaler_cycle.subprocess.run') as run:
            prepare_transport('manual')
            self.assertEqual([call.args[0][1] for call in run.call_args_list], ['tunnel', 'ensure'])
            run.reset_mock()
            prepare_transport('recover')
            self.assertEqual([call.args[0][1] for call in run.call_args_list], ['tunnel'])

    def test_transport_preparation_holds_worker_lock(self):
        events = []
        with patch('autoscaler_cycle.Client'), patch('autoscaler_cycle.WorkerControl') as worker_control, \
                patch('autoscaler_cycle.prepare_transport', side_effect=lambda _: events.append('transport')), \
                patch('run_lifecycle.RunLifecycle'), \
                patch('autoscaler_cycle.sys.argv', ['autoscaler_cycle.py', 'recover']), \
                patch('signal.signal'), patch('builtins.print'):
            control = worker_control.return_value
            control.__enter__.side_effect = lambda: events.append('lock') or control
            control.recover.side_effect = lambda: events.append('recover')
            main()
        self.assertEqual(events, ['lock', 'transport', 'recover'])


if __name__ == '__main__':
    unittest.main()
