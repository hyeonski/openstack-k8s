"""Whole-phase deadlines and a persistent, conservative bed uptime/cost ledger."""
from __future__ import annotations

from contextlib import contextmanager
import json
import signal
import time
from pathlib import Path

from fresh_evidence import epoch, utc, append
from lib.state import atomic_json

PHASE_LIMITS = ('environment_ensure_timeout_seconds', 'fixture_prepare_timeout_seconds',
                'cleanup_seconds', 'host_shutdown_timeout_seconds')
TIME_KEYS = ('last_case_start_utc', 'last_injection_utc', 'drain_utc', 'shutdown_start_utc', 'hard_stop_utc')


@contextmanager
def phase(name, seconds, path=None, until=None):
    """SIGALRM interrupts blocking calls as well as the sum of successive commands."""
    started = time.monotonic()
    limit = min(seconds, max(0, until-time.time())) if until is not None else seconds
    if limit <= 0:
        raise TimeoutError(name+' deadline already passed')
    old_handler = signal.getsignal(signal.SIGALRM)
    previous = signal.getitimer(signal.ITIMER_REAL)
    def timeout(*_):
        raise TimeoutError(name+' whole-phase timeout')
    signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, min(limit, previous[0]) if previous[0] else limit)
    if path: append(path, dict(phase=name, state='started', utc=utc(), limit_seconds=limit))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if previous[0]: signal.setitimer(signal.ITIMER_REAL, max(.000001, previous[0]-(time.monotonic()-started)), previous[1])
        if path: append(path, dict(phase=name, state='ended', utc=utc(), elapsed_seconds=time.monotonic()-started))


def reservation(profile, cold=False, rotate=False):
    ops = profile['operations']
    return (ops['fixture_prepare_timeout_seconds']+profile['max_case_seconds']+
            ops['cleanup_seconds']+ops['host_shutdown_timeout_seconds']+
            (ops['environment_ensure_timeout_seconds'] if cold or rotate else 0)+
            (ops['host_shutdown_timeout_seconds'] if rotate else 0))


def case_time_gate(profile, now=None, cold=False, rotate=False):
    now = time.time() if now is None else now
    ops = profile['operations']
    reserved = reservation(profile, cold, rotate)
    from fresh_host_lifetime import time_targets_only
    if time_targets_only(profile):return reserved
    if now >= epoch(ops['last_case_start_utc']) or now+reserved >= epoch(ops['hard_stop_utc']):
        raise RuntimeError('case admission rejected: case-start/hard-stop reservation')
    execution = reserved-ops['cleanup_seconds']-ops['host_shutdown_timeout_seconds']
    if now+execution >= epoch(ops['drain_utc']) or now+execution+ops['cleanup_seconds'] >= epoch(ops['shutdown_start_utc']):
        raise RuntimeError('case admission rejected: drain/shutdown reservation')
    return reserved


class BedLedger:
    """A session starts before ensure and closes only after every host is verified down.

    Includes all idle/preparation/DEV/failure time, across policy releases. During an
    unknown state elapsed time continues to accrue. Cost is a conservative planning
    estimate, explicitly distinct from the unavailable real-time Billing total.
    """
    def __init__(self, profile):
        self.profile = profile
        self.ops = profile['operations']
        self.path = Path(self.ops['bed_ledger_path'])
        self.data = json.loads(self.path.read_text()) if self.path.exists() else dict(
            environment=profile['environment'], project=profile['project'], created=utc(), sessions=[],
            cost_basis=self.ops['cost_estimate'], credit_evidence=self.ops['credit_evidence'])
        if self.data['environment'] != profile['environment'] or self.data['project'] != profile['project']:
            raise RuntimeError('bed ledger identity differs')
        if self.data['cost_basis'] != self.ops['cost_estimate']:
            raise RuntimeError('bed cost basis changed; preserve and reconcile ledger')

    def save(self):
        self.data['updated'] = utc()
        self.data['usage'] = self.usage()
        atomic_json(self.path, self.data)

    def usage(self, now=None):
        now = time.time() if now is None else now
        seconds = sum((epoch(s['stopped']) if s.get('stopped') else now)-epoch(s['started']) for s in self.data['sessions'])
        days = max(0, now-epoch(self.data['created']))/86400
        basis = self.data['cost_basis']
        return dict(bed_seconds=seconds, estimated_cost_krw=seconds/3600*basis['bed_hour_krw']+days*basis['calendar_day_krw']+basis['other_usage_reserve_krw'],
                    cost_semantics='planning upper estimate; not real-time billed amount')

    def gate(self, reserved):
        usage = self.usage()
        from fresh_host_lifetime import time_targets_only
        targets=time_targets_only(self.profile)
        if not targets and (usage['bed_seconds'] >= self.ops['bed_uptime_soft_limit_seconds'] or usage['bed_seconds']+reserved > self.ops['bed_uptime_limit_seconds']):
            raise RuntimeError('bed uptime gate rejected new work')
        estimate = usage['estimated_cost_krw']+reserved/3600*self.data['cost_basis']['bed_hour_krw']
        if estimate > self.ops['new_work_budget_krw']:
            raise RuntimeError('cost estimate gate rejected new work')
        if (time.time()+reserved if targets else epoch(self.ops['hard_stop_utc'])) >= epoch(self.ops['credit_evidence']['expires_utc']):
            raise RuntimeError('credit expires before operational completion')
        self.save()

    def begin(self):
        if any(not s.get('stopped') for s in self.data['sessions']):
            raise RuntimeError('previous bed session still active; reconcile/down explicitly')
        self.data['sessions'].append(dict(started=utc(), stopped=None))
        self.save()

    def require_active(self):
        if not self.data['sessions'] or self.data['sessions'][-1].get('stopped'):
            raise RuntimeError('bed not in uptime ledger; use explicit environment ensure')

    def stopped(self, hosts):
        if not hosts or any(h['status'] != 'TERMINATED' for h in hosts.values()):
            raise RuntimeError('cannot close uptime before all hosts are TERMINATED')
        self.require_active()
        self.data['sessions'][-1].update(stopped=utc(), final_hosts=hosts)
        self.save()
