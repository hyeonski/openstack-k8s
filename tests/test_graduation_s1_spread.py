import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from graduation_s1_spread import eligible, validate_server


class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.binding = {'machine_uid': 'uid', 'node': 'worker', 'nova_id': 'vm', 'host': 'compute01'}
        self.preparation = {'created': '2026-10-02T10:00:00+00:00'}
        self.machine = {'metadata': {'uid': 'uid', 'creationTimestamp': '2026-10-02T10:01:00Z'}}

    def test_preexisting_worker_cannot_be_migrated(self):
        self.machine['metadata']['creationTimestamp'] = '2026-10-02T09:00:00Z'
        self.assertFalse(eligible(self.binding, self.machine, [], self.preparation))

    def test_new_worker_may_have_only_node_agents(self):
        pod = {'metadata': {'ownerReferences': [{'kind': 'DaemonSet'}]}, 'spec': {'nodeName': 'worker'}}
        self.assertTrue(eligible(self.binding, self.machine, [pod], self.preparation))
        pod['metadata']['ownerReferences'][0]['kind'] = 'ReplicaSet'
        self.assertFalse(eligible(self.binding, self.machine, [pod], self.preparation))
        self.machine['metadata']['uid'] = 'different'
        self.assertFalse(eligible(self.binding, self.machine, [], self.preparation))

    def test_volume_or_inflight_migration_blocks_preparation(self):
        server = {'id': 'vm', 'status': 'ACTIVE', 'OS-EXT-STS:task_state': None,
                  'OS-EXT-SRV-ATTR:host': 'compute01', 'volumes_attached': []}
        validate_server(server, self.binding)
        for change in [{'volumes_attached': [{'id': 'volume'}]}, {'OS-EXT-STS:task_state': 'migrating'},
                       {'OS-EXT-SRV-ATTR:host': 'compute02'}, {'id': 'other'}]:
            with self.assertRaises(RuntimeError):
                validate_server({**server, **change}, self.binding)


if __name__ == '__main__':
    unittest.main()
