"""Effective host deadlines; absence of a cloud timer needs an explicit final bound."""
import datetime as dt
import math
import os


def epoch(value):
    if not isinstance(value, str):
        raise RuntimeError('host/final deadline timestamp unavailable')
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise RuntimeError('host deadline must have a timezone')
    return parsed.timestamp()


def host_deadline(host, *, hard_stop=None, allow_unlimited=False):
    scheduling = host.get('scheduling', {})
    raw = host.get('max_run_seconds', scheduling.get('maxRunDuration', {}).get('seconds'))
    try:
        seconds = 0 if raw is None else int(raw)
    except (TypeError, ValueError):
        raise RuntimeError('invalid host runtime limit')
    if isinstance(raw, bool) or seconds < 0:
        raise RuntimeError('invalid host runtime limit')
    bounds = []
    if seconds:
        bounds.append(epoch(host.get('last_start', host.get('lastStartTimestamp')))+seconds)
    termination = host.get('termination_time', scheduling.get('terminationTime'))
    if termination:
        bounds.append(epoch(termination))
    if not bounds and not (allow_unlimited and hard_stop):
        raise RuntimeError('automatic STOP deadline unknown; explicit bounded no-timer policy required')
    if hard_stop:
        bounds.append(epoch(hard_stop))
    if not bounds or not all(math.isfinite(v) for v in bounds):
        raise RuntimeError('finite operational host deadline required')
    return min(bounds)


def operational_host_deadline(host):
    return host_deadline(host, hard_stop=os.environ.get('FRESH_OPERATIONAL_HARD_STOP_UTC'),
                         allow_unlimited=os.environ.get('FRESH_HOST_RUNTIME_LIMIT')=='disabled')
