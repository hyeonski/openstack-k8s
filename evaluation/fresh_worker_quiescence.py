"""Wait for interrupted worker supervisors to release ownership before cleanup."""
import fcntl
from pathlib import Path
import time

from fresh_evidence import append, utc


def wait_worker_quiescent(state, evidence, *, timeout=30):
    started=time.monotonic()
    with (Path(state)/'worker-operation.lock').open('a+') as lock:
        while True:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                left=timeout-(time.monotonic()-started)
                if left<=0:
                    raise TimeoutError('worker operation still owns lock; cleanup mutation refused')
                time.sleep(min(.1,left))
        fcntl.flock(lock,fcntl.LOCK_UN)
    append(Path(evidence)/'worker-quiescence.jsonl',dict(utc=utc(),
        elapsed_seconds=time.monotonic()-started,lock_released=True))
