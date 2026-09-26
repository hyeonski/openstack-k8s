"""S4 preflight must identify only healthy workers and the actual HTTP host."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from graduation_s4 import archive_restored_record, target_identity, worker_machines


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


if __name__ == '__main__':
    unittest.main()
