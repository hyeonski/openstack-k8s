import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'observability' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = load('verify_live', 'verify-live.py')
manifest = load('manifest', 'build-run-manifest.py')


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.end = dt.datetime(2026, 9, 24, 9, tzinfo=dt.timezone.utc)
        self.start = self.end - dt.timedelta(minutes=30)
        self.times = [verify.iso(self.start + dt.timedelta(seconds=i)) for i in range(0, 1801, 60)]
        self.targets = [('cloud-gcp-amd64-hosts', h) for h in verify.HOST_INSTANCES]
        self.targets += [('management', 'management-node'), ('osk8s-workload', 'worker')]
        self.metrics = {name: {'series': 5, 'targets': [
            {'cluster': c, 'instance': h, 'sample_times': self.times.copy()} for c, h in self.targets]}
                        for name in verify.METRIC_PREFIXES}
        self.logs = {'sampled_count': 100, 'periodic': {
            **{'heartbeat:' + h: {'sample_times': self.times.copy()} for h in verify.HOST_INSTANCES},
            **{'nova:' + q: {'sample_times': self.times.copy()} for q in ('compute_service', 'hypervisor', 'nova_server')},
            **{'node-heartbeat:' + c + '/' + n: {'sample_times': self.times.copy()} for c, n in self.targets if c in verify.K8S_CLUSTERS}}}

    def assess(self, **kwargs):
        return verify.assess(self.metrics, self.logs, self.start, self.end, **kwargs)

    def test_continuous_targets_pass_without_requiring_noisy_events(self):
        self.assertEqual(self.assess(), [])

    def test_fresh_controller_cannot_mask_stale_compute_or_guest(self):
        for row in self.metrics.values():
            for target in row['targets']:
                if target['instance'] in ('osk8s-compute01', 'worker'):
                    target['sample_times'] = self.times[:6]
        missing = self.assess()
        self.assertIn('system_cpu:cloud-gcp-amd64-hosts/osk8s-compute01:gap', missing)
        self.assertIn('system_cpu:osk8s-workload/worker:gap', missing)

    def test_middle_gap_is_not_hidden_by_recent_sample(self):
        self.metrics['system_cpu']['targets'][0]['sample_times'] = self.times[:3] + self.times[-3:]
        self.assertTrue(any('system_cpu:' in x and x.endswith(':gap') for x in self.assess()))

    def test_never_reported_expected_node_is_missing(self):
        self.assertIn('system_cpu:osk8s-workload/missing-worker:absent', self.assess(
            expected=[{'cluster': 'osk8s-workload', 'instance': 'missing-worker'}]))

    def test_retired_worker_checks_only_recorded_lifetime(self):
        for row in self.metrics.values():
            for target in row['targets']:
                if target['instance'] == 'worker':
                    target['sample_times'] = self.times[:11]
        self.assertEqual(self.assess(expected=[{'cluster': 'osk8s-workload', 'instance': 'worker',
                                               'end_utc': self.times[10]}]), [])

    def test_stale_heartbeat_and_failed_nova_are_not_healthy(self):
        self.logs['periodic']['heartbeat:osk8s-compute02']['sample_times'] = self.times[:2]
        self.logs['periodic']['nova:nova_server']['failed_samples'] = 1
        missing = self.assess()
        self.assertIn('logs:heartbeat:osk8s-compute02:incomplete', missing)
        self.assertIn('logs:nova:nova_server:incomplete', missing)

    def test_guest_log_loss_is_not_hidden_by_healthy_host_logs_and_metrics(self):
        self.logs['periodic']['node-heartbeat:osk8s-workload/worker']['sample_times'] = []
        self.assertIn('logs:node-heartbeat:osk8s-workload/worker:incomplete', self.assess())

    def test_metric_api_keeps_each_target_timestamp(self):
        series = [{'resource': {'labels': {'cluster': c, 'instance': h}},
                   'points': [{'interval': {'endTime': t}} for t in (self.times if h == 'worker' else self.times[:2])]}
                  for c, h in self.targets]
        names = ['prometheus.googleapis.com/' + p + '/gauge' for p in verify.METRIC_PREFIXES.values()]
        with patch.object(verify, 'descriptors', return_value=names), \
                patch.object(verify, 'get_json', return_value={'timeSeries': series}):
            result = verify.metric_coverage('project', self.start, self.end, 'offline')
        targets = {r['instance']: r for r in result['system_cpu']['targets']}
        self.assertNotEqual(targets['worker']['latest_utc'], targets['osk8s-compute01']['latest_utc'])

    def test_node_log_queries_use_exported_cluster_and_instance_labels(self):
        with patch.object(verify.subprocess, 'check_output', return_value='[]') as read:
            verify.log_coverage('project', 'region', self.start, self.end,
                                [('management', 'shared-node'), ('osk8s-workload', 'shared-node')])
        queries = [call.args[0][3] for call in read.call_args_list]
        heartbeat_queries = [q for q in queries if 'collector_path_heartbeat' in q]
        self.assertEqual(len(heartbeat_queries), 2)
        for cluster, query in zip(('management', 'osk8s-workload'), heartbeat_queries):
            self.assertIn('labels."k8s.cluster.name"=' + json.dumps(cluster), query)
            self.assertIn('labels."service.instance.id"="shared-node"', query)


