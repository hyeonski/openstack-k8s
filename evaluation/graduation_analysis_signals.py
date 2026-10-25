#!/usr/bin/env python3
"""Offline per-layer signal table (RQ1) from frozen campaign evidence; never mutates the campaign."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics

from graduation_analysis_s2 import window
from graduation_evaluation_verify import read, rows

# Where each signal comes from. Inferred signals are marked so the report does not present them as snapshots.
BASIS = {
    's1': {
        'service.p95_ratio': 'last diagnosis window p95 / baseline window p95 (run.json, decisions.jsonl)',
        'service.failures': 'failed requests in the two diagnosis windows',
        'kubernetes.pod_ready_unchanged': 'no-action only: service_after during contention has the same Pod UID, '
                                          'state ready, restart 0 (run.json)',
        'kubernetes.pod_served_all_requests': 'inferred: single replica behind ClusterIP answered every request',
        'kubernetes.pod_throttled_periods': 'pod_cpu_delta.nr_throttled in the triggering diagnosis',
        'infrastructure.same_compute_as_contender': 'placement-before.json service host == contender-server.json host',
        'infrastructure.source_cpu_utilization': 'triggering diagnosis host_metrics',
        'infrastructure.source_cpu_psi_some': 'triggering diagnosis host_metrics',
        'infrastructure.source_memory_io_psi_max': 'triggering diagnosis host_metrics',
        'infrastructure.target_cpu_utilization': 'triggering diagnosis host_metrics',
    },
    's2': {
        'service.p95_ratio': 'mean uncontrolled window p95 / baseline p95 (window JSON)',
        'service.failures': 'failed requests in the uncontrolled windows',
        'kubernetes.api_pod_ready_before': 'api_before Ready condition and restart 0 (run.json)',
        'kubernetes.api_pod_unchanged': 'result.checks.api_pod_unchanged (run.json)',
        'infrastructure.egress_utilization': 'uncontrolled qdisc bytes rate / tbf rate (window JSON)',
        'infrastructure.overlimits_per_window': 'uncontrolled qdisc overlimits delta (window JSON)',
        'infrastructure.max_host_cpu_utilization': 'uncontrolled window host CPU (window JSON)',
    },
    's3': {
        'service.db_client_failures': 'fault-impact.json failed checks / checks',
        'kubernetes.node_not_ready_observed': 'node_not_ready_at recorded after the Ready condition left True',
        'kubernetes.pod_unchanged_before_fence': 'fence-negative-check.json pod_unchanged',
        'infrastructure.old_db_container_running': 'old-db-running-after-fault.json: same container ID and Pod UID '
                                                   'in CONTAINER_RUNNING (guest crictl)',
        'infrastructure.vm_status_before_fence': 'fence-negative-check.json status (Nova)',
        'infrastructure.volume_attached_to_source': 'volume-before.json attachment server_id == source nova_id',
    },
    's4': {
        'service.http_failures': 'analysis/summary.json service failures / requests',
        'kubernetes.target_node_ready': 'first observation snapshot: target Node Ready condition',
        'kubernetes.target_unreachable_taint': 'first observation snapshot: unreachable taint on target Node',
        'kubernetes.target_pod_ready': 'first observation snapshot: HTTP Pod on target Node Ready condition',
        'infrastructure.target_vm_status': 'first observation snapshot: Nova status of target VM',
    },
}


def condition(obj, kind):
    return next((c['status'] for c in obj.get('status', {}).get('conditions', []) if c['type'] == kind), None)


def s1(evidence, mode):
    run = read(evidence / 'run.json')
    diagnoses = [d for d in rows(evidence / 'decisions.jsonl') if d['kind'] == 'diagnosis']
    trigger = diagnoses[-1]
    source, target = run['service_compute_host'], run['target_compute_host']
    metrics = trigger['host_metrics']
    contender = read(evidence / 'contender-server.json')['OS-EXT-SRV-ATTR:host']
    placement = read(evidence / 'placement-before.json')
    after = run.get('service_after') or {}
    before = run['service_before']
    signals = {
        'service.p95_ratio': round(trigger['window']['latency_ms']['p95'] / run['baseline_window']['latency_ms']['p95'], 3),
        'service.failures': sum(d['window']['failures'] for d in diagnoses),
        'kubernetes.pod_served_all_requests': all(d['window']['failures'] == 0 for d in diagnoses),
        'kubernetes.pod_throttled_periods': trigger['pod_cpu_delta']['nr_throttled'],
        'infrastructure.same_compute_as_contender': placement['service']['compute_host'] == contender == source,
        'infrastructure.source_cpu_utilization': metrics[source]['cpu_utilization'],
        'infrastructure.source_cpu_psi_some': metrics[source]['cpu_pressure_some'],
        'infrastructure.source_memory_io_psi_max': max(metrics[source]['memory_pressure_some'],
                                                       metrics[source]['io_pressure_some']),
        'infrastructure.target_cpu_utilization': metrics[target]['cpu_utilization'],
    }
    if mode == 'no-action':
        signals['kubernetes.pod_ready_unchanged'] = (after.get('pod_uid') == before['pod_uid'] and
                                                     after.get('state') == 'ready' and after.get('restart_count') == 0)
    return signals


def s2(evidence, mode):
    run = read(evidence / 'run.json')
    measured = [window(evidence / f'uncontrolled-{i}.json') for i in range(2)]
    baseline = window(evidence / 'baseline.json')
    api = run['api_before'][0] if isinstance(run['api_before'], list) else run['api_before']
    return {
        'service.p95_ratio': round(statistics.fmean(w['p95_ms'] for w in measured) / baseline['p95_ms'], 3),
        'service.failures': sum(w['failures'] for w in measured),
        'kubernetes.api_pod_ready_before': condition(api, 'Ready') == 'True' and
        all(s.get('restartCount') == 0 for s in api['status'].get('containerStatuses', [])),
        'kubernetes.api_pod_unchanged': run['result']['checks'].get('api_pod_unchanged'),
        'infrastructure.egress_utilization': round(statistics.fmean(w['egress_mbps'] / w['egress_limit_mbps']
                                                                    for w in measured), 3),
        'infrastructure.overlimits_per_window': round(statistics.fmean(w['overlimits'] for w in measured)),
        'infrastructure.max_host_cpu_utilization': round(max(max(read(evidence / f'uncontrolled-{i}.json')
                                                                 ['cpu_utilization'].values()) for i in range(2)), 3),
    }


def s3(evidence, mode):
    run = read(evidence / 'run.json')
    impact = read(evidence / 'fault-impact.json')
    guard = read(evidence / 'fence-negative-check.json')
    old_pod = run['pod_before']
    expected = old_pod['status']['containerStatuses'][0]['containerID'].split('://', 1)[-1]
    running = read(evidence / 'old-db-running-after-fault.json').get('containers', [])
    attachments = read(evidence / 'volume-before.json').get('attachments', [])
    return {
        'service.db_client_failures': f"{sum(not r['ok'] for r in impact)}/{len(impact)}",
        'kubernetes.node_not_ready_observed': bool(run.get('node_not_ready_at')),
        'kubernetes.pod_unchanged_before_fence': guard.get('pod_unchanged'),
        'infrastructure.old_db_container_running': any(
            c.get('id') == expected and c.get('state') == 'CONTAINER_RUNNING' and
            c.get('labels', {}).get('io.kubernetes.pod.uid') == old_pod['metadata']['uid'] for c in running),
        'infrastructure.vm_status_before_fence': guard.get('status'),
        'infrastructure.volume_attached_to_source': [a['server_id'] for a in attachments] == [run['source']['nova_id']],
    }


def s4(evidence, mode):
    summary = read(evidence / 'analysis' / 'summary.json')
    target = summary['target']
    first = read(sorted((evidence / 'observations').glob('*.json'))[0])
    node = next(n for n in first['nodes']['items'] if n['metadata']['name'] == target['node'])
    pods = [p for p in first['pods']['items'] if p['spec'].get('nodeName') == target['node']]
    vm = next(v for v in first['nova'] if v['ID'] == target['nova_id'])
    return {
        'service.http_failures': f"{summary['service']['failures']}/{summary['service']['requests']}",
        'kubernetes.target_node_ready': condition(node, 'Ready'),
        'kubernetes.target_unreachable_taint': any(t['key'] == 'node.kubernetes.io/unreachable'
                                                   for t in node['spec'].get('taints', [])),
        'kubernetes.target_pod_ready': condition(pods[0], 'Ready') if pods else None,
        'infrastructure.target_vm_status': vm['Status'],
    }


EXTRACT = {'s1': s1, 's2': s2, 's3': s3, 's4': s4}


def summarise(values):
    values = [v for v in values if v is not None]
    if values and all(isinstance(v, bool) for v in values):
        return f'{sum(values)}/{len(values)} true'
    if values and all(isinstance(v, (int, float)) for v in values):
        return f'median {round(statistics.median(values), 3)} ({min(values)}~{max(values)})'
    counts = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return ', '.join(f'{k} x{n}' for k, n in sorted(counts.items()))


def analyse(campaign):
    cases = read(campaign / 'campaign.json')['cases']
    cases = cases.values() if isinstance(cases, dict) else cases
    runs = []
    for case in sorted(cases, key=lambda c: c['id']):
        if case['scenario'] in EXTRACT and not case.get('negative') and case.get('accepted'):
            runs.append({'id': case['id'], 'scenario': case['scenario'], 'mode': case['mode'],
                         'evidence': case['evidence'],
                         'signals': EXTRACT[case['scenario']](Path(case['evidence']), case['mode'])})
    summary = {}
    for run in runs:
        # S2 orders only change the post-diagnosis comparison; the fault-time signals form one group.
        mode = 'comparison' if run['scenario'] == 's2' else run['mode']
        group = summary.setdefault(f"{run['scenario']}:{mode}", {})
        for key, value in run['signals'].items():
            group.setdefault(key, []).append(value)
    summary = {group: {key: summarise(values) for key, values in signals.items()} for group, signals in summary.items()}
    return {'campaign': str(campaign), 'basis': BASIS, 'summary': summary, 'runs': runs}


def markdown(result):
    lines = []
    for group, signals in result['summary'].items():
        scenario = group.split(':', 1)[0]
        lines += [f'### {group}', '', '| 신호 | 결과 | 근거 |', '|---|---|---|']
        lines += [f"| {key} | {value} | {result['basis'][scenario].get(key, '')} |" for key, value in signals.items()]
        lines.append('')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = analyse(args.campaign.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'signals.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    (args.output / 'signals.md').write_text(markdown(result))
    print(markdown(result))


if __name__ == '__main__':
    main()
