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
import autoscaler_cycle as cycle
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


class CycleTests(unittest.TestCase):
    def test_cpu_request_prevents_two_on_fresh_worker(self):
        selected, _ = cycle.choose_request(fixture())
        self.assertGreater(selected * 2, 2000)
        self.assertLessEqual(selected, 2000)

    def test_insufficient_capacity_is_not_loosened(self):
        s = fixture()
        s['pods']['items'][-1]['spec']['containers'] = [{'resources': {'requests': {'cpu': '1100m'}}}]
        with self.assertRaisesRegex(RuntimeError, 'capacity insufficient'):
            cycle.choose_request(s)

    def test_deleted_identity_and_owned_ports(self):
        removed = cycle.retirement(fixture(3), fixture(2))
        self.assertEqual(removed[0]['server'], 'id-3')
        self.assertEqual(removed[0]['deleted_ports'], ['port-3'])

    def test_orphan_port_and_shared_deletion_fail(self):
        s = fixture(1)
        s['nova']['ports'].append({'id': 'port-2', 'device_id': ''})
        with self.assertRaisesRegex(RuntimeError, 'port remains'):
            cycle.retirement(fixture(2), s)
        s = fixture(1)
        s['nova']['security_groups'] = []
        with self.assertRaisesRegex(RuntimeError, 'shared'):
            cycle.retirement(fixture(2), s)

    def test_control_plane_replacement_is_rejected(self):
        s = fixture(1)
        s['machines']['items'][0]['metadata']['uid'] = 'replacement'
        with self.assertRaisesRegex(RuntimeError, 'control plane identity'):
            cycle.retirement(fixture(2), s)

    def test_scale_in_requires_actual_removed_node_event(self):
        with self.assertRaisesRegex(RuntimeError, 'deleted Node UID'):
            cycle.verify_transition(fixture(2), fixture(1), 'down', [{'involvedObject': {'uid': 'n-1'}}])
        removed = cycle.verify_transition(fixture(2), fixture(1), 'down', [{'involvedObject': {'uid': 'n-2'}}])
        self.assertEqual(len(removed), 1)

    def test_final_cleanup_cannot_hide_worker_replacement(self):
        s = fixture(1)
        # Replacement uses the old name: identity continuity still fails.
        s['machines']['items'][1]['metadata']['uid'] = 'replacement'
        with self.assertRaises(RuntimeError):
            cycle.verify_transition(fixture(1), s, None, [])

    def test_actual_pod_requests_and_termination_checked(self):
        s = fixture()
        pod = {'metadata': {'name': 'load', 'uid': 'load-1', 'labels': {'app.kubernetes.io/name': 'load'}},
               'spec': {'nodeName': 'test-1', 'containers': [{'resources': {'requests': {'cpu': '1200m'}}}]}, 'status': {'conditions': [ready()]}}
        s['pods']['items'].append(pod)
        self.assertTrue(cycle.pod_contract(s, 'load', 1200, 1))
        self.assertFalse(cycle.pod_contract(s, 'load', 1100, 1))
        pod['metadata']['deletionTimestamp'] = 'now'
        self.assertFalse(cycle.pod_contract(s, 'load', 1200, 1))

    def test_stale_and_unrelated_ca_events_do_not_prove_transition(self):
        before, current = fixture(), fixture(2)
        current['pods']['items'].append({'metadata': {'uid': 'new', 'labels': {'app.kubernetes.io/name': 'load'}}, 'spec': {}})
        event = {'metadata': {'uid': 'event'}, 'lastTimestamp': '2026-09-11T01:00:30Z', 'source': {'component': 'cluster-autoscaler'},
                 'reason': 'TriggeredScaleUp', 'involvedObject': {'uid': 'new', 'kind': 'Pod'}}
        start = '2026-09-11T01:00:00+00:00'
        self.assertEqual(len(cycle.ca_decisions(json.dumps({'items': [event]}), 'up', before, current, 'load', start)), 1)
        event['lastTimestamp'] = '2026-09-11T00:00:00Z'
        self.assertEqual(cycle.ca_decisions(json.dumps({'items': [event]}), 'up', before, current, 'load', start), [])

    def test_pdb_blocked_stage_terminates_without_scaling(self):
        s = fixture(2)
        with patch.dict(os.environ, ENV), patch.object(cycle, 'save') as saved, patch.object(cycle.time, 'monotonic', side_effect=[0, 0, 101, 101, 101]), patch.object(cycle.time, 'sleep'):
            client = state.Client()
            with patch.object(client, 'snapshot', return_value=s), patch.object(client, 'k') as mutation, patch.object(cycle, 'decision_evidence', return_value=({'pdb': 'disruptionsAllowed=0'}, {})):
                with self.assertRaises(TimeoutError):
                    cycle.stage(client, Path('/tmp/offline'), 1, 'load', 1200, s, 'down')
                mutation.assert_not_called()
            self.assertEqual(saved.call_args.args[1]['state'], 'timeout')

    def test_cycle_sequence_changes_only_test_deployment(self):
        class FakeClient:
            cluster, ns = 'test', 'default'
            def __init__(self): self.calls = []
            def k(self, plane, *args, **kwargs):
                self.calls.append((plane, args, kwargs))
                return json.dumps({'kind': 'Deployment', 'metadata': {'uid': 'owned', 'name': 'load', 'namespace': 'default'}})
            def get(self, *args): return {'metadata': {'uid': 'owned'}}
        client = FakeClient()
        targets = []
        def fake_stage(client, path, target, *args, **kwargs):
            targets.append(target)
            return fixture(target)
        with patch.dict(os.environ, ENV), tempfile.TemporaryDirectory() as tmp, patch.object(cycle, 'stage', side_effect=fake_stage), patch.object(cycle, 'save'), patch.object(cycle, 'probe'), patch.object(cycle, 'residues', return_value=[]), patch.object(cycle, 'command', return_value='no orphan'), patch.object(cycle, 'delete_owned'):
            cycle.run(client, Path(tmp))
        self.assertEqual(targets, [1, 2, 3, 2, 1, 2, 1, 1])
        self.assertTrue(all(plane == 'w' for plane, _, _ in client.calls))
        self.assertFalse(any('machinedeployment' in str(args) for _, args, _ in client.calls))
        patches = [json.loads(args[-1])[-1]['value'] for _, args, _ in client.calls if args[0] == 'patch']
        self.assertEqual(patches, [3, 2, 1, 2, 1])


