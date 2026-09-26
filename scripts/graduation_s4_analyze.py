#!/usr/bin/env python3
"""Rebuild report-ready S4 results from immutable local experiment observations."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import statistics
import tempfile

from graduation_env import atomic_json
from graduation_s4_run import STABLE_SECONDS, summarize_capacity
from workload_state import condition


def epoch(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def difference(later, earlier):
    return round(epoch(later) - epoch(earlier), 3) if later and earlier else None


def error_kind(sample):
    if sample['ok']:
        return 'ok'
    error = sample.get('error', '').lower()
    if 'no endpoints available' in error:
        return 'no_endpoints'
    if 'unable to connect to the server' in error or 'context deadline exceeded' in error:
        return 'api_proxy_unavailable'
    if sample.get('body'):
        return 'unexpected_body'
    return 'other_error'


def stable_success(samples, last_failure, seconds=STABLE_SECONDS):
    later = [row for row in samples if epoch(row['time']) > epoch(last_failure)] if last_failure else samples
    if not later or not all(row['ok'] for row in later):
        return None, None
    started = later[0]['time']
    confirmed = next((row['time'] for row in later if difference(row['time'], started) >= seconds), None)
    return started, confirmed


def hash_sources(paths):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def observation_events(observations, record):
    target = record['target']
    times = {}
    final_replacement = None
    timeline = []
    capacity_candidates = []
    errors = []
    for path, snap in observations:
        at = snap['time']
        if snap.get('errors'):
            errors.append({'time': at, 'file': path.name, 'errors': snap['errors']})
            continue
        target_node = next((n for n in snap['nodes']['items'] if n['metadata']['name'] == target['node']), None)
        if target_node:
            ready = next((c for c in target_node.get('status', {}).get('conditions', []) if c['type'] == 'Ready'), {})
            if ready.get('status') in ('False', 'Unknown'):
                times.setdefault('node_unhealthy_at', ready.get('lastTransitionTime') or at)
            taints = target_node.get('spec', {}).get('taints', [])
            for taint in taints:
                if taint.get('key') == 'node.kubernetes.io/unreachable' and taint.get('effect') == 'NoExecute':
                    times.setdefault('unreachable_taint_at', taint.get('timeAdded') or at)
        for pod in snap['pods']['items']:
            metadata = pod['metadata']
            if metadata.get('uid') == target['pod_uid']:
                for c in pod.get('status', {}).get('conditions', []):
                    if c['type'] == 'DisruptionTarget' and c['status'] == 'True':
                        times.setdefault('pod_eviction_at', c.get('lastTransitionTime') or at)
                if metadata.get('deletionTimestamp'):
                    times.setdefault('old_pod_deleting_at', metadata['deletionTimestamp'])
            elif metadata.get('labels', {}).get('app') == 'graduation-s4-http' and condition(pod, 'Ready'):
                times.setdefault('replacement_pod_ready_at', next((c.get('lastTransitionTime') for c in
                    pod.get('status', {}).get('conditions', []) if c['type'] == 'Ready' and c['status'] == 'True'), at))
                times.setdefault('replacement_pod_uid', metadata['uid'])
        old = next((m for m in snap['machines']['items'] if m['metadata']['uid'] == target['machine_uid']), None)
        if old and old['metadata'].get('deletionTimestamp'):
            times.setdefault('mhc_machine_delete_at', old['metadata']['deletionTimestamp'])
        if not old:
            times.setdefault('old_machine_absent_observed_at', at)
        if target['nova_id'].lower() not in {str(v.get('ID') or v.get('id', '')).lower() for v in snap['nova']}:
            times.setdefault('old_nova_absent_observed_at', at)
        capacity = summarize_capacity(snap, target, record['original_workers'], record['probe_name'])
        if capacity['replacement']:
            final_replacement = capacity['replacement']
        if capacity['state'] == 'recovered':
            capacity_candidates.append(at)
        else:
            capacity_candidates.clear()
        timeline.append({'time': at, 'snapshot': path.name,
                         'mhc_healthy': snap['mhc'].get('status', {}).get('currentHealthy'),
                         'mhc_expected': snap['mhc'].get('status', {}).get('expectedMachines'),
                         'md_ready': snap['md'].get('status', {}).get('readyReplicas'),
                         'http_ready': snap['deployment'].get('status', {}).get('readyReplicas'),
                         'old_nova_present': target['nova_id'].lower() in {
                             str(v.get('ID') or v.get('id', '')).lower() for v in snap['nova']},
                         'capacity_state': capacity['state'],
                         'capacity_reasons': '; '.join(capacity.get('reasons', []))})
    first_capacity = capacity_candidates[0] if capacity_candidates else None
    stable_capacity = next((at for at in capacity_candidates if
                            difference(at, first_capacity) >= STABLE_SECONDS), None) if first_capacity else None
    if first_capacity:
        times['capacity_first_observed_at'] = first_capacity
    if stable_capacity:
        times['capacity_stable_confirmed_at'] = stable_capacity
    return times, timeline, errors, final_replacement


def analyze(evidence):
    evidence = Path(evidence).resolve()
    record = json.loads((evidence / 'run.json').read_text())
    if record.get('version') != 1 or Path(record['evidence']).resolve() != evidence:
        raise RuntimeError('S4 run record/evidence identity mismatch')
    if not record.get('stop_intent_at') or not record.get('injected_at'):
        raise RuntimeError('S4 stop was not confirmed; analysis cannot claim recovery')
    source_http = evidence / 'http.jsonl'
    samples = [json.loads(line) for line in source_http.read_text().splitlines()]
    if not samples or any('time' not in row or 'ok' not in row for row in samples):
        raise RuntimeError('HTTP sample stream is empty or malformed')
    snapshots = [(path, json.loads(path.read_text())) for path in sorted((evidence / 'observations').glob('*.json'))]
    if not snapshots:
        raise RuntimeError('no S4 infrastructure observations')
    times, infrastructure, query_errors, replacement = observation_events(snapshots, record)
    after = [row for row in samples if epoch(row['time']) >= epoch(record['stop_intent_at'])]
    if not after:
        raise RuntimeError('no HTTP samples after stop intent')
    failed = [row for row in after if not row['ok']]
    last_failure = failed[-1]['time'] if failed else None
    first_good, stable_good = stable_success(after, last_failure)
    gaps = [{'from': before['time'], 'to': following['time'],
             'seconds': difference(following['time'], before['time'])}
            for before, following in zip(samples, samples[1:])
            if difference(following['time'], before['time']) > 2.5]
    kinds = {kind: sum(error_kind(row) == kind for row in after)
             for kind in ('ok', 'api_proxy_unavailable', 'no_endpoints', 'unexpected_body', 'other_error')}
    good_latencies = [row['latency_ms'] for row in after if row['ok']]
    service = {'requests': len(after), 'successes': len(after) - len(failed), 'failures': len(failed),
               'success_rate': round((len(after) - len(failed)) / len(after), 5),
               'error_categories': kinds,
               'first_failure_at': failed[0]['time'] if failed else None,
               'last_failure_at': last_failure,
               'first_success_after_failure_at': first_good if failed else None,
               'stable_success_confirmed_at': stable_good,
               'observed_failure_to_success_seconds': difference(first_good, failed[0]['time']) if failed else None,
               'successful_latency_median_ms': round(statistics.median(good_latencies), 2) if good_latencies else None,
               'successful_latency_max_ms': max(good_latencies) if good_latencies else None,
               'probe_path': 'Kubernetes API Service proxy; not user ingress'}
    observed = {'stop_intent_at': record['stop_intent_at'], 'shutoff_confirmed_at': record['injected_at'],
                **times}
    durations = {
        'first_failure_to_node_unhealthy_seconds': difference(times.get('node_unhealthy_at'), service['first_failure_at']),
        'node_unhealthy_to_pod_eviction_seconds': difference(times.get('pod_eviction_at'), times.get('node_unhealthy_at')),
        'pod_eviction_to_replacement_ready_seconds': difference(times.get('replacement_pod_ready_at'), times.get('pod_eviction_at')),
        'shutoff_to_capacity_first_observed_seconds': difference(times.get('capacity_first_observed_at'), record['injected_at']),
        'shutoff_to_capacity_stable_seconds': difference(times.get('capacity_stable_confirmed_at'), record['injected_at']),
    }
    end = snapshots[-1][1]
    complete = bool(stable_good and times.get('capacity_stable_confirmed_at') and
                    not query_errors and not record.get('resumed_with_gap'))
    finalization_file = evidence / 'finalization.json'
    finalization = json.loads(finalization_file.read_text()) if finalization_file.exists() else None
    summary = {'version': 1, 'run_id': record['run_id'], 'environment_run_id': record['environment_run_id'],
               'state': 'complete' if complete else 'incomplete',
               'target': record['target'], 'replacement': replacement,
               'experiment_source_sha256': record.get('source_sha256'),
               'service': service, 'events_utc': observed, 'durations_seconds': durations,
               'observation_quality': {'http_samples_total': len(samples),
                                       'http_max_start_gap_seconds': max((g['seconds'] for g in gaps), default=0),
                                       'http_gaps_over_2_5_seconds': gaps,
                                       'infrastructure_snapshot_errors': query_errors,
                                       'resumed_with_gap': bool(record.get('resumed_with_gap')),
                                       'notes': ['HTTP timeouts create sampling gaps; durations are observed bounds',
                                                 'API proxy errors do not isolate user ingress availability']},
               'final_observed': {'mhc_healthy': end.get('mhc', {}).get('status', {}).get('currentHealthy'),
                                  'md_ready': end.get('md', {}).get('status', {}).get('readyReplicas'),
                                  'nova_ids': [v.get('ID') or v.get('id') for v in end.get('nova', [])]},
               'finalization': finalization,
               'source_sha256': hash_sources([source_http, evidence / 'baseline.json',
                                               evidence / 'stopped-nova.json',
                                               *[path for path, _ in snapshots],
                                               *([finalization_file] if finalization else [])])}
    output = evidence / 'analysis'
    output.mkdir(exist_ok=True, mode=0o700)
    atomic_json(output / 'summary.json', summary)
    write_csv(output / 'http-requests.csv',
              ['time', 'ok', 'category', 'latency_ms', 'body', 'error'],
              [{**row, 'category': error_kind(row)} for row in samples])
    write_csv(output / 'infrastructure-timeline.csv',
              ['time', 'snapshot', 'mhc_healthy', 'mhc_expected', 'md_ready', 'http_ready',
               'old_nova_present', 'capacity_state', 'capacity_reasons'], infrastructure)
    write_csv(output / 'events.csv', ['event', 'time_utc', 'seconds_from_stop_intent'],
              [{'event': name, 'time_utc': value,
                'seconds_from_stop_intent': difference(value, record['stop_intent_at'])}
               for name, value in observed.items() if name != 'replacement_pod_uid' and value])
    report = {'run_id': record['run_id'], 'state': summary['state'],
              'http_successes': service['successes'], 'http_requests': service['requests'],
              'http_failures': service['failures'],
              'api_proxy_errors': kinds['api_proxy_unavailable'],
              'no_endpoint_errors': kinds['no_endpoints'],
              'observed_service_seconds': service['observed_failure_to_success_seconds'],
              'worker_stable_seconds': durations['shutoff_to_capacity_stable_seconds'],
              'snapshot_errors': len(query_errors), 'http_gaps': len(gaps)}
    write_csv(output / 'report-row.csv', list(report), [report])
    rows = [f"# S4 run {record['run_id']}", '',
            '| Run | HTTP success / requests | API proxy errors | No endpoints | Observed service recovery | Stable worker recovery |',
            '|---|---:|---:|---:|---:|---:|',
            f"| {record['run_id']} | {service['successes']}/{service['requests']} | {kinds['api_proxy_unavailable']} | {kinds['no_endpoints']} | {service['observed_failure_to_success_seconds']} s | {durations['shutoff_to_capacity_stable_seconds']} s |",
            '', f"- Result: {summary['state']}",
            f"- HTTP probe path: {service['probe_path']}",
            f"- Snapshot query errors: {len(query_errors)}; HTTP gaps >2.5 s: {len(gaps)}", '']
    if finalization:
        rows += [f"- Fixture restored: {finalization.get('fixture_phase')} / {finalization.get('worker_mode')} / {finalization.get('worker_count')} worker(s)",
                 f"- Environment: {finalization.get('environment_phase')}", '']
    (output / 'report-table.md').write_text('\n'.join(rows))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args()
    result = analyze(args.evidence)
    print(json.dumps({'run_id': result['run_id'], 'state': result['state'],
                      'service': result['service'], 'durations_seconds': result['durations_seconds']},
                     indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
