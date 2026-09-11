"""Offline behavior tests: no credentials, GCP, Kubernetes or OpenStack needed."""
from __future__ import annotations
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
import workload_state as state
import test_resources as resources

ENV = {'ENVIRONMENT_NAME': 'cloud-gcp-amd64', 'WORKLOAD_CLUSTER_NAME': 'test', 'WORKLOAD_NAMESPACE': 'default',
       'WORKLOAD_CALICO_PROBE_TIMEOUT_SECONDS': '120', 'WORKLOAD_CALICO_STARTUP_FAILURE_THRESHOLD': '180',
       'KUBERNETES_VERSION': 'v1.35.7', 'WORKLOAD_KUBERNETES_ARCHITECTURE': 'amd64',
       'CLUSTER_AUTOSCALER_TEST_IMAGE': 'busybox:1.37.0', 'CLUSTER_AUTOSCALER_TEST_NAMESPACE': 'default',
       'CLUSTER_AUTOSCALER_NAMESPACE': 'cluster-autoscaler-system', 'CLUSTER_AUTOSCALER_WORKLOAD_NAMESPACE': 'kube-system',
       'CLUSTER_AUTOSCALER_STAGE_TIMEOUT_SECONDS': '100', 'CLUSTER_AUTOSCALER_STABLE_SECONDS': '1',
       'CLUSTER_AUTOSCALER_TEST_NAME': 'm3-cpu-scale-up', 'CLUSTER_AUTOSCALER_TARGETED_PROBE_NAME': 'm3-new-worker-cni-dns'}


def ready(kind='Ready'):
    return {'type': kind, 'status': 'True'}


def fixture(workers=1):
    s = {'errors': {}, 'cluster': {'kind': 'Cluster', 'status': {'conditions': [ready('Available')], 'controlPlane': {'desiredReplicas': 1, 'readyReplicas': 1, 'availableReplicas': 1}}},
         'kcp': {'kind': 'KubeadmControlPlane', 'spec': {'replicas': 1}, 'status': {'conditions': [ready('Available')], 'readyReplicas': 1, 'availableReplicas': 1}},
         'md': {'spec': {'replicas': workers}, 'status': {'replicas': workers, 'readyReplicas': workers, 'availableReplicas': workers}},
         'machines': {'items': []}, 'osmachines': {'items': []}, 'nodes': {'items': []}, 'pods': {'items': []},
         'nova': {'servers': [], 'ports': [], 'floating_ips': [{'id': 'api-fip', 'port': 'port-0'}], **{k: [{'id': k}] for k in ['networks', 'subnets', 'routers', 'security_groups']}},
         'calico': {'metadata': {'generation': 1}, 'status': {'observedGeneration': 1, 'updatedNumberScheduled': workers + 1}, 'spec': {'template': {'spec': {'containers': [{
             'name': 'calico-node', 'startupProbe': {'timeoutSeconds': 120, 'failureThreshold': 180, 'periodSeconds': 10, 'exec': {'command': ['/bin/calico-node', '-felix-live', '-bird-live']}},
             'readinessProbe': {'timeoutSeconds': 120, 'failureThreshold': 12}, 'livenessProbe': {'timeoutSeconds': 120, 'failureThreshold': 12}}]}}}}}
    for i in range(workers+1):
        name = 'test-' + str(i)
        pid = 'openstack:///id-' + str(i)
        s['machines']['items'].append({'metadata': {'name': name, 'uid': 'm-' + str(i), 'labels': {'cluster.x-k8s.io/control-plane': ''} if i == 0 else {}},
                                      'spec': {'providerID': pid, 'infrastructureRef': {'name': name}},
                                      'status': {'conditions': [ready()], 'nodeRef': {'name': name}, 'addresses': [{'type': 'InternalIP', 'address': '10.0.0.' + str(i+1)}]}})
        s['osmachines']['items'].append({'metadata': {'name': name, 'uid': 'osm-' + str(i)}, 'spec': {'providerID': pid}, 'status': {'ready': True}})
        s['nodes']['items'].append({'metadata': {'name': name, 'uid': 'n-' + str(i), 'labels': {'node-role.kubernetes.io/control-plane': ''} if i == 0 else {}},
                                   'spec': {'providerID': pid}, 'status': {'conditions': [ready()], 'allocatable': {'cpu': '2'}, 'nodeInfo': {'kubeletVersion': 'v1.35.7', 'architecture': 'amd64'}}})
        s['nova']['servers'].append({'id': 'id-' + str(i), 'name': name, 'status': 'ACTIVE'})
        s['nova']['ports'].append({'id': 'port-' + str(i), 'device_id': 'id-' + str(i)})
        s['pods']['items'].append({'metadata': {'name': 'calico-' + str(i), 'uid': 'p-' + str(i), 'namespace': 'kube-system', 'labels': {'k8s-app': 'calico-node'}}, 'spec': {'nodeName': name, 'containers': []}, 'status': {'conditions': [ready()]}})
    for app in ('calico-kube-controllers', 'kube-dns'):
        s['pods']['items'].append({'metadata': {'name': app, 'uid': app, 'namespace': 'kube-system', 'labels': {'k8s-app': app}}, 'spec': {'nodeName': 'test-1', 'containers': []}, 'status': {'conditions': [ready()]}})
    return s


