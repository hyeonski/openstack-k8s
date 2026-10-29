"""Read-only, post-hoc S1/S2 tables; saved strict verdicts remain authoritative."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from fresh_campaign import check_frozen
from fresh_analysis import read, rows, request_metrics
from fresh_evidence import epoch

NOTICE = ('Post-hoc descriptive analysis only; does not replace the original primary, '
          'pool extension/supplemental samples with main, or promote strict verdicts. '
          '사후 분석이며 원래 primary를 대체하지 않는다.')
STRICT = ('trial_valid', 'fault_realized', 'impact_realized', 'recovered', 'safety',
          'execution', 'cleanup', 'missing', 'checks', 'v1_outcome')


def post_action(directory, cfg, metrics):
    """Use the original UTC latency semantics and request classifier, not new bins."""
    key = ('action_applied_seconds' if metrics.get('action_applied_seconds') is not None
           else 'diagnosis_seconds')
    offset = metrics.get(key)
    result = dict(anchor=key if offset is not None else None, seconds=offset,
                  service_slo_violation_fraction=None, errors=[])
    interval = metrics.get('interval')
    if offset is None or not interval:
        result['errors'] = ['action_and_diagnosis_missing' if offset is None else 'horizon_missing']
        return result
    start, end = interval[0] + offset, interval[1]
    if not math.isfinite(offset) or not interval[0] <= start < end:
        result['errors'] = ['anchor_outside_nonempty_horizon']
        return result
    requests = rows(Path(directory) / 'requests.jsonl')
    # Count scheduled arrivals on the registered index/rate lattice. Rounding
    # duration*rate alone can be off by one for an action between arrivals.
    indexed = [r for r in requests if type(r.get('index')) is int]
    if not indexed:
        result['errors'] = ['arrival_origin_missing']
        return result
    origin = epoch(indexed[0]['scheduled_utc']) - indexed[0]['index'] / cfg['rate']
    first = math.ceil((start-origin)*cfg['rate'] - 1e-6)
    last = math.ceil((end-origin)*cfg['rate'] - 1e-6)
    measured = request_metrics(requests, cfg, start, end, expected=max(0, last-first))
    for name in ('service_slo_violation_fraction', 'failure_rate', 'expected_arrivals',
                 'observed_arrivals', 'missing', 'errors'):
        result[name] = measured[name]
    result['interval'] = [start, end]
    result['semantics'] = 'scheduled UTC arrivals in [injection UTC + first milestone seconds, H end); missingness retained'
    return result


def campaign_rows(directory, cohort, allow_synthetic=False):
    directory = Path(directory).resolve()
    data = check_frozen(directory)
    if data['synthetic'] and not allow_synthetic:
        raise ValueError('synthetic evidence requires --allow-synthetic')
    if cohort == 'extension' and data['stage'] != 'extension':
        raise ValueError('extension input must be an extension campaign')
    result, excluded = [], []
    for case in data['cases']:
        if case['scenario'] not in ('s1', 's2'):
            continue
        if cohort == 'main' and (case['purpose'] != 'main' or case['mode'] not in ('P', 'M', 'A')):
            continue
        if cohort == 'supplemental' and case['id'] != 's2-b03-p-supplement01':
            continue
        attempts = case.get('attempts', [])
        if not attempts:
            excluded.append(dict(case_id=case['id'], cohort=cohort, reason='not_run'))
            continue
        attempt = attempts[0]  # Never substitute a later successful retry.
        path = (directory / attempt['path']).resolve()
        if not path.is_relative_to(directory):
            raise ValueError('attempt path escapes campaign')
        hashes = attempt.get('evidence_sha256', {})
        for name in ('judgement.json', 'metrics.json', 'requests.jsonl'):
            if name in hashes and (not (path/name).is_file() or hashlib.sha256((path/name).read_bytes()).hexdigest() != hashes[name]):
                raise ValueError('saved attempt evidence changed: ' + case['id'] + '/' + name)
        strict = read(path / 'judgement.json', {})
        metrics = read(path / 'metrics.json', {})
        if cohort == 'main' and strict.get('trial_valid') is not True:
            excluded.append(dict(case_id=case['id'], cohort=cohort, reason='strict_invalid_first_attempt', strict=strict))
            continue
        cfg = data['profile'][case['scenario']]
        result.append(dict(case_id=case['id'], scenario=case['scenario'], mode=case['mode'],
            cohort=cohort, campaign=str(directory), attempt=attempt['id'], attempts_disclosed=len(attempts),
            source_commit=data.get('git_head'), synthetic=data['synthetic'],
            post_action=post_action(path, cfg, metrics),
            service_slo_violation_fraction=metrics.get('service_slo_violation_fraction'),
            failure_rate=metrics.get('failure_rate'), conditional_p95_ms=metrics.get('scheduled_latency_p95_ms'),
            unhealthy_bins=(sum(not b['healthy'] for b in metrics['bins']) if 'bins' in metrics else None),
            incomplete_bins=(sum(not b['complete'] for b in metrics['bins']) if 'bins' in metrics else None),
            upload_goodput_Bps=metrics.get('upload_goodput_Bps'),
            strict={key: strict.get(key) for key in STRICT},
            saved_evidence_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in (path/'judgement.json', path/'metrics.json', path/'requests.jsonl') if p.is_file()}))
    return result, excluded


def analyze(extension, main=(), supplements=(), allow_synthetic=False):
    tables = {'s1': [], 's2': []}
    excluded, seen = [], set()
    inputs = [('extension', extension)] + [('main', p) for p in main] + [('supplemental', p) for p in supplements]
    for cohort, path in inputs:
        records, skipped = campaign_rows(path, cohort, allow_synthetic)
        excluded.extend(skipped)
        for row in records:
            identity = (cohort, row['case_id'])
            if identity in seen:
                raise ValueError('duplicate cohort/case; supply canonical campaigns only: ' + str(identity))
            seen.add(identity)
            tables[row['scenario']].append(row)
    return dict(notice=NOTICE, tables=tables, excluded=excluded,
                selection='original main valid first attempts; extension all first attempts; named supplement separate',
                limitations=['descriptive only; no new contrast or pooled estimate',
                             'S1 V1 has a separate SLO and is excluded from the P/M/A table',
                             'p95 conditional on successful, correct, within-deadline requests',
                             'absent action and diagnosis yield null, never an invented intervention time'])


def write_new_json(path, value, protected=()):
    path = Path(path).resolve()
    if any(path.is_relative_to(Path(p).resolve()) for p in protected):
        raise ValueError('output must be outside input campaigns')
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extension', type=Path, required=True)
    parser.add_argument('--main', type=Path, action='append', default=[])
    parser.add_argument('--supplement', type=Path, action='append', default=[])
    parser.add_argument('--allow-synthetic', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    value = analyze(args.extension, args.main, args.supplement, args.allow_synthetic)
    if args.output:
        write_new_json(args.output, value, [args.extension, *args.main, *args.supplement])
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
