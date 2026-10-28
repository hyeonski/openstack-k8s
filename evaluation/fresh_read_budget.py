"""One deadline for an explicitly registered operational read and its identity.

No shell inference, service-probe retry, mutation replay, or nested retries.
The enclosing phase must supply its remaining original budget.
"""
from contextvars import ContextVar
from contextlib import contextmanager
from pathlib import Path
import math
import re
import subprocess
import time

from fresh_evidence import append, utc

_ACTIVE = ContextVar('fresh_read_budget', default=None)
BACKOFF = (10.0, 25.0)
COMMAND_CAP = 20.0
OPERATION_CAP = 90.0
# A scenario has one observational phase, shared by concurrent snapshot threads.
_PHASE_END = None
_HORIZON_END = None

def set_horizon_deadline(end):
    global _HORIZON_END
    _HORIZON_END=end

def set_phase_deadline(end):
    global _PHASE_END
    _PHASE_END=end

@contextmanager
def phase_deadline(end):
    prior=_PHASE_END
    set_phase_deadline(end if prior is None else min(prior,end))
    try:yield
    finally:set_phase_deadline(prior)



def transient_error(error):
    text = str(error).lower()
    if any(x in text for x in ('forbidden', 'unauthorized', 'permission denied',
            'certificate', 'notfound', 'not found', 'invalid argument', 'invalid choice',
            '403:', '401:', 'identity changed', 'uid changed')):
        return False
    return (bool(re.search(r'the connection to the server [^\n]+ was refused', text)) or
        isinstance(error, (subprocess.TimeoutExpired, ConnectionError))) or any(
        x in text for x in ('4047', 'tls handshake timeout', 'connection reset',
        'connection refused', 'broken pipe', 'unexpected eof', 'i/o timeout',
        'context deadline exceeded', 'tls eof', 'unable to connect to the server',
        'error while connecting to', 'failed to receive data', 'connection timed out',
        'connection closed by remote host'))


def read_with_budget(invoke, *, timeout, identity, label, evidence,
                     reconnect=None, attempts=3, clock=time.monotonic,
                     sleep=time.sleep, log_name='transport-read-attempts.jsonl', compound=False):
    """Callbacks accept a remaining() function capped to 20s per command.

    Reentrant identity reads execute once, on the SAME deadline. Callbacks must
    honor the supplied timeout; an overrun is rejected even after success.
    """
    if not math.isfinite(timeout) or timeout <= 0 or attempts not in (1, 2, 3):
        raise ValueError('invalid operational read budget')
    parent = _ACTIVE.get()
    if parent is not None:
        if compound:
            raise ValueError('compound read cannot reset an enclosing command deadline')
        result = invoke(parent)
        parent()
        return result
    end = clock() + min(timeout, OPERATION_CAP)
    if _PHASE_END is not None:end=min(end,_PHASE_END)
    def remaining():
        left = end-clock()
        if left <= 0:
            raise TimeoutError('operational read cumulative deadline exhausted: '+label)
        return min(COMMAND_CAP, left)
    def operation_remaining():
        # Only a registered collector that bounds EACH child command may use
        # the operation budget. Identity and nested reads retain their 20s cap.
        remaining()
        return end-clock()
    token = _ACTIVE.set(remaining)
    try:
        for number in range(1, attempts+1):
            began = clock()
            try:
                result = invoke(operation_remaining if compound else remaining)
                remaining()
                if number > 1: identity(remaining)
                remaining()
            except Exception as error:
                append(Path(evidence)/log_name, dict(utc=utc(), label=label,
                    attempt=number, elapsed_seconds=clock()-began,
                    error=type(error).__name__+': '+str(error),
                    remaining_seconds=max(0,end-clock()), observation_filled=False))
                if number == attempts or not transient_error(error):
                    raise
                # Keep the original successful read contract. A read already in
                # progress may finish after H as before; a retry must fit in H.
                # Baseline's hard phase deadline still applies to every attempt.
                if _HORIZON_END is not None:
                    end=min(end,_HORIZON_END)
                    remaining()
                # Validate identity before sleeping, so changed targets fail now.
                # An unavailable identity is not evidence that ownership is intact.
                if reconnect: reconnect(remaining)
                identity(remaining)
                remaining()
                sleep(min(BACKOFF[number-1], max(0,end-clock())))
                remaining()
            else:
                append(Path(evidence)/log_name, dict(utc=utc(), label=label,
                    attempt=number, elapsed_seconds=clock()-began, captured=True,
                    kind='transport_retry' if number>1 else 'transport_read',
                    remaining_seconds=max(0,end-clock()), observation_filled=False))
                return result
    finally:
        _ACTIVE.reset(token)
