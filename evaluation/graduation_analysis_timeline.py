#!/usr/bin/env python3
"""Offline S1/S3/S4 phase decomposition from frozen campaign evidence; never mutates the campaign."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics

from graduation_evaluation_verify import epoch, read, rows

# (phase name, start event, end event). Events are resolved per scenario below.
PHASES = {
    's1': [('detection', 'stress_observed_at', 'diagnosis_at'),
           ('destination_selection', 'diagnosis_at', 'relocation_intent_at'),
           ('rollout', 'relocation_intent_at', 'relocated_at'),
           ('settle', 'relocated_at', 'stabilization_start_at'),
           ('stability_windows', 'stabilization_start_at', 'recovery_confirmed_at'),
           ('total_diagnosis_to_stable', 'diagnosis_at', 'recovery_confirmed_at')],
    's3': [('node_not_ready', 'fault_at', 'node_not_ready_at'),
           ('fence_decision', 'node_not_ready_at', 'fence_requested_at'),
           ('fence_confirmation', 'fence_requested_at', 'fenced_at'),
           ('out_of_service', 'fenced_at', 'out_of_service_at'),
           ('replacement_scheduled', 'out_of_service_at', 'replacement_pod_started_at'),
           ('db_ready', 'replacement_pod_started_at', 'recovered_at'),
           ('total_fault_to_ready', 'fault_at', 'recovered_at'),
           ('total_fence_to_ready', 'fenced_at', 'recovered_at')],
    's4': [('stop_to_first_failure', 'stop_intent_at', 'first_failure_at'),
           ('stop_to_shutoff_confirmed', 'stop_intent_at', 'shutoff_confirmed_at'),
           ('failure_to_node_unhealthy', 'first_failure_at', 'node_unhealthy_at'),
           ('unhealthy_to_eviction', 'node_unhealthy_at', 'pod_eviction_at'),
           ('eviction_to_replacement_ready', 'pod_eviction_at', 'replacement_pod_ready_at'),
           ('replacement_ready_to_last_failure', 'replacement_pod_ready_at', 'last_failure_at'),
           ('last_failure_to_stable', 'last_failure_at', 'stable_success_confirmed_at'),
           ('total_failure_to_stable', 'first_failure_at', 'stable_success_confirmed_at'),
           ('supplementary_failure_to_first_stable', 'first_failure_at', 'first_stable_confirmed_at'),
           ('unhealthy_to_machine_delete', 'node_unhealthy_at', 'mhc_machine_delete_at'),
           ('delete_to_capacity_observed', 'mhc_machine_delete_at', 'capacity_first_observed_at'),
           ('capacity_observed_to_stable', 'capacity_first_observed_at', 'capacity_stable_confirmed_at'),
           ('total_shutoff_to_capacity_stable', 'shutoff_confirmed_at', 'capacity_stable_confirmed_at')],
}
# Waits that the frozen policy or manifests impose; reported next to the measured phases.
CONFIGURED = {
    's1': {'consecutive_diagnosis_windows': '2 x 60 s', 'settle': '30 s', 'stability_windows': '3 x 60 s'},
    's3': {'stabilization_after_ready': '60 DB checks (not part of total)'},
    's4': {'unreachable_toleration': '30 s (http-service.yaml)', 'mhc_unhealthy_timeout': '120 s',
           'http_stable': '30 s, >=20 samples, gap <=2.5 s', 'capacity_stable': '30 s'},
}


def s1_events(evidence):
    run = read(evidence / 'run.json')
    events = {k: v for k, v in run.items() if k.endswith('_at') and isinstance(v, str)}
    if not run.get('relocation_intent_at'):
        # The no-action control writes a phase marker here; it is not a relocation.
        events.pop('relocated_at', None)
        return events
    windows = run.get('stabilization_windows') or []
    if windows:
        events['stabilization_start_at'] = windows[0]['start']
    first = next((d for d in rows(evidence / 'decisions.jsonl') if d['kind'] == 'diagnosis'), None)
    if first:
        events['first_diagnosis_window_start_at'] = first['window']['start']
    return events


def s3_events(evidence):
    run = read(evidence / 'run.json')
    events = {k: v for k, v in run.items() if k.endswith('_at') and isinstance(v, str)}
    started = (run.get('pod_after') or {}).get('status', {}).get('startTime')
    if started:
        events['replacement_pod_started_at'] = started
    return events


def first_stable(samples, start, seconds=30, min_samples=20, max_gap=2.5):
    """First confirmation of the frozen HTTP stability rule after start, and later interruptions.

    The frozen metric keeps only the final streak; this supplementary view shows when the rule was first met.
    """
    streak, confirmed, interruptions = [], None, 0
    for sample in (s for s in samples if epoch(s['time']) >= epoch(start)):
        broken = not sample['ok'] or (streak and not 0 < epoch(sample['time']) - epoch(streak[-1]['time']) <= max_gap)
        if broken:
            interruptions += confirmed is not None
            streak = []
            if not sample['ok']:
                continue
        streak.append(sample)
        if confirmed is None and len(streak) >= min_samples and \
                epoch(sample['time']) - epoch(streak[0]['time']) >= seconds:
            confirmed = sample['time']
    return confirmed, interruptions


def s4_events(evidence):
    summary = read(evidence / 'analysis' / 'summary.json')
    events = {k: v for k, v in summary['events_utc'].items() if k.endswith('_at') and isinstance(v, str)}
    service = summary['service']
    events.update({k: service[k] for k in ('first_failure_at', 'last_failure_at', 'first_success_after_failure_at',
                                           'stable_success_confirmed_at') if service.get(k)})
    if service.get('first_failure_at'):
        confirmed, interruptions = first_stable(rows(evidence / 'http.jsonl'), service['first_failure_at'])
        if confirmed:
            events['first_stable_confirmed_at'] = confirmed
        events['interruptions_after_first_stable'] = interruptions
    return events


EVENTS = {'s1': s1_events, 's3': s3_events, 's4': s4_events}


def phases(scenario, events):
    result = {}
    for name, start, end in PHASES[scenario]:
        if events.get(start) and events.get(end):
            result[name] = round(epoch(events[end]) - epoch(events[start]), 3)
        else:
            result[name] = None
    return result


def analyse(campaign):
    cases = read(campaign / 'campaign.json')['cases']
    cases = cases.values() if isinstance(cases, dict) else cases
    runs = []
    for case in sorted(cases, key=lambda c: c['id']):
        scenario = case['scenario']
        if scenario not in PHASES or case.get('negative') or not case.get('accepted'):
            continue
        events = EVENTS[scenario](Path(case['evidence']))
        runs.append({'id': case['id'], 'scenario': scenario, 'mode': case['mode'], 'evidence': case['evidence'],
                     'events': events, 'phases': phases(scenario, events)})
    summary = {}
    for run in runs:
        group = summary.setdefault(f"{run['scenario']}:{run['mode']}", {})
        for name, value in run['phases'].items():
            group.setdefault(name, []).append(value)
    for group in summary.values():
        for name, values in list(group.items()):
            present = [v for v in values if v is not None]
            group[name] = {'n': len(present), 'missing': len(values) - len(present), **(
                {'median': round(statistics.median(present), 3), 'min': min(present), 'max': max(present)}
                if present else {})}
    return {'campaign': str(campaign), 'configured_waits': CONFIGURED, 'summary': summary, 'runs': runs}


def markdown(result):
    lines = []
    for group, values in result['summary'].items():
        lines += [f'### {group}', '', '| 구간 | n | 중앙값 s | 최소 | 최대 |', '|---|---:|---:|---:|---:|']
        for name, s in values.items():
            if s['n']:
                lines.append(f"| {name} | {s['n']} | {s['median']} | {s['min']} | {s['max']} |")
            else:
                lines.append(f'| {name} | 0 | - | - | - |')
        lines.append('')
    lines += ['### 실행별', '', '| 실행 | ' + ' | '.join(['구간', '초']) + ' |', '|---|---|---:|']
    for run in result['runs']:
        for name, value in run['phases'].items():
            lines.append(f"| {run['id']} | {name} | {'-' if value is None else value} |")
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = analyse(args.campaign.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'timeline.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    (args.output / 'timeline.md').write_text(markdown(result))
    print(markdown(result).split('### 실행별')[0])


if __name__ == '__main__':
    main()
