"""S4 preflight must identify only healthy workers and the actual HTTP host."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from graduation_env import atomic_json
from graduation_s4 import S4Preparation, archive_restored_record, target_identity, worker_machines


def machine(name, node, provider, deployment='workload-md-0', ready=True):
    return {
        'metadata': {'name': name, 'uid': 'uid-' + name,
                     'labels': {'cluster.x-k8s.io/cluster-name': 'workload',
                                'cluster.x-k8s.io/deployment-name': deployment},
                     'ownerReferences': [{'kind': 'MachineSet'}]},
        'spec': {'providerID': provider},
        'status': {'nodeRef': {'name': node},
                   'conditions': [{'type': 'Ready', 'status': 'True' if ready else 'False'}]},
    }


class S4IdentityTests(unittest.TestCase):
    def setUp(self):
        self.workers = [machine('worker-a', 'node-a', 'openstack:///nova-a'),
                        machine('worker-b', 'node-b', 'openstack:///nova-b')]

    def test_only_two_healthy_machineset_workers_are_selected(self):
        control_plane = machine('cp', 'cp-node', 'openstack:///nova-cp', 'control-plane')
        result = worker_machines([*self.workers, control_plane], 'workload', 'workload-md-0')
        self.assertEqual([item['metadata']['name'] for item in result], ['worker-a', 'worker-b'])

    def test_unhealthy_or_missing_worker_refuses_prepare(self):
        self.workers[1]['status']['conditions'][0]['status'] = 'False'
        with self.assertRaisesRegex(RuntimeError, 'exactly two healthy'):
            worker_machines(self.workers, 'workload', 'workload-md-0')

    def test_pod_node_maps_to_exact_nova_id(self):
        pod = {'metadata': {'name': 'http-1', 'uid': 'pod-uid'},
               'spec': {'nodeName': 'node-b'},
               'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}
        result = target_identity([pod], self.workers)
        self.assertEqual(result['machine_uid'], 'uid-worker-b')
        self.assertEqual(result['nova_id'], 'nova-b')

    def test_unknown_pod_node_refuses_fault_target(self):
        pod = {'metadata': {'name': 'http-1', 'uid': 'pod-uid'},
               'spec': {'nodeName': 'node-unknown'},
               'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}
        with self.assertRaisesRegex(RuntimeError, 'does not map'):
            target_identity([pod], self.workers)

    def test_restored_preparation_is_archived_before_next_run(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            old = {'phase': 'restored', 'environment_run_id': 'env-old',
                   'created': '2026-09-26T01:00:00+00:00'}
            self.assertIsNone(archive_restored_record(state_dir, old))
            archives = list((state_dir / 'graduation-s4-history').glob('*.json'))
            self.assertEqual(len(archives), 1)
            self.assertIn('env-old', archives[0].name)


class S4PartialCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name)
        self.preparation = S4Preparation(SimpleNamespace(state=self.state, cluster='workload', ns='ns'))
        self.worker = {'mode': 'fixed', 'workers': 2}
        self.commands = []
        self.objects = {
            ('m', 'machinehealthcheck', 'graduation-s4-worker'): self.resource('mhc'),
            ('w', 'namespace', 'graduation-s4'): self.resource('namespace'),
            ('w', 'configmap', 'http-content'): self.resource('configmap'),
            ('w', 'deployment', 'http'): self.resource('deployment'),
        }
        atomic_json(self.preparation.record_path, {
            'version': 1, 'phase': 'failed', 'environment_run_id': 'env-1',
            'cluster_uid': 'cluster', 'md_uid': 'md', 'original_mode': 'auto',
            'original_workers': 1, 'mhc_apply_intent': True, 'app_apply_intent': True,
        })
        self.preparation.environment_record = lambda: {'run_id': 'env-1'}
        self.preparation.preflight = lambda: (self.worker['mode'], {
            'cluster_uid': 'cluster', 'md_uid': 'md', 'workers': self.worker['workers']})
        self.preparation.object = lambda plane, kind, name, namespace=None: self.objects.get((plane, kind, name))
        self.preparation.k = self.kubectl

    @staticmethod
    def resource(name):
        return {'kind': name.title(), 'metadata': {'name': name, 'uid': 'uid-' + name,
                'labels': {'openstack-k8s.dev/experiment': 'graduation-s4'}}}

    def kubectl(self, plane, *args, **_kwargs):
        self.commands.append((plane, args))
        if args[0] == 'get':
            return json.dumps({'items': [item for (p, kind, _), item in self.objects.items()
                                         if p == 'w' and kind != 'namespace']})
        return ''

    def worker_command(self, args, timeout):
        self.commands.append(('worker', tuple(str(arg) for arg in args)))
        if str(args[0]).endswith('workload-cluster.sh'):
            self.worker['workers'] = 1
        else:
            self.worker['mode'] = 'auto'
        return ''

    def test_failed_partial_apply_removes_owned_resources_and_restores_workers(self):
        with patch('graduation_s4.command', side_effect=self.worker_command),\
                patch('graduation_s4.WorkerControl.stable_workers', return_value=True):
            result = self.preparation.cleanup()
        self.assertEqual(result['phase'], 'restored')
        self.assertEqual((self.worker['mode'], self.worker['workers']), ('auto', 1))
        self.assertIn(('m', ('delete', 'machinehealthcheck', 'graduation-s4-worker', '-n', 'ns',
                                   '--wait=true', '--timeout=3m')), self.commands)
        self.assertTrue(any(call[0] == 'w' and call[1][:2] == ('delete', '-f') for call in self.commands))

    def test_replaced_resource_refuses_partial_cleanup_before_deletion(self):
        record = json.loads(self.preparation.record_path.read_text())
        record['resource_uids'] = {'deployment': 'uid-from-original-run'}
        atomic_json(self.preparation.record_path, record)
        with self.assertRaisesRegex(RuntimeError, 'deployment/http ownership/UID changed'):
            self.preparation.cleanup()
        self.assertFalse(any(call[1][0] == 'delete' for call in self.commands))
        self.assertEqual(json.loads(self.preparation.record_path.read_text())['phase'], 'cleanup-failed')


if __name__ == '__main__':
    unittest.main()
