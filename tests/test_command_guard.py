"""Real process regressions for the parent-SIGKILL lock boundary."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from worker_control import WorkerControl
from workload_state import command


class CommandGuardTests(unittest.TestCase):
    def test_parent_sigkill_stops_command_before_recovery_can_mutate(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            runner = '''
import sys
from pathlib import Path
from types import SimpleNamespace
from worker_control import WorkerControl
from workload_state import command
with WorkerControl(SimpleNamespace(state=Path(sys.argv[1]))):
    command([sys.executable, '-c', sys.argv[2], sys.argv[1]], timeout=15)
'''
            child = '''
import os, sys, time
from pathlib import Path
p = Path(sys.argv[1])
(p/'ready').write_text(str(os.getpid()))
while not (p/'release').exists(): time.sleep(.01)
(p/'mutation').write_text('late')
'''
            proc = subprocess.Popen([sys.executable, '-c', runner, temporary, child],
                                    env={**os.environ, 'PYTHONPATH': str(ROOT / 'scripts')},
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 5
                while not (folder / 'ready').exists():
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.01)
                proc.kill()
                proc.wait(timeout=3)
                deadline = time.monotonic() + 3
                while True:
                    try:
                        with WorkerControl(SimpleNamespace(state=folder)):
                            (folder / 'release').touch()
                            time.sleep(.1)
                            self.assertFalse((folder / 'mutation').exists())
                            break
                    except BlockingIOError:
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(.01)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

    def test_supervisor_deadline_and_io_preserve_lock_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            with WorkerControl(SimpleNamespace(state=Path(temporary))):
                self.assertEqual(command([sys.executable, '-c', 'import sys; print(sys.stdin.read())'],
                                         data='input', timeout=3), 'input\n')
                with self.assertRaises(subprocess.TimeoutExpired):
                    command([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=.15)
            with WorkerControl(SimpleNamespace(state=Path(temporary))):
                pass

    def test_sigterm_reaps_guarded_command(self):
        # Same command path as lifecycle signal handling, with a real inherited lock.
        with tempfile.TemporaryDirectory() as temporary:
            code = '''
import sys
from pathlib import Path
from types import SimpleNamespace
from worker_control import WorkerControl
from workload_state import command
from run_lifecycle import install_signal_handlers, Cancelled
install_signal_handlers()
with WorkerControl(SimpleNamespace(state=Path(sys.argv[1]))):
    print('ready', flush=True)
    try: command([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=20)
    except Cancelled: print('cancelled', flush=True)
'''
            with subprocess.Popen([sys.executable, '-c', code, temporary],
                                  env={**os.environ, 'PYTHONPATH': str(ROOT / 'scripts')},
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
                self.assertEqual(proc.stdout.readline().strip(), 'ready')
                time.sleep(.1)
                proc.send_signal(signal.SIGTERM)
                out, err = proc.communicate(timeout=4)
                self.assertEqual(proc.returncode, 0, err)
                self.assertIn('cancelled', out)
            with WorkerControl(SimpleNamespace(state=Path(temporary))):
                pass
