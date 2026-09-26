"""S4 service and capacity completion remain independent and identity based."""
import datetime as dt
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from graduation_s4_run import S4Run, s4_host_budget, summarize_capacity, summarize_http


def stamp(second):
    return (dt.datetime(2026, 9, 26, tzinfo=dt.timezone.utc) +
            dt.timedelta(seconds=second)).isoformat()


def obj(name, uid, ready=True, node=None, deployment=None, provider=None):
    value = {'metadata': {'name': name, 'uid': uid, 'labels': {}},
             'status': {'conditions': [{'type': 'Ready', 'status': 'True' if ready else 'False'}]},
             'spec': {}}
    if node:
        value['status']['nodeRef'] = {'name': node}
    if deployment:
        value['metadata']['labels']['cluster.x-k8s.io/deployment-name'] = deployment
    if provider:
        value['spec']['providerID'] = provider
    return value


class S4ResultsTests(unittest.TestCase):
    def test_no_http_failure_does_not_invent_outage(self):
        rows = [{'time': stamp(i), 'ok': True} for i in (10, 20, 50)]
        result = summarize_http(rows, stamp(5))
        self.assertEqual(result['state'], 'no_observed_outage')
        self.assertIsNone(result['outage_seconds'])

    def test_http_recovery_requires_stable_success_after_last_failure(self):
        rows = [{'time': stamp(i), 'ok': okay} for i, okay in
                ((5, False), (10, True), (20, False), (21, True), (45, True))]
        self.assertEqual(summarize_http(rows, stamp(0))['state'], 'not_stable')
        rows.append({'time': stamp(52), 'ok': True})
        result = summarize_http(rows, stamp(0))
        self.assertEqual(result['state'], 'recovered')
        self.assertEqual(result['failed'], 2)
        self.assertEqual(result['outage_seconds'], 16)

    def test_stop_command_window_includes_failures_before_shutoff_confirmation(self):
        rows = [{'time': stamp(i), 'ok': okay} for i, okay in
                ((0, True), (3, False), (9, False), (12, True), (45, True))]
        result = summarize_http(rows, stamp(0))
        self.assertEqual(result['failed'], 2)
        self.assertEqual(result['outage_seconds'], 9)

    def test_capacity_needs_old_resources_gone_and_new_worker_probe_ready(self):
        md = 'workload-md-0'
        survivor = obj('survivor', 'uid-survivor', node='node-survivor', deployment=md,
                       provider='openstack:///nova-survivor')
        replacement = obj('new', 'uid-new', node='node-new', deployment=md,
                          provider='openstack:///nova-new')
        probe = obj('new-worker-probe', 'uid-probe')
        probe['spec']['nodeName'] = 'node-new'
        service_pod = obj('http-1', 'uid-http')
        service_pod['metadata']['labels']['app'] = 'graduation-s4-http'
        service_pod['spec']['nodeName'] = 'node-survivor'
        snapshot = {'errors': {}, 'md': {'metadata': {'name': md},
                                        'status': {'replicas': 2, 'readyReplicas': 2, 'availableReplicas': 2}},
                    'machines': {'items': [survivor, replacement]},
                    'nodes': {'items': [obj('node-survivor', 'n1'), obj('node-new', 'n2')]},
                    'osmachines': {'items': [obj('osm-survivor', 'o1'), obj('osm-new', 'o2')]},
                    'nova': [{'ID': 'nova-survivor', 'Status': 'ACTIVE'},
                             {'ID': 'nova-new', 'Status': 'ACTIVE'}],
                    'pods': {'items': [probe, service_pod]},
                    'deployment': {'status': {'readyReplicas': 1}}}
        target = {'machine_uid': 'uid-old', 'node': 'node-old', 'nova_id': 'nova-old',
                  'osmachine': 'osm-old'}
        originals = ['uid-old', 'uid-survivor']
        self.assertEqual(summarize_capacity(snapshot, target, originals, 'new-worker-probe')['state'], 'recovered')
        snapshot['nova'].append({'ID': 'nova-old', 'Status': 'SHUTOFF'})
        self.assertIn('original Nova VM remains', summarize_capacity(
            snapshot, target, originals, 'new-worker-probe')['reasons'])
        snapshot['nova'].pop()
        probe['status']['conditions'][0]['status'] = 'False'
        self.assertIn('new worker HTTP probe not Ready', summarize_capacity(
            snapshot, target, originals, 'new-worker-probe')['reasons'])

    def test_host_budget_requires_running_original_host_id(self):
        record = {'initial_hosts': {'controller': {'id': '123'}}}
        row = {'name': 'controller', 'id': '123', 'status': 'RUNNING',
               'lastStartTimestamp': '2026-09-26T00:00:00Z',
               'scheduling': {'maxRunDuration': {'seconds': 36000}}}
        with patch.dict('os.environ', {'GCP_PROJECT_ID': 'project', 'GCP_ZONE': 'zone'}),\
                patch('graduation_s4_run.command', return_value=__import__('json').dumps([row])):
            self.assertEqual(s4_host_budget(record), 1790416800)
            row['id'] = 'other'
        with patch.dict('os.environ', {'GCP_PROJECT_ID': 'project', 'GCP_ZONE': 'zone'}),\
                patch('graduation_s4_run.command', return_value=__import__('json').dumps([row])):
            with self.assertRaisesRegex(RuntimeError, 'identity/state/budget mismatch'):
                s4_host_budget(record)

    def test_pending_stop_intent_cannot_inject_again(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = S4Run.__new__(S4Run)
            runner.lock_path = Path(directory) / 'experiment.lock'
            runner.read = lambda: {'phase': 'stop-intent'}
            with self.assertRaisesRegex(RuntimeError, 'never inject twice'):
                runner.run()


if __name__ == '__main__':
    unittest.main()
