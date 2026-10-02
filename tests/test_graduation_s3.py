import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from graduation_s3 import S3, require_fenced, volume_matches


class S3SafetyTests(unittest.TestCase):
    def test_cleanup_waits_for_machine_deployment_after_node_recovery(self):
        runner = S3.__new__(S3)
        runner.client = Mock()
        runner.record = {'md_uid': 'md', 'original_mode': 'auto', 'original_workers': 1}
        runner.s1 = Mock()
        runner.s1.worker.return_value = ('auto', {'workers': 1})
        with patch('graduation_recovery.WorkerControl') as control_class, \
                patch('graduation_recovery.command') as command, \
                patch('graduation_recovery.time.sleep') as sleep:
            control = control_class.return_value.__enter__.return_value
            control.preflight.return_value = ('fixed', {'md_uid': 'md', 'workers': 2})
            control.stable_workers.side_effect = [False, True]
            runner.restore_workers()
            sleep.assert_called_once_with(5)
            self.assertEqual(command.call_count, 2)
            self.assertEqual(command.call_args_list[0].args[0][-2:], ['scale', '1'])
            self.assertEqual(command.call_args_list[1].args[0][-2:], ['mode', 'auto'])

    def test_database_fixture_keeps_data_and_wal_on_cinder(self):
        runner = S3.__new__(S3)
        runner.ns = 'graduation-s3'
        runner.apply = Mock()
        with patch('graduation_s3.wait_for', side_effect=RuntimeError('stop before cloud reads')):
            with self.assertRaisesRegex(RuntimeError, 'stop before cloud reads'):
                runner.build_database([{'node': 'worker-a'}, {'node': 'worker-b'}], {'node': 'control-plane'})
        stateful = next(call.args[0] for call in runner.apply.call_args_list if call.args[0]['kind'] == 'StatefulSet')
        claim = stateful['spec']['volumeClaimTemplates'][0]
        self.assertEqual(claim['spec']['storageClassName'], 'graduation-cinder')
        self.assertEqual(claim['spec']['accessModes'], ['ReadWriteOnce'])
        pod = stateful['spec']['template']['spec']
        container = pod['containers'][0]
        self.assertIn({'name': 'PGDATA', 'value': '/var/lib/postgresql/data/pgdata'}, container['env'])
        self.assertEqual(container['volumeMounts'][0], {'name': 'data', 'mountPath': '/var/lib/postgresql/data'})
        self.assertFalse(any(t['key'] == 'node.kubernetes.io/out-of-service' for t in pod['tolerations']))

    def test_nova_request_acceptance_is_not_fencing(self):
        stopped = {'id': 'vm', 'status': 'SHUTOFF', 'OS-EXT-STS:task_state': None, 'OS-EXT-STS:power_state': 4}
        require_fenced(stopped, 'vm', 'shut off\n')
        for change, hypervisor in [({'status': 'ACTIVE'}, 'running'),
                                   ({'OS-EXT-STS:task_state': 'powering-off'}, 'shut off'),
                                   ({'OS-EXT-STS:power_state': 1}, 'shut off'),
                                   ({'id': 'other'}, 'shut off'), ({}, 'running')]:
            with self.subTest(change=change):
                with self.assertRaises(RuntimeError):
                    require_fenced({**stopped, **change}, 'vm', hypervisor)

    def test_no_kubernetes_mutation_when_fencing_unconfirmed(self):
        runner = S3.__new__(S3)
        runner.record = {'source': {'nova_id': 'vm', 'instance_name': 'instance', 'host': 'compute'}}
        runner.admin_json = Mock(return_value={'id': 'vm', 'status': 'ACTIVE', 'OS-EXT-SRV-ATTR:host': 'compute'})
        runner.remote = Mock(return_value='running')
        runner.k = Mock()
        runner.write = Mock()
        runner.obj = Mock()
        with self.assertRaises(RuntimeError):
            runner.mark_out_of_service()
        runner.k.assert_not_called()
        runner.obj.assert_not_called()
        runner.write.assert_not_called()

    def test_volume_chain_and_attachment_must_be_exact(self):
        pvc = {'metadata': {'uid': 'claim'}, 'spec': {'volumeName': 'pv'}}
        pv = {'metadata': {'name': 'pv'}, 'spec': {'claimRef': {'uid': 'claim'},
              'csi': {'driver': 'cinder.csi.openstack.org', 'volumeHandle': 'volume'}}}
        volume = {'id': 'volume', 'attachments': [{'server_id': 'vm'}]}
        volume_matches(pvc, pv, volume, 'claim', 'vm')
        for value in ({**volume, 'id': 'wrong'}, {**volume, 'attachments': []},
                      {**volume, 'attachments': [{'server_id': 'other'}]},
                      {**volume, 'attachments': [{'server_id': 'vm'}, {'server_id': 'other'}]}):
            with self.assertRaises(RuntimeError):
                volume_matches(pvc, pv, value, 'claim', 'vm')
        with self.assertRaises(RuntimeError):
            volume_matches(pvc, pv, volume, 'different-claim', 'vm')


if __name__ == '__main__':
    unittest.main()