class OwnershipTests(unittest.TestCase):
    def test_cleanup_records_unstarted_container_without_requesting_impossible_logs(self):
        pod = {'kind': 'Pod', 'metadata': {'name': 'infra-probe-x', 'namespace': 'default', 'uid': 'uid'},
               'status': {'containerStatuses': [{'name': 'load', 'state': {'waiting': {'reason': 'ContainerCreating'}}}]}}
        with patch.dict(os.environ, ENV), tempfile.TemporaryDirectory() as tmp:
            client = state.Client()
            with patch.object(resources, 'residues', side_effect=[[('w', pod)], []]), \
                    patch.object(client, 'get', return_value={}), patch.object(client, 'k') as logs, \
                    patch.object(resources, 'delete_owned') as delete:
                resources.cleanup(client, Path(tmp))
                logs.assert_not_called()
                delete.assert_called_once_with(client, 'w', pod)
                evidence = json.loads((Path(tmp) / 'w-uid-logs-unavailable.json').read_text())
                self.assertEqual(evidence['containers'][0]['state']['waiting']['reason'], 'ContainerCreating')

    def test_cleanup_mixed_containers_preserves_available_logs(self):
        pod = {'kind': 'Pod', 'metadata': {'name': 'infra-probe-x', 'namespace': 'default', 'uid': 'uid'},
               'status': {'containerStatuses': [
                   {'name': 'running', 'state': {'running': {}}},
                   {'name': 'pending', 'state': {'waiting': {'reason': 'ContainerCreating'}}},
                   {'name': 'crashed', 'state': {'waiting': {'reason': 'CrashLoopBackOff'}}, 'lastState': {'terminated': {}}}]}}
        with patch.dict(os.environ, ENV), tempfile.TemporaryDirectory() as tmp:
            client = state.Client()
            with patch.object(resources, 'residues', side_effect=[[('w', pod)], []]), \
                    patch.object(client, 'get', return_value={}), patch.object(client, 'k', return_value='log') as logs, \
                    patch.object(resources, 'delete_owned'):
                resources.cleanup(client, Path(tmp))
                calls = [call.args for call in logs.call_args_list]
                self.assertEqual(len(calls), 2)
                self.assertIn('running', calls[0])
                self.assertIn('--previous', calls[1])
                self.assertTrue((Path(tmp) / 'w-uid-running.log').exists())

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

    def test_manual_shell_leaves_ca_stopped_for_checked_owner_restore(self):
        source = (ROOT / 'scripts/workload-cluster.sh').read_text().split('case "${action}" in')[0]
        source = source.replace('PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"', 'PROJECT_ROOT=' + str(ROOT))
        for original, result in ((0, 0), (0, 1), (1, 0), (1, 1)):
            with tempfile.TemporaryDirectory() as tmp:
                script = source + r'''
require_management() { :; }
ensure_workload_api_access() { :; }
current_or_new_run() { printf '%s\n' "$TEST_TMP"; }
python3() { :; }
verify_cluster() { return "$TEST_VERIFY_STATUS"; }
probe_cluster() { :; }
kubectl() {
  printf '%s\n' "$*" >>"$TEST_TMP/calls"
  case "$*" in
    *"get deployment cluster-autoscaler --ignore-not-found"*) echo deployment/cluster-autoscaler ;;
    *"get deployment cluster-autoscaler -o jsonpath"*) echo "$TEST_CA_REPLICAS" ;;
    *"get machinedeployment"*) echo 2 ;;
    *"get pods"*) : ;;
  esac
}
scale_workers 1
'''
                env = {**os.environ, 'TEST_TMP': tmp, 'TEST_VERIFY_STATUS': str(result),
                       'TEST_CA_REPLICAS': str(original)}
                proc = subprocess.run(['bash', '-c', script], env=env, text=True, capture_output=True)
                self.assertEqual(proc.returncode, result, proc.stderr)
                calls = (Path(tmp) / 'calls').read_text()
                self.assertIn('scale deployment cluster-autoscaler --replicas=0', calls)
                self.assertNotIn('scale deployment cluster-autoscaler --replicas=1', calls)
                self.assertEqual(list(Path(tmp).glob('manual-*/autoscaler-restored.txt')), [])
                self.assertIn('scale machinedeployment osk8s-workload-md-0 --replicas=1', calls)


if __name__ == '__main__':
    unittest.main()
