"""Synthetic evidence for offline acceptance tests; no archived campaign dependency."""
import copy
import hashlib
import json
import datetime as dt


def put(root, name, value):
    (root / name).write_text(json.dumps(value))


def s2_evidence(root):
    names = ['baseline', 'uncontrolled-0', 'uncontrolled-1', 'split-unlimited',
             'fixed-0', 'fixed-1', 'stable-0', 'stable-1']
    before = {'time': '2026-10-23T00:00:00+00:00', 'cpu_ticks': [0] * 8,
              'cpu_pressure': ['some avg10=0 total=0']}
    after = {'time': '2026-10-23T00:01:00+00:00', 'cpu_ticks': [10, 0, 0, 90, 0, 0, 0, 0],
             'cpu_pressure': ['some avg10=0 total=60000']}
    windows = {}
    for name in names:
        stressed = name.startswith('uncontrolled') or name == 'split-unlimited'
        latency = 200 if stressed else 100
        raw = {'rows': [{'index': i, 'ok': True, 'latency_ms': latency} for i in range(120)],
               'progress_before': {'bytes': 0}, 'progress_after': {'bytes': 100},
               'qdisc_before': [{'bytes': 0, 'overlimits': 0, 'drops': 0}],
               'qdisc_after': [{'bytes': 150000000, 'overlimits': 100, 'drops': 0}], 'elapsed': 60,
               'host_before': {'compute': before}, 'host_after': {'compute': after}}
        put(root, name + '.json', raw)
        windows[name] = dict(requests=120, failures=0, p95_ms=latency, upload_bytes=100,
                             egress_bps=20000000, overlimits=100, drops=0, complete=True)
    summary = {'passed': True, 'windows': windows}
    put(root, 'summary.json', summary)
    pod = {'status': {'containerStatuses': [{'imageID': 'image'}]}}
    record = {'workers': [{'host': 'osk8s-compute02'}, {'host': 'osk8s-compute01'}],
              'policy_changes': [{'burst_kbits': 250, 'kbps': 6000, 'ovs': [['if', 6000, 250]]}],
              'api_before': pod, 'upload_before': copy.deepcopy(pod)}
    put(root, 'run.json', record)
    payload = hashlib.sha256(b'0').digest() * (1024 * 1024 // 32)
    put(root, 'upload-integrity.json', {'rows': [[0, len(payload), hashlib.sha256(payload).hexdigest()]],
                                      'bytes': len(payload), 'all_files_valid': True})
    return summary


def s4_evidence(root, sparse=False):
    def stamp(second):
        return (dt.datetime(2026, 10, 23, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=second)).isoformat()
    def obj(name, uid):
        return {'metadata': {'name': name, 'uid': uid, 'labels': {}}, 'spec': {},
                'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}
    machines, nodes = [], []
    for name in ('survivor', 'new'):
        m = obj(name, 'uid-' + name)
        m['metadata']['labels']['cluster.x-k8s.io/deployment-name'] = 'md'
        m['spec']['providerID'] = 'openstack:///vm-' + name
        m['status']['nodeRef'] = {'name': 'node-' + name}
        machines.append(m); nodes.append(obj('node-' + name, 'node-uid-' + name))
    probe = obj('probe', 'probe-uid'); probe['spec']['nodeName'] = 'node-new'
    app = obj('app', 'app-uid'); app['spec']['nodeName'] = 'node-survivor'
    app['metadata']['labels']['app'] = 'graduation-s4-http'
    snapshot = {'errors': {}, 'md': {'metadata': {'name': 'md'},
                'status': {'replicas': 2, 'readyReplicas': 2, 'availableReplicas': 2}},
                'machines': {'items': machines}, 'nodes': {'items': nodes}, 'osmachines': {'items': []},
                'nova': [{'ID': 'vm-' + n, 'Status': 'ACTIVE'} for n in ('survivor', 'new')],
                'pods': {'items': [probe, app]}, 'deployment': {'status': {'readyReplicas': 1}},
                'mhc': {'status': {'currentHealthy': 2, 'expectedMachines': 2}}}
    target = {'machine_uid': 'uid-old', 'node': 'node-old', 'nova_id': 'vm-old',
              'pod_uid': 'app-old', 'osmachine': 'osm-old'}
    record = {'version': 1, 'evidence': str(root), 'run_id': 'synthetic-s4', 'environment_run_id': 'env',
              'target': target, 'original_workers': ['uid-old', 'uid-survivor'], 'probe_name': 'probe',
              'stop_intent_at': stamp(0), 'injected_at': stamp(1)}
    put(root, 'run.json', record)
    put(root, 'baseline.json', {'pods': {'items': []}})
    put(root, 'stopped-nova.json', {'status': 'SHUTOFF'})
    put(root, 'finalization.json', {'fixture_phase': 'restored'})
    put(root, 'result.json', {'state': 'passed', 'target': target, 'capacity': {'state': 'recovered'},
                            'capacity_recovered_at': stamp(90), 'capacity_seconds': 89})
    (root / 'observations').mkdir()
    for i, t in enumerate((60, 75, 90)):
        put(root / 'observations', f'{i:04d}.json', {**snapshot, 'time': stamp(t)})
    times = [2, 100] if sparse else range(2, 101)
    samples = [{'time': stamp(0), 'ok': False, 'latency_ms': 10, 'error': 'no endpoints available'}]
    samples += [{'time': stamp(t), 'ok': True, 'latency_ms': 10} for t in times]
    (root / 'http.jsonl').write_text('\n'.join(json.dumps(s) for s in samples) + '\n')
    return record


def s3_evidence(root):
    run_id = 'synthetic-s3'
    pod = {'status': {'containerStatuses': [{'imageID': 'postgres-digest'}]}}
    record = {'run_id': run_id, 'volume_id': 'volume', 'evaluation_mode': 'automatic',
              'source': {'nova_id': 'source', 'host': 'osk8s-compute02'},
              'target': {'nova_id': 'target', 'host': 'osk8s-compute01'},
              'fault_at': '2026-10-23T00:00:00+00:00', 'fenced_at': '2026-10-23T00:01:00+00:00',
              'out_of_service_at': '2026-10-23T00:01:01+00:00', 'recovered_at': '2026-10-23T00:01:30+00:00',
              'durability': 'on:on:on:/var/lib/postgresql/data/pgdata', 'pod_before': pod, 'pod_after': copy.deepcopy(pod)}
    put(root, 'run.json', record)
    records = [{'id': i, 'value': hashlib.md5((str(i) + run_id).encode()).hexdigest()} for i in range(1, 1001)]
    for name in ('before', 'after'):
        put(root, 'committed-records-' + name + '.json', records)
        put(root, 'volume-' + name + '.json', {'id': 'volume', 'attachments': [
            {'server_id': 'source' if name == 'before' else 'target'}]})
    put(root, 'stabilization.json', [{'ok': True} for _ in range(60)])
    put(root, 'fault-impact.json', [{'ok': False} for _ in range(15)])
    put(root, 'fence.json', {'server': {'id': 'source', 'status': 'SHUTOFF',
        'OS-EXT-STS:task_state': None, 'OS-EXT-STS:power_state': 4, 'OS-EXT-SRV-ATTR:host': 'osk8s-compute02'},
        'hypervisor_state': 'shut off'})
    put(root, 'new-transaction.json', {'value': 'after-recovery'})
    put(root, 'summary.json', {'checks': {'new_transaction_readable': True}})
    return record
