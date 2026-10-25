#!/usr/bin/env python3
"""Offline decision matrix (RQ4) and exact statistics from frozen campaign evidence; never mutates the campaign."""
from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path
import statistics

from graduation_evaluation_verify import read


def s1(case, evidence):
    run = read(evidence / 'run.json')
    if case['mode'] == 'no-destination':
        rejection = read(evidence / 'expected-rejection.json')
        return ('contention, impact, no eligible destination', 'defer, no change',
                'deferred' if rejection['passed'] and rejection['kind'] == 'no-destination' else 'other')
    diagnosed = run.get('automatic_trigger') is True
    if case['mode'] == 'no-action':
        observed = 'diagnosed, no action' if diagnosed and run.get('action_count') == 0 else 'other'
        return 'contention, impact (control arm)', 'diagnose; action suppressed by design', observed
    moved = run.get('action_count') == 1 and (run.get('service_after') or {}).get('nova_id') == run['target_nova_id']
    return ('contention, impact, destination available', 'relocate once to other compute',
            'relocated once to target' if diagnosed and moved else 'other')


def s2(case, evidence):
    run = read(evidence / 'run.json')
    if case['mode'] == 'qos-rejection':
        rejection = read(evidence / 'expected-rejection.json')
        return ('invalid QoS value rejected by Neutron', 'propagate error, keep policy and placement',
                'error propagated, unchanged' if rejection['passed'] else 'other')
    upload = run['upload_after'][0] if isinstance(run['upload_after'], list) else run['upload_after']
    port = next(w['port']['id'] for w in run['workers'] if w['node'] == upload['spec']['nodeName'])
    ports = {c['port_id'] for c in run.get('policy_changes', [])}
    correct = run.get('diagnosis') is True and ports == {port}
    return ('egress contention, impact', 'separate upload, limit only its port',
            'separated, limited upload port only' if correct else 'other')


def s3(case, evidence):
    run = read(evidence / 'run.json')
    if case['mode'] == 'fence-refusal':
        rejection = read(evidence / 'expected-rejection.json')
        return ('NotReady, VM still ACTIVE', 'refuse out-of-service, keep Pod and volume',
                'refused, unchanged' if rejection['passed'] else 'other')
    fence = read(evidence / 'fence.json')
    attachments = [a['server_id'] for a in read(evidence / 'volume-after.json').get('attachments', [])]
    correct = (fence['server']['id'] == run['source']['nova_id'] and fence['server']['status'] == 'SHUTOFF' and
               run['fenced_at'] < run['out_of_service_at'] and attachments == [run['target']['nova_id']])
    return ('NotReady, DB unreachable', 'fence source VM, then out-of-service, reattach to target',
            'fenced source, then recovered on target' if correct else 'other')


def s4(case, evidence):
    run = read(evidence / 'run.json')
    stopped = read(evidence / 'stopped-nova.json')
    correct = stopped['id'] == run['target']['nova_id'] and stopped['status'] == 'SHUTOFF'
    if case['mode'] == 'interrupt-resume':
        return ('runner killed after stop', 'resume same run without a second stop',
                'resumed, single stop' if correct else 'other')
    return 'target worker VM stopped', 'stop only the mapped VM; existing controllers recover', \
        'mapped VM stopped' if correct else 'other'


DECISIONS = {'s1': s1, 's2': s2, 's3': s3, 's4': s4}
# S4 rows check the harness's fault target and resume path; recovery itself belongs to existing controllers.
CATEGORY = {'s1': 'module_decision', 's2': 'module_decision', 's3': 'module_decision', 's4': 'integration'}
EXPECTED_OBSERVED = {
    'relocated once to target', 'diagnosed, no action', 'deferred', 'separated, limited upload port only',
    'error propagated, unchanged', 'fenced source, then recovered on target', 'refused, unchanged',
    'mapped VM stopped', 'resumed, single stop'}


