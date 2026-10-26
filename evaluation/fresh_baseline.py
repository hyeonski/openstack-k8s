"""Fixed first-arrival baseline; index membership never depends on observed latency."""
from __future__ import annotations

import json
import math
import time

from fresh_evidence import epoch


def baseline_metrics(requests, cfg, before=None):
    from fresh_analysis import quantile
    count = int(60 * cfg['rate'])
    per_bin = int(20 * cfg['rate'])
    errors = []
    selected = [r for r in requests if type(r.get('index')) is int and 0 <= r['index'] < count]
    selected.sort(key=lambda r: r['index'])
    if [r['index'] for r in selected] != list(range(count)):
        errors.append('baseline_first_arrivals_incomplete_or_duplicate')
    if len({r.get('request_id') for r in selected}) != len(selected):
        errors.append('baseline_request_id_duplicate')
    clocks = {r.get('clock_id') for r in selected}
    if len(clocks) != 1 or not all(isinstance(c, str) and c for c in clocks):
        errors.append('baseline_clock_origin_invalid')
    zero = next((r for r in selected if r['index'] == 0), None)
    evaluated = []
    for r in selected:
        try:
            scheduled = epoch(r['scheduled_utc'])
            sm = r['scheduled_monotonic']
            if type(sm) not in (int, float) or not math.isfinite(sm):
                raise ValueError('scheduled monotonic missing/nonfinite')
            if zero is None or abs(scheduled - epoch(zero['scheduled_utc']) - r['index']/cfg['rate']) > .001 or abs(sm-zero['scheduled_monotonic']-r['index']/cfg['rate']) > .001:
                errors.append('baseline_arrival_schedule_mismatch')
            start, finish = epoch(r['started_utc']), epoch(r['completed_utc'])
            bm, fm = r['started_monotonic'], r['completed_monotonic']
            if not all(type(v) in (int, float) and math.isfinite(v) for v in (bm, fm)):
                raise ValueError('request monotonic missing/nonfinite')
            if start < scheduled-.001 or finish < start or bm < sm-.001 or fm < bm:
                errors.append('baseline_time_reversed')
            if abs((start-scheduled)-(bm-sm)) > .1 or abs((finish-start)-(fm-bm)) > .1 or r.get('completed_clock_id', r['clock_id']) != r['clock_id']:
                errors.append('baseline_clock_disagreement')
            if r.get('deadline_seconds') != cfg['deadline_seconds']:
                errors.append('baseline_deadline_mismatch')
            if before is not None and (scheduled >= before or finish > before):
                errors.append('baseline_not_pre_injection')
            # UTC records have microsecond precision; remove binary epoch cancellation
            # so exactly 100.000 ms stays on the registered inclusive V1 boundary.
            latency = round(finish-scheduled,6)*1000
            good = bool(r.get('ok') and r.get('correct') and not r.get('generator_rejection') and 0 <= latency <= cfg['deadline_seconds']*1000)
        except (KeyError, TypeError, ValueError, AttributeError):
            errors.append('baseline_request_incomplete')
            latency, good = None, False
        evaluated.append((r['index'], good, latency))
    bins = []
    for n in range(3):
        values = [(good, latency) for index, good, latency in evaluated if n*per_bin <= index < (n+1)*per_bin]
        indexes = [index for index, _, _ in evaluated if n*per_bin <= index < (n+1)*per_bin]
        complete = indexes == list(range(n*per_bin, (n+1)*per_bin))
        bad = sum(not good or latency > cfg['slo_ms'] for good, latency in values)
        p95 = quantile([latency for good, latency in values if good])
        healthy = complete and bad <= math.floor(per_bin*cfg['bin_max_bad_fraction']) and p95 is not None and p95 <= cfg['slo_ms']
        bins.append(dict(index_start=n*per_bin, index_end=(n+1)*per_bin, samples=len(values), complete=complete, bad=bad, successful_p95_ms=p95, healthy=healthy))
    if not all(b['healthy'] for b in bins):
        errors.append('baseline_unhealthy')
    return dict(passed=not errors, errors=sorted(set(errors)), bins=bins,
                expected_arrivals=count, observed_arrivals=len(selected),
                selection='registered indexes 0 through 60*rate-1; three 20*rate bins')


def baseline_gate(ev, cfg, collect, *, wait=True, source, policy_window=None):
    """Wait only for this fixed window, never seek a later successful window."""
    from lib.state import atomic_json
    deadline = time.monotonic()+65
    count = int(60*cfg['rate'])
    requests = []
    while True:
        requests = collect()
        selected = [r for r in requests if type(r.get('index')) is int and 0 <= r['index'] < count]
        zero = next((r for r in selected if r['index'] == 0), None)
        if zero:
            # Final arrival's five-second completion grace is an absolute boundary.
            deadline = min(deadline, time.monotonic()+max(0, epoch(zero['scheduled_utc'])+(count-1)/cfg['rate']+5-time.time()))
        if not wait or len({r['index'] for r in selected}) == count or time.monotonic() >= deadline:
            break
        time.sleep(min(.5, max(0, deadline-time.monotonic())))
    path = ev.directory/'baseline-gate-requests.jsonl'
    path.write_text(''.join(json.dumps(r)+'\n' for r in requests if type(r.get('index')) is int and 0 <= r['index'] < count))
    result = baseline_metrics(selected, cfg, before=time.time())
    atomic_json(ev.directory/'baseline-gate.json', dict(**result, source=source, policy_window=policy_window))
    ev.event('baseline_checked', passed=result['passed'], source=source)
    if not result['passed']:
        raise RuntimeError('fixed pre-injection baseline rejected: '+', '.join(result['errors']))
    return result
