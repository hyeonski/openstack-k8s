#!/usr/bin/env python3
"""Hold an inherited operation lock until a bounded command has stopped.

The parent-death pipe also works on macOS, where Linux PDEATHSIG is unavailable.
Only this supervisor inherits the lock; long-lived API tunnels must not hold it.
"""
import argparse
import os
import selectors
import signal
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent-fd', type=int, required=True)
    parser.add_argument('--lock-fd', type=int, required=True)
    parser.add_argument('--timeout', type=float, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    os.fstat(args.lock_fd)
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    argv = args.command[1:] if args.command[:1] == ['--'] else args.command
    deadline = time.monotonic() + args.timeout
    with selectors.DefaultSelector() as selector:
        selector.register(args.parent_fd, selectors.EVENT_READ)
        with subprocess.Popen(argv, start_new_session=True) as child:
            while child.poll() is None:
                expired = time.monotonic() >= deadline
                orphan = bool(selector.select(timeout=min(.05, max(0, deadline - time.monotonic()))))
                if stopped or expired or orphan:
                    # Keep the lock while killing/reaping the entire command group.
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    child.wait()
                    return 124 if expired else 125
            return child.returncode if child.returncode >= 0 else 128 - child.returncode


if __name__ == '__main__':
    raise SystemExit(main())
