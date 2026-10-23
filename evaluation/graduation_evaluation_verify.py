#!/usr/bin/env python3
"""Independently recalculate frozen evaluation artifacts without cloud mutations."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import statistics


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
    metrics.update(final_60s_p95_ms=final_p95, final_60s_requests=len(final),
                   final_60s_failures=sum(not r['ok'] for r in final),
                   final_60s_baseline_ratio=round(final_p95 / calculated['baseline']['p95_ms'], 4))
    if record.get('recovery_confirmed_at'):
        metrics['diagnosis_to_stable_seconds'] = round(epoch(record['recovery_confirmed_at']) - epoch(record['diagnosis_at']), 3)
    return checks, metrics, [summary['service_before']['image_id']]


def verify_s2(path):
    summary, record = read(path / 'summary.json'), read(path / 'run.json')
    checks, computed = {}, {}
    requests = failures = 0
    for name, expected in summary['windows'].items():
        sample = read(path / (name + '.json')); values = sample['rows']
        actual = {'p95_ms': percentile([r['latency_ms'] for r in values if r['ok']]),
                  'upload_bytes': sample['progress_after']['bytes'] - sample['progress_before']['bytes'],
                  'egress_bps': (sample['qdisc_after'][0]['bytes'] - sample['qdisc_before'][0]['bytes']) * 8 / sample['elapsed']}
        computed[name] = actual
        checks[name + '_sample_indexes'] = len(values) == 120 and {r['index'] for r in values} == set(range(120))
        checks[name + '_metrics'] = all(abs(actual[k] - expected[k]) < .001 for k in actual)
        requests += len(values); failures += sum(not r['ok'] for r in values)
    integrity = read(path / 'upload-integrity.json')
    chunks = integrity['rows']
    checks['upload_manifest_complete'] = bool(chunks) and integrity['bytes'] > 0 and integrity['all_files_valid'] and len({r[0] for r in chunks}) == len(chunks) and\
        sum(r[1] for r in chunks) == integrity['bytes']
    checks['upload_payload_digests'] = all(size == 1024 * 1024 and digest == hashlib.sha256(
        hashlib.sha256(str(index).encode()).digest() * (1024 * 1024 // 32)).hexdigest()
        for index, size, digest in chunks)
    checks['roles'] = [w['host'] for w in record['workers']] == ['osk8s-compute02', 'osk8s-compute01']
    checks['policy_enforced'] = all(x['burst_kbits'] == 250 and len(x['ovs']) == 1 and
                                   x['ovs'][0][1:] == [x['kbps'], 250] for x in record['policy_changes'])
    metrics = {'baseline_p95_ms': computed['baseline']['p95_ms'],
               'uncontrolled_p95_ms': statistics.mean(computed[n]['p95_ms'] for n in ('uncontrolled-0', 'uncontrolled-1')),
               'fixed_p95_ms': statistics.mean(computed[n]['p95_ms'] for n in ('fixed-0', 'fixed-1')),
               'dynamic_p95_ms': statistics.mean(computed[n]['p95_ms'] for n in ('stable-0', 'stable-1')),
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
              'same_volume': previous['id'] == following['id'] == record['volume_id'],
              'old_attachment': len(previous['attachments']) == 1 and previous['attachments'][0]['server_id'] == record['source']['nova_id'],
              'new_attachment': len(following['attachments']) == 1 and following['attachments'][0]['server_id'] == record['target']['nova_id'],
              'stable_service': len(stable) == 60 and all(r['ok'] for r in stable),
              'real_impact': len(impact) == 15 and all(not r['ok'] for r in impact),
              'fence_before_taint': epoch(record['fenced_at']) < epoch(record['out_of_service_at']),
              'fence_evidence': fence['server']['status'] == 'SHUTOFF' and fence['hypervisor_state'] == 'shut off' and
                  fence['server']['OS-EXT-STS:task_state'] is None and fence['server']['OS-EXT-STS:power_state'] == 4,
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
    source_checks = {name: hashlib.sha256((directory / 'source' / name).read_bytes()).hexdigest() == expected
                     for name, expected in campaign['source_sha256'].items()}
    output = {'campaign_id': campaign['id'], 'source_snapshots_valid': all(source_checks.values()),
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
            if case.get('evidence_sha256'):
                checks['evidence_digests_match'] = all((path / name).is_file() and hashlib.sha256((path / name).read_bytes()).hexdigest() == digest
                                                       for name, digest in case['evidence_sha256'].items())
            cleanup = read(directory / 'cases' / case['id'] / 'cleanup-verification.json')
            checks['cleanup_verified'] = cleanup['passed'] and all(cleanup['checks'].values())
            entry.update(checks=checks, metrics=metrics, image_ids=ids, verified=all(checks.values()))
            if ids:
                output['images'].setdefault(case['scenario'], []).append(ids)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            entry.update(verified=False, errors=[f'{type(exc).__name__}: {exc}'])
    output['image_consistency'] = {k: all(value == values[0] for value in values) for k, values in output['images'].items()}
    output['all_planned_cases_finished'] = all(c['status'] in ('complete', 'needs_review') for c in campaign['cases'])
    output['all_artifacts_verified'] = output['source_snapshots_valid'] and all(output['image_consistency'].values()) and all(c['verified'] for c in output['cases'])
    output['all_acceptance_conditions_passed'] = all(c.get('accepted', False) for c in campaign['cases'])
    output['verification_complete'] = output['all_planned_cases_finished'] and output['all_artifacts_verified']
    final = directory / 'environment-final.json'
    output['hosts_stopped'] = final.exists() and all(v['status'] == 'TERMINATED' for v in read(final)['final_hosts'].values())
    output['groups'] = {}
    for entry in output['cases']:
        if not entry.get('metrics') or entry['negative']:
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
    print(json.dumps({k: output[k] for k in ('campaign_id', 'all_planned_cases_finished', 'all_artifacts_verified', 'all_acceptance_conditions_passed', 'hosts_stopped', 'statistics')}, indent=2))
    if not partial and not (output['verification_complete'] and output['hosts_stopped']):
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