class ManifestTests(unittest.TestCase):
    def test_transient_and_probe_uids_survive_with_lifetimes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def write(path, obj):
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(obj))
            write('ownership.json', {'run': 'owner'})
            write('result.json', {'state': 'passed', 'time': '2026-09-24T09:00:00Z'})
            write('01-workers-2/started.json', {'time': '2026-09-24T08:00:00Z'})
            def pod(uid):
                return {'kind': 'Pod', 'metadata': {'uid': uid, 'name': uid, 'namespace': 'default',
                        'creationTimestamp': '2026-09-24T08:00:00Z',
                        'labels': {'test.openstack-k8s.io/run': 'owner'}}, 'spec': {'nodeName': 'worker'}}
            for index, uid in enumerate(('failed-pod', 'replacement')):
                write(f'01-workers-2/{index:04d}/snapshot.json', {
                    'time': f'2026-09-24T08:0{index}:00Z', 'pods': {'items': [pod(uid)]}})
            write('01-workers-2/probes/api-created.json', pod('short-probe'))
            write('admission/resources.json', [])
            result = manifest.build(root)
            self.assertEqual({p['pod_uid'] for p in result['pods']}, {'failed-pod', 'replacement', 'short-probe'})
            self.assertTrue(all(p.get('first_seen_utc') and p.get('last_seen_utc') for p in result['pods']))
            self.assertEqual(result['schema_version'], 2)

    def test_merge_preserves_earliest_and_latest_nonempty_identity(self):
        rows = {}
        manifest.merge_observation(rows, 'm', {'node': None}, '2026-09-24T08:00:00Z')
        manifest.merge_observation(rows, 'm', {'node': 'worker'}, '2026-09-24T08:05:00Z')
        manifest.merge_observation(rows, 'm', {'node': None}, '2026-09-24T08:10:00Z')
        self.assertEqual(rows['m']['node'], 'worker')
        self.assertEqual(rows['m']['first_seen_utc'], '2026-09-24T08:00:00Z')
        self.assertEqual(rows['m']['last_seen_utc'], '2026-09-24T08:10:00Z')
        self.assertEqual(rows['m']['node_first_seen_utc'], '2026-09-24T08:05:00Z')
        aggregate = {}
        manifest.merge_observation(aggregate, 'm', rows['m'], rows['m']['first_seen_utc'])
        self.assertEqual(aggregate['m']['node_first_seen_utc'], '2026-09-24T08:05:00Z')
