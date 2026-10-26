"""Open-loop S1 HTTP sampler. All timestamps and latencies originate in this Pod."""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import http.client
import os
import uuid
import time
import urllib.error
import urllib.request


class TimedConnection(http.client.HTTPConnection):
    def connect(self):
        started = time.monotonic()
        super().connect()
        self.dns_tcp_ms = (time.monotonic() - started) * 1000


class TimedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, timings):
        super().__init__()
        self.timings = timings

    def http_open(self, req):
        def connection(*args, **kwargs):
            conn = TimedConnection(*args, **kwargs)
            self.timings['connection'] = conn
            return conn
        return self.do_open(connection, req)


def request(url, phase, index, timeout):
    at = dt.datetime.now(dt.timezone.utc).isoformat()
    started = time.monotonic()
    result = {'kind': 'request', 'phase': phase, 'index': index, 'time': at,
              'ok': False, 'status': None, 'request_id': str(index),
              'scheduled_utc': at, 'started_utc': at,
              'started_monotonic': started, 'clock_id': 'assigned-by-generator',
              'deadline_seconds': timeout, 'generator_rejection': False}
    try:
        timings = {}
        opener = urllib.request.build_opener(TimedHTTPHandler(timings))
        with opener.open(url, timeout=timeout) as response:
            result['response_headers_ms'] = (time.monotonic() - started) * 1000
            conn = timings.get('connection')
            result['dns_tcp_ms'] = getattr(conn, 'dns_tcp_ms', None)
            result['server_timing'] = response.headers.get('Server-Timing')
            body = json.loads(response.read(512))
            result['status'] = response.status
            result['ok'] = response.status == 200 and isinstance(body.get('digest'), str)
            if not result['ok']:
                result['error'] = 'unexpected response'
    except urllib.error.HTTPError as exc:
        result['status'] = exc.code
        result['error'] = 'HTTPError'
    except (OSError, ValueError, TimeoutError) as exc:
        result['error'] = type(exc).__name__
    result['latency_ms'] = round((time.monotonic() - started) * 1000, 3)
    result.update(completed_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                  completed_monotonic=time.monotonic(), correct=result['ok'])
    return result


def run(url, rate, warmup_seconds, measure_seconds, timeout, max_inflight):
    if rate <= 0 or warmup_seconds < 0 or measure_seconds <= 0 or max_inflight < 1:
        raise ValueError('invalid load parameters')
    started = time.monotonic()
    wall = time.time()
    clock_id = 's1:' + uuid.uuid4().hex
    count = int((warmup_seconds + measure_seconds) * rate)
    pending = set()
    def scheduled_request(phase, index, scheduled):
        result = request(url, phase, index, timeout)
        result.update(scheduled_utc=scheduled, scheduled_monotonic=started+index/rate, clock_id=clock_id)
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_inflight) as pool:
        for index in range(count):
            deadline = started + index / rate
            if deadline > time.monotonic():
                time.sleep(deadline - time.monotonic())
            scheduled = dt.datetime.fromtimestamp(wall + index / rate, dt.timezone.utc).isoformat()
            phase = 'warmup' if index / rate < warmup_seconds else 'measure'
            finished = {task for task in pending if task.done()}
            for task in finished:
                print(json.dumps(task.result(), separators=(',', ':')), flush=True)
            pending.difference_update(finished)
            # A full queue would make this a closed-loop test. Preserve the
            # missed arrival as a failure instead of silently lowering demand.
            if len(pending) >= max_inflight:
                print(json.dumps({'kind': 'request', 'phase': phase, 'index': index,
                                  'time': dt.datetime.now(dt.timezone.utc).isoformat(),
                                  'ok': False, 'status': None, 'latency_ms': 0,
                                  'error': 'inflight_limit', 'request_id': str(index),
                                  'scheduled_utc': scheduled, 'scheduled_monotonic': started+index/rate, 'started_utc': None, 'completed_utc': None,
                                  'deadline_seconds': timeout, 'correct': False,
                                  'generator_rejection': True, 'clock_id': clock_id}), flush=True)
            else:
                pending.add(pool.submit(scheduled_request, phase, index, scheduled))
        for task in concurrent.futures.as_completed(pending):
            print(json.dumps(task.result(), separators=(',', ':')), flush=True)


if __name__ == '__main__':
    run(os.environ['S1_URL'], float(os.environ['S1_RATE']),
        int(os.environ['S1_WARMUP_SECONDS']), int(os.environ['S1_MEASURE_SECONDS']),
        float(os.environ['S1_TIMEOUT_SECONDS']), int(os.environ['S1_MAX_INFLIGHT']))
