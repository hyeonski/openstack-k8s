"""Bounded local-transport repair for identified Kubernetes reads only.

No command mutation, synthetic observation, or experiment action is retried.
The caller's original deadline includes reconnect, identity reads and backoff.
"""
from contextlib import contextmanager
import fcntl
import math
from pathlib import Path
import re
import socket
import time

from fresh_evidence import append, utc


def transient_transport_error(exc):
    text = str(exc).lower()
    if any(word in text for word in ('forbidden', 'unauthorized', 'notfound',
                                     'not found', 'permission denied', 'certificate')):
        return False
    return any(word in text for word in ('connection reset', 'connection refused',
        'broken pipe', 'unexpected eof', 'unable to connect to the server',
        'error while connecting to', 'failed to receive data from'))


def read_command(args, data=None):
    if data is not None:
        return False
    # Flags may precede the verb. Do not infer that exec or a rollout mutation
    # is read-only merely because some later argument contains "get".
    values = list(map(str, args))
    index = 0
    takes_value = {'-n', '--namespace', '--context', '--kubeconfig',
                   '--request-timeout', '--server', '-s'}
    while index < len(values) and values[index].startswith('-'):
        flag = values[index]
        index += 2 if flag in takes_value else 1
    if index >= len(values):
        return False
    verb = values[index]
    return verb in ('get', 'wait', 'logs') or (
        verb == 'rollout' and values[index + 1:index + 2] == ['status'])


def deadline_args(args, remaining):
    result = []
    for value in map(str, args):
        if value.startswith(('--timeout=', '--request-timeout=')):
            key, original = value.split('=', 1)
            match = re.fullmatch(r'(\d+(?:\.\d+)?)(ms|s|m|h)', original)
            if not match:
                raise ValueError('unrecognised Kubernetes timeout: ' + value)
            seconds = float(match[1]) * {'ms': .001, 's': 1, 'm': 60, 'h': 3600}[match[2]]
            # Never increase an existing request timeout or reset wait's timeout.
            value = key + '=' + str(max(.001, min(seconds, remaining))) + 's'
        result.append(value)
    return result


def retry_read(invoke, args, *, timeout, identity, reconnect, evidence,
               data=None, attempts=3, clock=time.monotonic, sleep=time.sleep):
    """invoke(args, data=..., timeout=...) must execute exactly one command."""
    if not read_command(args, data):
        return invoke(args, data=data, timeout=timeout)
    if not math.isfinite(timeout) or timeout <= 0:
        raise TimeoutError('read deadline exhausted before command')
    end = clock() + timeout

    def remaining():
        value = end - clock()
        if value <= 0:
            raise TimeoutError('read cumulative deadline exhausted')
        return value

    for number in range(1, attempts + 1):
        remaining()
        try:
            if number > 1:
                # Reconnect is serialised with the preparation/cleanup watcher.
                reconnect(remaining)
                identity(remaining)
            result = invoke(deadline_args(args, remaining()), data=data, timeout=remaining())
            if number > 1:
                identity(remaining)
            remaining()
        except Exception as exc:
            append(Path(evidence) / 'transport-read-attempts.jsonl', dict(
                utc=utc(), command=list(map(str, args)), attempt=number,
                error=type(exc).__name__ + ': ' + str(exc),
                remaining_seconds=max(0, end - clock()), observation_filled=False))
            if number == attempts or not transient_transport_error(exc):
                raise
            pause = min(float(number), remaining())
            sleep(pause)
            remaining()
        else:
            append(Path(evidence) / 'transport-read-attempts.jsonl', dict(
                utc=utc(), command=list(map(str, args)), attempt=number,
                captured=True, remaining_seconds=max(0, end - clock()),
                observation_filled=False))
            return result


def listener_reachable(port):
    try:
        with socket.create_connection(('127.0.0.1', int(port)), timeout=1):
            return True
    except OSError:
        return False


@contextmanager
def transport_lock(state, remaining, sleep=time.sleep):
    """One reconnect owner, also used by the existing TransportWatch."""
    with (Path(state) / 'workload-api-reconnect.lock').open('a+') as lock:
        while True:
            remaining()
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                sleep(min(.1, remaining()))
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