class StateTests(unittest.TestCase):
    def test_all_supported_stable_counts(self):
        for workers in (1, 2, 3):
            self.assertEqual(state.evaluate(fixture(workers), workers, ENV), ('ready', []))

    def test_expected_transition_is_preparing(self):
        s = fixture(2)
        s['md']['spec']['replicas'] = 1
        s['machines']['items'][-1]['metadata']['deletionTimestamp'] = 'now'
        self.assertEqual(state.evaluate(s, 1, ENV)[0], 'preparing')

    def test_drift_does_not_repair(self):
        s = fixture()
        s['calico']['spec']['template']['spec']['containers'][0]['startupProbe']['timeoutSeconds'] = 1
        before = copy.deepcopy(s)
        self.assertEqual(state.evaluate(s, 1, ENV)[0], 'mismatch')
        self.assertEqual(s, before)

    def test_unavailable_is_not_zero_nodes(self):
        s = fixture()
        s['errors']['nodes'] = 'Forbidden'
        self.assertEqual(state.evaluate(s, 1, ENV), ('unavailable', ['nodes']))

    def test_wrong_nova_identity_and_error_are_not_ready(self):
        for field, value in [('id', 'wrong'), ('status', 'ERROR')]:
            s = fixture()
            s['nova']['servers'][1][field] = value
            self.assertEqual(state.evaluate(s, 1, ENV)[0], 'preparing')

    def test_registering_node_without_info_is_preparing(self):
        s = fixture(2)
        s['nodes']['items'][-1]['status'].pop('nodeInfo')
        s['machines']['items'][-1]['spec']['providerID'] = None
        self.assertEqual(state.evaluate(s, 2, ENV)[0], 'preparing')

    def test_partial_calico_coverage_not_ready(self):
        s = fixture(3)
        s['pods']['items'].pop(3)
        self.assertEqual(state.evaluate(s, 3, ENV)[0], 'preparing')

    def test_snapshot_commands_are_read_only_even_on_failure(self):
        with patch.dict(os.environ, ENV), tempfile.TemporaryDirectory() as tmp:
            client = state.Client()
            calls = []
            def fake_k(plane, *args, **kwargs):
                calls.append(args)
                raise RuntimeError('query unavailable')
            with patch.object(client, 'k', side_effect=fake_k), patch.object(state, 'command', side_effect=RuntimeError('offline')), patch.object(state, 'save'):
                snapshot = client.snapshot(Path(tmp) / 's.json')
            self.assertTrue(snapshot['errors'])
            self.assertTrue(all(args[0] == 'get' for args in calls))

    def test_wait_timeout_records_last_state(self):
        s = fixture(2)
        with patch.dict(os.environ, ENV), patch.object(state, 'save') as save, patch.object(state.time, 'monotonic', side_effect=[0, 0, 101, 101, 101]), patch.object(state.time, 'sleep'):
            client = state.Client()
            with patch.object(client, 'snapshot', return_value=s):
                with self.assertRaises(TimeoutError):
                    state.wait_ready(client, Path('/tmp/offline'), 1, 100)
            self.assertEqual(save.call_args.args[1]['state'], 'timeout')
            self.assertEqual(save.call_args.args[1]['last_observation']['state'], 'preparing')


class OwnershipTests(unittest.TestCase):
    def test_delete_has_uid_precondition(self):
        with patch.dict(os.environ, ENV):
            client = state.Client()
            with patch.object(client, 'k') as request:
                resources.delete_owned(client, 'w', {'kind': 'Pod', 'metadata': {'namespace': 'default', 'name': 'x', 'uid': 'original'}})
            self.assertEqual(json.loads(request.call_args.kwargs['data'])['preconditions'], {'uid': 'original'})
            self.assertNotIn('--force', request.call_args.args)

    def test_cleanup_never_deletes_if_evidence_capture_fails(self):
        client = state.Client.__new__(state.Client)
        with patch.object(resources, 'residues', return_value=[]), patch.object(resources, 'save', side_effect=RuntimeError('disk full')), patch.object(resources, 'delete_owned') as deletion:
            with self.assertRaises(RuntimeError): resources.cleanup(client, Path('/tmp/offline'))
            deletion.assert_not_called()

    def test_unowned_legacy_resource_is_never_deleted(self):
        with patch.dict(os.environ, ENV):
            client = state.Client()
            with patch.object(client, 'get', return_value={'items': []}), patch.object(client, 'k', return_value=json.dumps({'metadata': {'labels': {}}})):
                with self.assertRaisesRegex(RuntimeError, 'ownership label'):
                    resources.residues(client)

    def test_probe_preserves_failure_and_saves_before_success_delete(self):
        for phase in ('Succeeded', 'Failed'):
            with patch.dict(os.environ, ENV):
                client = state.Client()
                pod = {'kind': 'Pod', 'metadata': {'name': 'probe', 'namespace': 'default', 'uid': 'uid'}, 'status': {'phase': phase}}
                def fake_get(plane, resource, *args):
                    if resource == 'cluster': return {'spec': {'controlPlaneEndpoint': {'host': '10.0.0.1', 'port': 6443}}}
                    if resource == 'nodes': return {'items': []}
                    if resource == 'events': return {'items': []}
                    return pod
                actions = []
                with patch.object(client, 'get', side_effect=fake_get), patch.object(client, 'k', return_value=json.dumps(pod)), patch.object(resources, 'save', side_effect=lambda *args: actions.append('save')), patch.object(resources, 'delete_owned', side_effect=lambda *args: actions.append('delete')):
                    if phase == 'Failed':
                        with self.assertRaises(RuntimeError): resources.probe(client, Path('/tmp/offline'), 'run')
                        self.assertNotIn('delete', actions)
                    else:
                        resources.probe(client, Path('/tmp/offline'), 'run')
                        self.assertGreaterEqual(actions.index('delete'), 4)

if __name__ == '__main__':
    unittest.main()
