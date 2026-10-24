#!/usr/bin/env python3
"""Independently recalculate frozen evaluation artifacts without cloud mutations."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

from graduation_evaluation_report import write_report


def read(path):
    return json.loads(Path(path).read_text())


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def epoch(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def percentile(values, fraction=.95):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    left = int(position)
    right = min(left + 1, len(values) - 1)
    return round(values[left] * (1 - (position - left)) + values[right] * (position - left), 3)


def window(samples, start, end):
    selected = [r for r in samples if epoch(start) <= epoch(r['time']) < epoch(end)]
    return {'requests': len(selected), 'failures': sum(not r['ok'] for r in selected),
            'p95_ms': percentile([r['latency_ms'] for r in selected if r['ok']])}


def image_id(pod):
    return sorted(c['imageID'] for c in pod['status']['containerStatuses'])


def equal_metric(actual, expected):
    if actual is None or expected is None:
        return actual is expected
    return math.isfinite(actual) and math.isfinite(expected) and abs(actual - expected) < .001


def mean_metric(values):
    values = list(values)
    return statistics.mean(values) if values and all(v is not None and math.isfinite(v) for v in values) else None


def host_metrics(before, after):
    delta = [b - a for a, b in zip(before['cpu_ticks'], after['cpu_ticks'])]
    if len(delta) != 8 or min(delta) < 0 or sum(delta) <= 0:
        raise ValueError('invalid host CPU counters')
    def pressure(sample):
        line = next(s for s in sample['cpu_pressure'] if s.startswith('some '))
        return int(re.search(r'\btotal=(\d+)', line).group(1))
    elapsed = epoch(after['time']) - epoch(before['time'])
    change = pressure(after) - pressure(before)
    if elapsed <= 0 or change < 0:
        raise ValueError('invalid host pressure interval')
    return {'cpu_utilization': round(1 - (delta[3] + delta[4]) / sum(delta), 5),
            'cpu_pressure_some': round(change / elapsed / 1_000_000, 5)}


def verify_s1(path, mode):
    summary, record, samples = read(path / 'summary.json'), read(path / 'run.json'), rows(path / 'http.jsonl')
    checks = {'request_indexes_complete': len(samples) == 5400 and {r['index'] for r in samples} == set(range(5400)),
              'source_compute': record['service_compute_host'] == 'osk8s-compute02',
              'target_compute': record['target_compute_host'] == 'osk8s-compute01'}
    calculated = {}
    for name, stored in summary['windows'].items():
        actual = window(samples, stored['start'], stored['end']); calculated[name] = actual
        checks[name + '_recalculated'] = (actual['requests'], actual['failures'], actual['p95_ms']) == (
            stored['requests'], stored['failures'], stored['latency_ms']['p95'])
    checks['source_pressure_persisted'] = all(summary[k] for k in (
        'source_contention_persisted', 'source_contention_at_completion', 'competitor_active_on_source'))
    decisions = rows(path / 'decisions.jsonl')
    last = next(d for d in reversed(decisions) if d['kind'] == 'diagnosis')
    pairs = {'baseline': ('baseline-start', 'baseline-end'),
             'contention': ('stress-start', 'decision-' + str(last['attempt'])),
             'relocated': ('relocated', 'post-relocation'),
             'completion': ('completion-start', 'completion-end')}
    hosts = {}
    for stage, (a, b) in pairs.items():
        before, after = read(path / ('hosts-' + a + '.json')), read(path / ('hosts-' + b + '.json'))
        hosts[stage] = {h: host_metrics(before[h], after[h]) for h in before}
    checks['raw_host_metrics'] = hosts == summary['host_metrics']
    source = record['service_compute_host']
    floor = max(.02, hosts['baseline'][source]['cpu_pressure_some'] * 2)
    checks['raw_contention_persists'] = all(hosts[s][source]['cpu_utilization'] >= .7 and
        hosts[s][source]['cpu_pressure_some'] >= floor for s in ('contention', 'relocated', 'completion'))
    contender = read(path / 'contender-after.json')
    checks['raw_competitor_identity'] = (contender['id'] == record['server_id'] and
        contender['status'] == 'ACTIVE' and contender['OS-EXT-SRV-ATTR:host'] == source)
    checks['image_unchanged'] = summary['service_before']['image_id'] == summary['service_after']['image_id']
    if mode == 'automatic':
        selected = record.get('stabilization_windows', [])
        checks['three_stable_windows'] = len(selected) == 3 and all(
            (actual := window(samples, w['start'], w['end']))['requests'] >= 270 and actual['failures'] == 0 and
            actual['p95_ms'] is not None and actual['p95_ms'] <= calculated['baseline']['p95_ms'] * 1.2 for w in selected)
        checks['one_action'] = record.get('action_count') == 1
        checks['all_requests_successful'] = not any(not r['ok'] for r in samples)
        checks['new_pod_other_worker'] = summary['service_before']['pod_uid'] != summary['service_after']['pod_uid'] and\
            summary['service_before']['node'] != summary['service_after']['node']
    else:
        checks['no_action'] = record.get('action_count') == 0
        checks['same_pod'] = summary['service_before']['pod_uid'] == summary['service_after']['pod_uid']
    if record.get('final_window'):
        last = record['final_window']; actual = window(samples, last['start'], last['end'])
        checks['final_window_recalculated'] = actual['p95_ms'] == last['latency_ms']['p95'] and actual['failures'] == last['failures']
    metrics = {'baseline_p95_ms': calculated['baseline']['p95_ms'], 'contention_p95_ms': calculated['contention']['p95_ms'],
               'post_p95_ms': calculated['relocated']['p95_ms'], 'requests': len(samples),
               'failures': sum(not r['ok'] for r in samples)}
    last = max(epoch(row['time']) for row in samples) + 1 / record['rate']
    final = [r for r in samples if last - 60 <= epoch(r['time']) < last]
    final_p95 = percentile([r['latency_ms'] for r in final if r['ok']])
    if mode == 'automatic':
        checks['final_window_recovers'] = len(final) >= 270 and all(r['ok'] for r in final) and\
            final_p95 is not None and final_p95 <= calculated['baseline']['p95_ms'] * 1.2
    metrics.update(final_60s_p95_ms=final_p95, final_60s_requests=len(final),
                   final_60s_failures=sum(not r['ok'] for r in final),
                   final_60s_baseline_ratio=round(final_p95 / calculated['baseline']['p95_ms'], 4))
    if record.get('recovery_confirmed_at'):
        metrics['diagnosis_to_stable_seconds'] = round(epoch(record['recovery_confirmed_at']) - epoch(record['diagnosis_at']), 3)
    return checks, metrics, [summary['service_before']['image_id']]


def verify_s2(path):
    summary, record = read(path / 'summary.json'), read(path / 'run.json')
    required = {'baseline', 'uncontrolled-0', 'uncontrolled-1', 'split-unlimited',
                'fixed-0', 'fixed-1', 'stable-0', 'stable-1'}
    checks, computed = {'required_windows': required <= set(summary['windows'])}, {}
    requests = failures = 0
    for name, expected in summary['windows'].items():
        sample = read(path / (name + '.json')); values = sample['rows']
        actual = {'requests': len(values), 'failures': sum(not r['ok'] for r in values),
                  'p95_ms': percentile([r['latency_ms'] for r in values if r['ok']]),
                  'upload_bytes': sample['progress_after']['bytes'] - sample['progress_before']['bytes'],
                  'egress_bps': (sample['qdisc_after'][0]['bytes'] - sample['qdisc_before'][0]['bytes']) * 8 / sample['elapsed'],
                  'overlimits': sample['qdisc_after'][0]['overlimits'] - sample['qdisc_before'][0]['overlimits'],
                  'drops': sample['qdisc_after'][0]['drops'] - sample['qdisc_before'][0]['drops']}
        computed[name] = actual
        checks[name + '_sample_indexes'] = len(values) == 120 and {r['index'] for r in values} == set(range(120))
        checks[name + '_metrics'] = all(equal_metric(actual[k], expected.get(k)) for k in actual)
        checks[name + '_valid_latencies'] = all(isinstance(r['latency_ms'], (int, float)) and
            math.isfinite(r['latency_ms']) and r['latency_ms'] >= 0 for r in values)
        requests += len(values); failures += sum(not r['ok'] for r in values)
    base = computed['baseline']['p95_ms']
    checks['baseline_valid'] = base is not None and base > 0 and computed['baseline']['failures'] == 0
    def stable(name):
        m = computed.get(name, {})
        return bool(checks['baseline_valid'] and m.get('requests') == 120 and m.get('failures') == 0 and
                    m.get('p95_ms') is not None and m['p95_ms'] <= base * 1.3 and m.get('upload_bytes', 0) > 0)
    def impacted(name):
        m = computed.get(name, {})
        return bool(checks['baseline_valid'] and m.get('requests') == 120 and
                    (m.get('failures', 0) > 0 or m.get('p95_ms') is not None and m['p95_ms'] > base * 1.5))
    checks['fixed_recovers'] = all(stable(n) for n in ('fixed-0', 'fixed-1'))
    checks['dynamic_recovers'] = all(stable(n) for n in ('stable-0', 'stable-1'))
    checks['split_alone_insufficient'] = impacted('split-unlimited')
    for name in ('uncontrolled-0', 'uncontrolled-1'):
        sample = read(path / (name + '.json'))
        utilization = [host_metrics(sample['host_before'][h], sample['host_after'][h])['cpu_utilization']
                       for h in sample['host_before']]
        metric = computed[name]
        checks[name + '_diagnosis'] = (impacted(name) and metric['egress_bps'] >= 16_000_000 and
            metric['overlimits'] > 0 and metric['upload_bytes'] > 0 and bool(utilization) and max(utilization) < .7)
    integrity = read(path / 'upload-integrity.json')
    chunks = integrity['rows']
    checks['upload_manifest_complete'] = bool(chunks) and integrity['bytes'] > 0 and integrity['all_files_valid'] and len({r[0] for r in chunks}) == len(chunks) and\
        sum(r[1] for r in chunks) == integrity['bytes']
    checks['upload_payload_digests'] = all(size == 1024 * 1024 and digest == hashlib.sha256(
        hashlib.sha256(str(index).encode()).digest() * (1024 * 1024 // 32)).hexdigest()
        for index, size, digest in chunks)
    checks['roles'] = [w['host'] for w in record['workers']] == ['osk8s-compute02', 'osk8s-compute01']
    checks['policy_enforced'] = bool(record['policy_changes']) and all(x['burst_kbits'] == 250 and len(x['ovs']) == 1 and
                                   x['ovs'][0][1:] == [x['kbps'], 250] for x in record['policy_changes'])
    metrics = {'baseline_p95_ms': computed['baseline']['p95_ms'],
               'uncontrolled_p95_ms': mean_metric(computed[n]['p95_ms'] for n in ('uncontrolled-0', 'uncontrolled-1')),
               'fixed_p95_ms': mean_metric(computed[n]['p95_ms'] for n in ('fixed-0', 'fixed-1')),
               'dynamic_p95_ms': mean_metric(computed[n]['p95_ms'] for n in ('stable-0', 'stable-1')),
               'fixed_upload_bytes_per_window': statistics.mean(computed[n]['upload_bytes'] for n in ('fixed-0', 'fixed-1')),
               'dynamic_upload_bytes_per_window': statistics.mean(computed[n]['upload_bytes'] for n in ('stable-0', 'stable-1')),
               'requests': requests, 'failures': failures, 'upload_bytes': integrity['bytes']}
    return checks, metrics, image_id(record['api_before']) + image_id(record['upload_before'])


def verify_s3(path):
    record, summary = read(path / 'run.json'), read(path / 'summary.json')
    before, after = read(path / 'committed-records-before.json'), read(path / 'committed-records-after.json')
    stable, impact = read(path / 'stabilization.json'), read(path / 'fault-impact.json')
    previous, following = read(path / 'volume-before.json'), read(path / 'volume-after.json')
    fence = read(path / 'fence.json')
    checks = {'commits_preserved': len(before) == 1000 and before == after,
              'commits_match_seed': before == [{'id': i, 'value': hashlib.md5((str(i) + record['run_id']).encode()).hexdigest()}
                                             for i in range(1, 1001)],
              'same_volume': previous['id'] == following['id'] == record['volume_id'],
              'old_attachment': len(previous['attachments']) == 1 and previous['attachments'][0]['server_id'] == record['source']['nova_id'],
              'new_attachment': len(following['attachments']) == 1 and following['attachments'][0]['server_id'] == record['target']['nova_id'],
              'stable_service': len(stable) == 60 and all(r['ok'] for r in stable),
              'real_impact': len(impact) == 15 and all(not r['ok'] for r in impact),
              'fence_before_taint': epoch(record['fenced_at']) < epoch(record['out_of_service_at']),
              'fence_evidence': fence['server']['status'] == 'SHUTOFF' and fence['hypervisor_state'] == 'shut off' and
                  fence['server']['OS-EXT-STS:task_state'] is None and fence['server']['OS-EXT-STS:power_state'] == 4 and
                  fence['server']['id'] == record['source']['nova_id'] and
                  fence['server']['OS-EXT-SRV-ATTR:host'] == record['source']['host'],
              'durability_enabled': record['durability'].startswith('on:on:on:/var/lib/postgresql/data/pgdata'),
              'image_unchanged': image_id(record['pod_before']) == image_id(record['pod_after']),
              'roles': record['source']['host'] == 'osk8s-compute02' and record['target']['host'] == 'osk8s-compute01',
              'new_transaction_verified': summary['checks']['new_transaction_readable'] and
                  read(path / 'new-transaction.json')['value'] == 'after-recovery'}
    if record['evaluation_mode'] == 'runbook':
        steps = record.get('runbook_steps', [])
        checks['explicit_runbook_steps'] = [r['step'] for r in steps] == ['fence', 'recover'] and all(r['returncode'] == 0 for r in steps)
    metrics = {'fault_intent_to_ready_seconds': round(epoch(record['recovered_at']) - epoch(record['fault_at']), 3),
               'fence_to_ready_seconds': round(epoch(record['recovered_at']) - epoch(record['fenced_at']), 3),
               'committed_records': len(after)}
    return checks, metrics, image_id(record['pod_before'])


def ready(obj):
    return any(c['type'] == 'Ready' and c['status'] == 'True'
               for c in obj.get('status', {}).get('conditions', []))


def raw_capacity(snapshot, record):
    old = record['target']
    md = snapshot['md']
    machines = [m for m in snapshot['machines']['items'] if
                m['metadata'].get('labels', {}).get('cluster.x-k8s.io/deployment-name') == md['metadata']['name']]
    fresh = [m for m in machines if m['metadata']['uid'] not in record['original_workers']]
    nodes = {n['metadata']['name']: n for n in snapshot['nodes']['items']}
    nova = {str(v.get('ID') or v.get('id')): v.get('Status') or v.get('status') for v in snapshot['nova']}
    probes = [p for p in snapshot['pods']['items'] if p['metadata']['name'] == record['probe_name']]
    service = [p for p in snapshot['pods']['items'] if
               p['metadata'].get('labels', {}).get('app') == 'graduation-s4-http' and
               not p['metadata'].get('deletionTimestamp')]
    return (not snapshot.get('errors') and len(machines) == 2 and len(fresh) == 1 and
            all(md['status'].get(k) == 2 for k in ('replicas', 'readyReplicas', 'availableReplicas')) and
            old['machine_uid'] not in {m['metadata']['uid'] for m in machines} and old['node'] not in nodes and
            old['nova_id'] not in nova and
            not any(m['metadata']['name'] == old.get('osmachine') for m in snapshot['osmachines']['items']) and
            all(ready(m) and ready(nodes.get(m.get('status', {}).get('nodeRef', {}).get('name'), {})) and
                nova.get(m['spec'].get('providerID', '').removeprefix('openstack:///')) == 'ACTIVE' for m in machines) and
            len(probes) == 1 and ready(probes[0]) and
            probes[0]['spec'].get('nodeName') == fresh[0].get('status', {}).get('nodeRef', {}).get('name') and
            len(service) == 1 and ready(service[0]) and service[0]['spec'].get('nodeName') != old['node'] and
            snapshot['deployment'].get('status', {}).get('readyReplicas') == 1)


def raw_http_stable(samples):
    """Independent acceptance implementation; never imports the online analyzer."""
    streak = []
    for row in samples:
        if not row['ok']:
            streak = []
            continue
        if streak and not 0 < epoch(row['time']) - epoch(streak[-1]['time']) <= 2.5:
            streak = []
        streak.append(row)
    return next((r['time'] for i, r in enumerate(streak, 1)
                 if i >= 20 and epoch(r['time']) - epoch(streak[0]['time']) >= 30), None)


def verify_s4(path, interrupted=False):
    record, summary = read(path / 'run.json'), read(path / 'analysis/summary.json')
    sample = rows(path / 'http.jsonl')
    used = [r for r in sample if epoch(r['time']) >= epoch(record['stop_intent_at'])]
    result, finalization = read(path / 'result.json'), read(path / 'finalization.json')
    checks = {'http_request_count': len(used) == summary['service']['requests'],
              'http_failures': sum(not r['ok'] for r in used) == summary['service']['failures'],
              'result_recovered': result['capacity']['state'] == 'recovered',
              'fixture_restored': finalization['fixture_phase'] == 'restored',
              'analysis_quality': summary['state'] == ('incomplete' if interrupted else 'complete')}
    stable = raw_http_stable(used)
    checks['raw_http_stable'] = stable is not None and stable == summary['service']['stable_success_confirmed_at']
    observations = [read(p) for p in sorted((path / 'observations').glob('[0-9][0-9][0-9][0-9].json'))]
    streak = []
    for observation in observations:
        if raw_capacity(observation, record):
            streak.append(observation['time'])
        else:
            streak = []
    checks['raw_final_capacity'] = bool(streak)
    at = result['capacity_recovered_at']
    checks['raw_capacity_stable'] = bool(streak) and at in streak and epoch(at) - epoch(streak[0]) >= 30
    checks['raw_capacity_duration'] = checks['raw_capacity_stable'] and equal_metric(
        epoch(at) - epoch(record['injected_at']), summary['durations_seconds']['shutoff_to_capacity_stable_seconds'])
    checks['snapshot_queries_succeeded'] = bool(observations) and all(not s.get('errors') for s in observations)
    metrics = dict(summary['durations_seconds'])
    service = summary['service']
    if service.get('first_failure_at') and service.get('stable_success_confirmed_at'):
        metrics['first_failure_to_service_stable_seconds'] = round(epoch(service['stable_success_confirmed_at']) - epoch(service['first_failure_at']), 3)
    metrics['requests'], metrics['failures'] = len(used), sum(not r['ok'] for r in used)
    baseline = read(path / 'baseline.json')
    pods = baseline.get('pods', {}).get('items', [])
    ids = sorted({v for p in pods if p['metadata'].get('namespace') == 'graduation-s4' for v in image_id(p)})
    return checks, metrics, ids


def verify_negative(path, scenario):
    proof, raw, record = read(path / 'expected-rejection.json'), read(path / 'negative-raw.json'), read(path / 'run.json')
    checks = dict(proof['checks'])
    if scenario == 's1':
        before, after = raw['before'], raw['after']
        key = 'openstack-k8s.dev/evaluation-unavailable'
        checks['raw_deployment_unchanged'] = before['deployment']['metadata']['uid'] == after['deployment']['metadata']['uid'] and before['deployment']['spec'] == after['deployment']['spec']
        checks['raw_service_unchanged'] = all(before['service'][k] == after['service'][k] for k in ('pod_uid', 'node', 'nova_id', 'image_id'))
        checks['raw_owned_taint_was_present'] = any(t['key'] == key and t.get('value') == record['run_id'] and t['effect'] == 'NoSchedule' for t in raw['during_node']['spec'].get('taints', []))
        checks['raw_owned_taint_removed'] = not any(t['key'] == key for t in after['node']['spec'].get('taints', []))
    elif scenario == 's2':
        before, after = raw['before'], raw['after']
        checks['raw_same_upload_pod'] = len(after['pods']) == 1 and before['pod']['metadata']['uid'] == after['pods'][0]['metadata']['uid'] and before['pod']['spec']['nodeName'] == after['pods'][0]['spec']['nodeName']
        checks['raw_port_policy_unchanged'] = all(before['port'].get(k) == after['port'].get(k) for k in ('id', 'device_id', 'qos_policy_id')) and not after['port'].get('qos_policy_id')
        checks['raw_original_rule_unchanged'] = all(before['rule'].get(k) == after['rule'].get(k) for k in ('id', 'max_kbps', 'max_burst_kbps', 'max_burst_kbits', 'direction')) and int(after['rule']['max_kbps']) == 6000
    else:
        checks['raw_vm_active'] = raw['server']['id'] == record['source']['nova_id'] and raw['server']['status'] == 'ACTIVE'
        checks['raw_pod_unchanged'] = raw['before_pod']['metadata']['uid'] == raw['after_pod']['metadata']['uid']
        checks['raw_no_out_of_service'] = not any(t['key'] == 'node.kubernetes.io/out-of-service' for t in raw['node']['spec'].get('taints', []))
        checks['raw_same_volume_identity'] = raw['pvc']['metadata']['uid'] == record['pvc_uid'] == raw['pv']['spec']['claimRef']['uid'] and raw['pvc']['spec']['volumeName'] == raw['pv']['metadata']['name'] and raw['pv']['spec']['csi']['volumeHandle'] == raw['volume']['id'] == record['volume_id']
        checks['raw_exclusive_source_attachment'] = len(raw['volume']['attachments']) == 1 and raw['volume']['attachments'][0]['server_id'] == record['source']['nova_id']
    return checks


def verify(directory, partial=False):
    directory = Path(directory)
    campaign = read(directory / 'campaign.json')
    source_checks = {name: (directory / 'source' / name).is_file() and hashlib.sha256((directory / 'source' / name).read_bytes()).hexdigest() == expected
                     for name, expected in campaign['source_sha256'].items()}
    output = {'campaign_id': campaign['id'], 'source_snapshots_valid': bool(source_checks) and all(source_checks.values()),
              'source_mismatches': [k for k, v in source_checks.items() if not v], 'cases': [], 'images': {}}
    for case in campaign['cases']:
        entry = {k: case[k] for k in ('id', 'scenario', 'mode', 'status', 'negative', 'repetition', 'accepted') if k in case}
        output['cases'].append(entry)
        if not case.get('evidence'):
            entry.update(verified=False, errors=['no evidence recorded']); continue
        path = Path(case['evidence'])
        try:
            if case['negative'] and case['scenario'] != 's4':
                checks, metrics, ids = verify_negative(path, case['scenario']), {}, []
                checks['expected_rejection_exit'] = case.get('returncode') == 20
            else:
                fn = {'s1': lambda p: verify_s1(p, case['mode']), 's2': verify_s2, 's3': verify_s3,
                      's4': lambda p: verify_s4(p, case['negative'])}[case['scenario']]
                checks, metrics, ids = fn(path)
                if case['negative']:
                    checks.update(read(directory / 'cases' / case['id'] / 'resume-verification.json'))
            checks['evidence_digests_match'] = bool(case.get('evidence_sha256')) and all((path / name).is_file() and hashlib.sha256((path / name).read_bytes()).hexdigest() == digest
                                                       for name, digest in case.get('evidence_sha256', {}).items())
            cleanup = read(directory / 'cases' / case['id'] / 'cleanup-verification.json')
            checks['cleanup_verified'] = cleanup['passed'] and bool(cleanup['checks']) and all(cleanup['checks'].values())
            entry.update(checks=checks, metrics=metrics, image_ids=ids, verified=all(checks.values()))
            if ids:
                output['images'].setdefault(case['scenario'], []).append(ids)
        except (OSError, KeyError, TypeError, ValueError, IndexError, ZeroDivisionError, StopIteration) as exc:
            entry.update(verified=False, errors=[f'{type(exc).__name__}: {exc}'])
    output['image_consistency'] = {k: all(value == values[0] for value in values) for k, values in output['images'].items()}
    output['all_planned_cases_finished'] = all(c['status'] in ('complete', 'needs_review') for c in campaign['cases'])
    output['all_artifacts_verified'] = output['source_snapshots_valid'] and all(output['image_consistency'].values()) and all(c['verified'] for c in output['cases'])
    output['all_acceptance_conditions_passed'] = all(c.get('accepted', False) for c in campaign['cases'])
    output['verification_complete'] = output['all_planned_cases_finished'] and output['all_artifacts_verified']
    final = directory / 'environment-final.json'
    hosts = read(final).get('final_hosts', {}) if final.exists() else {}
    output['hosts_stopped'] = bool(hosts) and set(hosts) == set(campaign['profile']['hosts']) and\
        all(v['status'] == 'TERMINATED' for v in hosts.values())
    output['groups'] = {}
    for entry in output['cases']:
        reasons = []
        if not entry.get('metrics'):
            reasons.append('no_metrics')
        if entry['negative']:
            reasons.append('negative_or_interruption_case')
        if not entry.get('accepted'):
            reasons.append('not_accepted')
        if not entry.get('verified'):
            reasons.append('not_verified')
        if not output['source_snapshots_valid']:
            reasons.append('invalid_source_snapshot')
        if output['image_consistency'].get(entry['scenario']) is False:
            reasons.append('inconsistent_runtime_images')
        entry['statistics_exclusions'] = reasons
        if reasons:
            continue
        group = entry['scenario'] + ':' + ('comparison' if entry['scenario'] == 's2' else entry['mode'])
        output['groups'].setdefault(group, []).append(entry)
    output['statistics'] = {}
    for group, entries in output['groups'].items():
        metrics = sorted({k for entry in entries for k, v in entry['metrics'].items() if isinstance(v, (int, float))})
        output['statistics'][group] = {'runs': len(entries), 'accepted': sum(e.get('accepted', False) for e in entries),
            'metrics': {key: {'median': statistics.median(values), 'min': min(values), 'max': max(values)}
                        for key in metrics if (values := [e['metrics'][key] for e in entries if isinstance(e['metrics'].get(key), (int, float))])}}
    output.pop('groups')
    (directory / 'independent-verification.json').write_text(json.dumps(output, indent=2, ensure_ascii=False) + '\n')
    metric_names = sorted({k for entry in output['cases'] for k in entry.get('metrics', {})})
    with (directory / 'results.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=['id', 'scenario', 'mode', 'status', 'accepted', 'verified', *metric_names])
        writer.writeheader()
        for entry in output['cases']:
            writer.writerow({**{k: entry.get(k) for k in writer.fieldnames[:6]}, **entry.get('metrics', {})})
    write_report(directory, campaign, output)
    print(json.dumps({k: output[k] for k in ('campaign_id', 'all_planned_cases_finished', 'all_artifacts_verified', 'all_acceptance_conditions_passed', 'hosts_stopped', 'statistics')}, indent=2))
    if not partial and not (output['verification_complete'] and output['hosts_stopped'] and output['all_acceptance_conditions_passed']):
        raise SystemExit(2)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign')
    parser.add_argument('--partial', action='store_true')
    args = parser.parse_args()
    verify(args.campaign, args.partial)


if __name__ == '__main__':
    main()
