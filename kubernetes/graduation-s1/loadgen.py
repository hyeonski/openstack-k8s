"""Open-loop S1 HTTP sampler. All timestamps and latencies originate in this Pod."""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request


def request(url, phase, index, timeout):
    at = dt.datetime.now(dt.timezone.utc).isoformat()
    started = time.monotonic()
    result = {'kind': 'request', 'phase': phase, 'index': index, 'time': at,
              'ok': False, 'status': None}
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
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
    return result


def run(url, rate, warmup_seconds, measure_seconds, timeout, max_inflight):
    if rate <= 0 or warmup_seconds < 0 or measure_seconds <= 0 or max_inflight < 1:
        raise ValueError('invalid load parameters')
    started = time.monotonic()
    count = int((warmup_seconds + measure_seconds) * rate)
    pending = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_inflight) as pool:
        for index in range(count):
            deadline = started + index / rate
            if deadline > time.monotonic():
                time.sleep(deadline - time.monotonic())
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
                                  'error': 'inflight_limit'}), flush=True)
            else:
                pending.add(pool.submit(request, url, phase, index, timeout))
        for task in concurrent.futures.as_completed(pending):
            print(json.dumps(task.result(), separators=(',', ':')), flush=True)


if __name__ == '__main__':
    run(os.environ['S1_URL'], float(os.environ['S1_RATE']),
        int(os.environ['S1_WARMUP_SECONDS']), int(os.environ['S1_MEASURE_SECONDS']),
        float(os.environ['S1_TIMEOUT_SECONDS']), int(os.environ['S1_MAX_INFLIGHT']))
