#!/usr/bin/env python3
"""Offline S2 window analysis from frozen campaign evidence; never mutates the campaign."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics

from graduation_evaluation_verify import percentile, read

WINDOWS = ['baseline', 'uncontrolled-0', 'uncontrolled-1', 'split-unlimited', 'fixed-0', 'fixed-1',
           'dynamic-0', 'dynamic-1', 'dynamic-2', 'dynamic-3', 'stable-0', 'stable-1']
CONDITIONS = {'uncontrolled': ['uncontrolled-0', 'uncontrolled-1'], 'split-unlimited': ['split-unlimited'],
              'fixed': ['fixed-0', 'fixed-1'], 'dynamic-stable': ['stable-0', 'stable-1']}


def window(path):
    data = read(path)
    rows, elapsed = data['rows'], data['elapsed']
    upload = data['progress_after']['bytes'] - data['progress_before']['bytes']
    before, after = data['qdisc_before'][0], data['qdisc_after'][0]
    return {'requests': len(rows), 'failures': sum(not r['ok'] for r in rows),
            'p95_ms': percentile([r['latency_ms'] for r in rows if r['ok']]),
            'elapsed_seconds': round(elapsed, 3), 'upload_bytes': upload,
            'upload_mbps': round(upload * 8 / elapsed / 1e6, 3),
            'api_mbps': round(sum(r['bytes'] for r in rows if r['ok']) * 8 / elapsed / 1e6, 3),
            'egress_mbps': round((after['bytes'] - before['bytes']) * 8 / elapsed / 1e6, 3),
            'egress_limit_mbps': round(after['options']['rate'] * 8 / 1e6, 3),
            'overlimits': after['overlimits'] - before['overlimits'], 'drops': after['drops'] - before['drops'],
            'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def analyse(campaign):
    cases = read(campaign / 'campaign.json')['cases']
    cases = cases.values() if isinstance(cases, dict) else cases
    runs = []
    for case in sorted((c for c in cases if c['scenario'] == 's2' and not c.get('negative')), key=lambda c: c['id']):
        evidence = Path(case['evidence'])
        windows = {name: window(evidence / f'{name}.json') for name in WINDOWS if (evidence / f'{name}.json').exists()}
        changes = read(evidence / 'run.json').get('policy_changes', [])
        runs.append({'id': case['id'], 'evidence': str(evidence), 'windows': windows,
                     'policy_changes': [{k: c[k] for k in ('time', 'kbps', 'burst_kbits', 'ovs') if k in c}
                                        for c in changes]})
    summary = {}
    for condition, names in CONDITIONS.items():
        per_run = []
        for run in runs:
            selected = [run['windows'][n] for n in names if n in run['windows']]
            if len(selected) == len(names):
                per_run.append({key: statistics.fmean(w[key] for w in selected)
                                for key in ('p95_ms', 'upload_mbps', 'egress_mbps', 'failures')})
        summary[condition] = {'runs': len(per_run), **{
            key: {'median': round(statistics.median(v), 3), 'min': round(min(v), 3), 'max': round(max(v), 3)}
            for key in ('p95_ms', 'upload_mbps', 'egress_mbps') if (v := [r[key] for r in per_run])},
            'failures': sum(r['failures'] for r in per_run) * len(names)}
    baseline = [r['windows']['baseline']['p95_ms'] for r in runs]
    return {'campaign': str(campaign), 'note': 'condition values average the windows of one run, then summarise runs',
            'baseline_p95_ms': {'median': statistics.median(baseline), 'min': min(baseline), 'max': max(baseline)},
            'summary': summary, 'runs': runs}


def markdown(result):
    lines = ['| 조건 | 실행 | p95 ms 중앙값 (범위) | 업로드 Mbit/s 중앙값 (범위) | 공통 출구 Mbit/s 중앙값 |',
             '|---|---:|---:|---:|---:|']
    for condition, s in result['summary'].items():
        lines.append(f"| {condition} | {s['runs']} | {s['p95_ms']['median']} ({s['p95_ms']['min']}~{s['p95_ms']['max']}) | "
                     f"{s['upload_mbps']['median']} ({s['upload_mbps']['min']}~{s['upload_mbps']['max']}) | "
                     f"{s['egress_mbps']['median']} |")
    lines += ['', '| 실행 | 구간 | 요청 | 실패 | p95 ms | 업로드 Mbit/s | API Mbit/s | 출구 Mbit/s | overlimits |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for run in result['runs']:
        for name, w in run['windows'].items():
            lines.append(f"| {run['id']} | {name} | {w['requests']} | {w['failures']} | {w['p95_ms']} | "
                         f"{w['upload_mbps']} | {w['api_mbps']} | {w['egress_mbps']} | {w['overlimits']} |")
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = analyse(args.campaign.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 's2-windows.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    (args.output / 's2-windows.md').write_text(markdown(result))
    print(markdown(result).split('\n\n')[0])


if __name__ == '__main__':
    main()