def binomial_cdf(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def clopper_pearson(k, n, alpha=.05):
    def solve(predicate):
        low, high = 0.0, 1.0
        for _ in range(100):
            mid = (low + high) / 2
            low, high = (mid, high) if predicate(mid) else (low, mid)
        return round((low + high) / 2, 4)
    lower = 0.0 if k == 0 else solve(lambda p: 1 - binomial_cdf(k - 1, n, p) < alpha / 2)
    upper = 1.0 if k == n else solve(lambda p: binomial_cdf(k, n, p) > alpha / 2)
    return lower, upper


def ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            result[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return result


def mann_whitney_exact(a, b):
    pooled = a + b
    r = ranks(pooled)
    expected = len(a) * (len(pooled) + 1) / 2
    observed = abs(sum(r[:len(a)]) - expected)
    splits = list(itertools.combinations(range(len(pooled)), len(a)))
    extreme = sum(abs(sum(r[i] for i in s) - expected) >= observed - 1e-9 for s in splits)
    u = sum(r[:len(a)]) - len(a) * (len(a) + 1) / 2
    return {'u': u, 'p_two_sided': round(extreme / len(splits), 4), 'permutations': len(splits),
            'min_possible_p': round(2 / len(splits), 4)}


def cliffs_delta(a, b):
    return round(sum((x > y) - (x < y) for x in a for y in b) / (len(a) * len(b)), 3)


def wilcoxon_exact(x, y):
    diffs = [b - a for a, b in zip(x, y) if b != a]
    r = ranks([abs(d) for d in diffs])
    observed = sum(rk for rk, d in zip(r, diffs) if d > 0)
    expected = len(diffs) * (len(diffs) + 1) / 4
    signs = list(itertools.product((0, 1), repeat=len(diffs)))
    extreme = sum(abs(sum(rk for rk, s in zip(r, sign) if s) - expected) >= abs(observed - expected) - 1e-9
                  for sign in signs)
    return {'w_plus': observed, 'n_nonzero': len(diffs), 'p_two_sided': round(extreme / len(signs), 4),
            'min_possible_p': round(2 / len(signs), 4) if diffs else None,
            'positive_differences': sum(d > 0 for d in diffs)}


def describe(values):
    return {'n': len(values), 'median': round(statistics.median(values), 3), 'min': min(values), 'max': max(values)}


def proportion(k, n):
    lower, upper = clopper_pearson(k, n)
    return {'k': k, 'n': n, 'ci95': [lower, upper]}


def analyse(campaign):
    cases = read(campaign / 'campaign.json')['cases']
    cases = list(cases.values() if isinstance(cases, dict) else cases)
    verified = read(campaign / 'independent-verification.json')['cases']
    verified = verified if isinstance(verified, dict) else {c['id']: c for c in verified}
    matrix = []
    for case in sorted(cases, key=lambda c: c['id']):
        if case['scenario'] not in DECISIONS or not case.get('accepted'):
            continue
        condition, expected, observed = DECISIONS[case['scenario']](case, Path(case['evidence']))
        checks = verified[case['id']]['checks']
        matrix.append({'id': case['id'], 'scenario': case['scenario'], 'mode': case['mode'],
                       'negative': bool(case.get('negative')), 'category': CATEGORY[case['scenario']],
                       'condition': condition, 'expected': expected,
                       'observed': observed, 'correct': observed in EXPECTED_OBSERVED,
                       'independent_checks': f'{sum(checks.values())}/{len(checks)}'})
    metrics = {c['id']: verified[c['id']]['metrics'] for c in cases if c.get('accepted') and not c.get('negative')}

    def values(prefix, key):
        return [metrics[i][key] for i in sorted(metrics) if i.startswith(prefix) and metrics[i].get(key) is not None]

    s1_auto, s1_none = values('s1-automatic', 'final_60s_p95_ms'), values('s1-no-action', 'final_60s_p95_ms')
    s3_auto, s3_book = values('s3-automatic', 'fault_intent_to_ready_seconds'), values('s3-runbook',
                                                                                       'fault_intent_to_ready_seconds')
    s2_ids = sorted(i for i in metrics if i.startswith('s2-'))
    fixed = [metrics[i]['fixed_p95_ms'] for i in s2_ids]
    dynamic = [metrics[i]['dynamic_p95_ms'] for i in s2_ids]
    fixed_upload = [metrics[i]['fixed_upload_bytes_per_window'] for i in s2_ids]
    dynamic_upload = [metrics[i]['dynamic_upload_bytes_per_window'] for i in s2_ids]
    groups = {}
    for row in matrix:
        kind = 'negative' if row['negative'] else 'normal'
        groups.setdefault(f"{row['category']}_{kind}", []).append(row['correct'])
    stats = {
        'proportions': {
            **{f'{name}_correct': proportion(sum(v), len(v)) for name, v in sorted(groups.items())},
            'single_negative_case': proportion(1, 1),
            'five_of_five': proportion(5, 5),
            'ten_of_ten': proportion(10, 10),
        },
        's1_final_60s_p95_ms': {'automatic': describe(s1_auto), 'no_action': describe(s1_none),
                                'mann_whitney': mann_whitney_exact(s1_auto, s1_none),
                                'cliffs_delta_automatic_vs_no_action': cliffs_delta(s1_auto, s1_none)},
        's3_fault_intent_to_ready_seconds': {'automatic': describe(s3_auto), 'runbook': describe(s3_book),
                                             'mann_whitney': mann_whitney_exact(s3_auto, s3_book),
                                             'cliffs_delta_automatic_vs_runbook': cliffs_delta(s3_auto, s3_book)},
        's2_paired_by_run': {'runs': s2_ids,
                             'p95_ms': {'fixed': describe(fixed), 'dynamic': describe(dynamic),
                                        'wilcoxon_dynamic_minus_fixed': wilcoxon_exact(fixed, dynamic)},
                             'upload_bytes_per_window': {
                                 'fixed': describe(fixed_upload), 'dynamic': describe(dynamic_upload),
                                 'wilcoxon_dynamic_minus_fixed': wilcoxon_exact(fixed_upload, dynamic_upload)}},
    }
    return {'campaign': str(campaign), 'metrics_source': 'independent-verification.json (recomputed from raw)',
            'decision_matrix': matrix, 'statistics': stats}


def markdown(result):
    lines = ['| 실행 | 조건 | 기대 | 관측 | 일치 | 독립 검사 |', '|---|---|---|---|---|---:|']
    for row in result['decision_matrix']:
        lines.append(f"| {row['id']} | {row['condition']} | {row['expected']} | {row['observed']} | "
                     f"{'yes' if row['correct'] else 'no'} | {row['independent_checks']} |")
    return '\n'.join(lines) + '\n\n```json\n' + json.dumps(result['statistics'], indent=2) + '\n```\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = analyse(args.campaign.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'decisions.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    (args.output / 'decisions.md').write_text(markdown(result))
    print(markdown(result))


if __name__ == '__main__':
    main()
