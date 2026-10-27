"""Durable evidence hooks, process-local clocks and bounded open-loop sampling."""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import math
import os
from pathlib import Path
import threading
import time
import uuid


def utc(epoch=None):
    return dt.datetime.fromtimestamp(time.time() if epoch is None else epoch, dt.timezone.utc).isoformat()


def epoch(value):
    if isinstance(value, (float, int)):
        if not math.isfinite(value):raise ValueError('timestamp must be finite')
        return float(value)
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('UTC timestamp requires timezone')
    return parsed.timestamp()


def append(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def wait_for_arrival(scheduled_wall, scheduled_monotonic):
    """Keep both registered clocks; a wall-clock slew must not send early."""
    while True:
        remaining = max(scheduled_wall-time.time(), scheduled_monotonic-time.monotonic())
        if remaining <= 0:
            return
        # Recheck instead of assuming sleep or either clock stayed exact.
        time.sleep(min(remaining, 1.0))


class Evidence:
    def __init__(self, directory, observer='runner'):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.clock_id = f'{observer}:{os.getpid()}:{uuid.uuid4().hex}'
        self.observer = observer

    def event(self, kind, target=None, actor='observer', **fields):
        row = dict(event_id=uuid.uuid4().hex, kind=kind, utc=utc(),
                   monotonic_ns=time.monotonic_ns(), clock_id=self.clock_id,
                   observer=self.observer, target_uid=target, actor=actor, **fields)
        append(self.directory / 'events.jsonl', row)
        return row

    def state(self, phase):
        return self.event('phase', phase=phase)


class OpenLoopProbe:
    """Arrival index defines the denominator, including rejection and unfinished work."""
    def __init__(self, path, probe, rate, seconds, deadline, max_inflight=16):
        self.path, self.probe = Path(path), probe
        self.rate, self.seconds, self.deadline = rate, seconds, deadline
        self.max_inflight = max_inflight
        self.clock_id = 'probe:' + uuid.uuid4().hex
        self.error = None
        self.until = None
        self.until_utc = None
        self.rows = []
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def outside_horizon(self, scheduled_wall, scheduled_monotonic):
        return self.until is not None and scheduled_monotonic >= self.until and (self.until_utc is None or scheduled_wall >= self.until_utc)

    def loop(self):
        try:
            anchor, wall = time.monotonic(), time.time()
            pending = {}
            active_rows = {}
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_inflight)
            def one(index, scheduled):
                wait_for_arrival(scheduled, anchor+index/self.rate)
                begin, mono = time.time(), time.monotonic()
                row = dict(request_id=str(index), index=index, scheduled_utc=utc(scheduled),
                           scheduled_monotonic=anchor+index/self.rate, started_utc=utc(begin), clock_id=self.clock_id, started_monotonic=mono,
                           deadline_seconds=self.deadline, ok=False, correct=False, bytes=0, generator_rejection=False)
                active_rows[index] = row
                try:
                    result = self.probe()
                    protected={'request_id','index','scheduled_monotonic','scheduled_utc','started_utc','started_monotonic','clock_id','deadline_seconds','generator_rejection','completed_utc','completed_monotonic'}
                    row.update({k:v for k,v in result.items() if k not in protected})
                    row['correct'] = result.get('correct', result['ok'])
                except Exception as exc:
                    row['error'] = f'{type(exc).__name__}: {exc}'
                row.update(completed_utc=utc(), completed_monotonic=time.monotonic())
                return row
            def emit(row):
                append(self.path, row)
                self.rows.append(row)
            for i in range(int(self.seconds * self.rate)):
                scheduled = wall + i / self.rate
                if self.outside_horizon(scheduled, anchor+i/self.rate):
                    break
                wait_for_arrival(scheduled, anchor+i/self.rate)
                if self.outside_horizon(scheduled, anchor+i/self.rate):
                    break
                for future in [f for f in pending if f.done()]:
                    emit(future.result()); del pending[future]
                if len(pending) >= self.max_inflight:
                    emit(dict(request_id=str(i), index=i, scheduled_utc=utc(scheduled), started_utc=None,
                              scheduled_monotonic=anchor+i/self.rate, completed_utc=None, deadline_seconds=self.deadline, ok=False, correct=False,
                              bytes=0, generator_rejection=True, error='inflight_limit', clock_id=self.clock_id))
                else:
                    pending[pool.submit(one, i, scheduled)] = (i, scheduled)
            done, unfinished = concurrent.futures.wait(pending, timeout=self.deadline)
            for future in done:
                emit(future.result())
            for future in unfinished:
                i, scheduled = pending[future]
                incomplete=dict(active_rows.get(i,dict(request_id=str(i),index=i,scheduled_utc=utc(scheduled),scheduled_monotonic=anchor+i/self.rate,started_utc=None,deadline_seconds=self.deadline,clock_id=self.clock_id)))
                incomplete.update(completed_utc=None,ok=False,correct=False,bytes=0,generator_rejection=False,error='unfinished')
                emit(incomplete)
            pool.shutdown(wait=False, cancel_futures=True)
        except BaseException as exc:
            self.error = f'{type(exc).__name__}: {exc}'

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exception):
        if exception and exception[0] is not None:
            self.until=time.monotonic();self.until_utc=time.time()
        self.thread.join(timeout=self.seconds + self.deadline + 10)
        if self.thread.is_alive() or self.error:
            raise RuntimeError('continuous probe incomplete: ' + str(self.error))


def elapsed(a, b):
    if a['clock_id'] != b['clock_id']:
        raise ValueError('cannot subtract monotonic clocks from different processes')
    delta = (b['monotonic_ns'] - a['monotonic_ns']) / 1e9
    if delta < 0:
        raise ValueError('monotonic time reversed')
    return delta


def clock_check(ev, phase, remote_utc, max_offset_seconds, source):
    """Bound remote UTC offset by a local send/receive interval; never mix monotonic origins."""
    before=time.time();begin=time.monotonic()
    remote=epoch(remote_utc())
    after=time.time();finish=time.monotonic()
    row={'phase':phase,'utc':utc(after),'clock_id':ev.clock_id,'monotonic_ns':time.monotonic_ns(),
         'source':source,'remote_utc':utc(remote),'round_trip_seconds':finish-begin,
         'offset_lower_seconds':remote-after,'offset_upper_seconds':remote-before}
    append(ev.directory/'clock-checks.jsonl',row)
    if after<before or abs((after-before)-(finish-begin))>.1 or max(abs(row['offset_lower_seconds']),abs(row['offset_upper_seconds']))>max_offset_seconds:
        raise RuntimeError('UTC offset/uncertainty exceeds registered clock bound')
    return row
