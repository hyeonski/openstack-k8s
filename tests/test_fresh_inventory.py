import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/d) for d in ('evaluation','scripts')]
from fresh_read_budget import read_with_budget,phase_deadline
from fresh_worker_quiescence import wait_worker_quiescent


class Clock:
    def __init__(self):self.value=0
    def __call__(self):return self.value
    def sleep(self,seconds):self.value+=seconds


class InventoryTests(unittest.TestCase):
    def test_real_dispatch_allows_46_second_collection_without_raising_child_cap(self):
        from workload_state import command
        clock=Clock();caps=[]
        with tempfile.TemporaryDirectory() as directory:
            ctx=Path(directory)/'context.json';ctx.write_text(json.dumps(dict(version=1,evidence=directory)))
            def once(args,**kw):caps.append(kw['timeout']);clock.sleep(46);return '{}'
            def budget(*args,**kw):return read_with_budget(*args,**kw,clock=clock,sleep=clock.sleep)
            with patch.dict(os.environ,FRESH_READ_CONTEXT=str(ctx)),patch('workload_state.command_once',side_effect=once),patch('fresh_read_budget.read_with_budget',side_effect=budget):
                self.assertEqual(command([ROOT/'scripts/workload-inventory.sh'],timeout=210),'{}')
            self.assertEqual(caps,[90]);self.assertEqual(clock.value,46)

    def test_compound_retry_identity_and_phase_keep_one_total_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            clock=Clock();caps=[];identities=[]
            def invoke(left):
                caps.append(left());clock.sleep(20)
                if len(caps)==1:raise ConnectionError('broken pipe')
                return 'complete'
            result=read_with_budget(invoke,timeout=210,compound=True,
                identity=lambda left:identities.append(left()),label='inventory',evidence=directory,clock=clock,sleep=clock.sleep)
            self.assertEqual(result,'complete');self.assertEqual(caps,[90,60]);self.assertEqual(identities,[20,20]);self.assertEqual(clock.value,50)
            clock=Clock()
            with phase_deadline(12),self.assertRaises(TimeoutError):
                read_with_budget(lambda left:clock.sleep(left()+1),timeout=90,compound=True,
                    identity=lambda _:None,label='phase',evidence=directory,clock=clock,sleep=clock.sleep)

    def test_remote_inventory_limits_each_cli_and_keeps_complete_output(self):
        text=(ROOT/'scripts/workload-inventory.sh').read_text()
        source=text.split("python3 - \"$1\" <<'PY'\n",1)[1].split('\nPY\n',1)[0]
        calls=[];clock=Clock()
        def query(args,timeout,**kw):
            calls.append((args,timeout));clock.sleep(3)
            if args[3:5]==['port','list']:return json.dumps([{'ID':str(i)} for i in range(6)])
            if args[3:5]==['port','show']:return '{"id":"port"}'
            return '[]'
        stream=io.StringIO()
        with patch.object(sys,'argv',['inventory','fresh']),patch('subprocess.check_output',side_effect=query),patch('time.monotonic',clock),contextlib.redirect_stdout(stream):
            exec(compile(source,'remote-inventory','exec'),{})
        result=json.loads(stream.getvalue());self.assertEqual(len(result['ports']),6)
        self.assertEqual(len(calls),15);self.assertTrue(all(t==20 for _,t in calls));self.assertEqual(clock.value,45)

    def test_cleanup_waits_for_supervisor_lock_and_refuses_live_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            lock=str(Path(directory)/'worker-operation.lock')
            code='import fcntl,sys,time; f=open(sys.argv[1],"a+"); fcntl.flock(f,fcntl.LOCK_EX); print("locked",flush=True); time.sleep(.5)'
            with subprocess.Popen([sys.executable,'-c',code,lock],stdout=subprocess.PIPE,text=True) as child:
                self.assertEqual(child.stdout.readline().strip(),'locked')
                with self.assertRaises(TimeoutError):wait_worker_quiescent(directory,directory,timeout=.05)
                before=time.monotonic();wait_worker_quiescent(directory,directory,timeout=2)
                self.assertGreater(time.monotonic()-before,.2);child.wait(timeout=2)
            self.assertTrue(json.loads((Path(directory)/'worker-quiescence.jsonl').read_text())['lock_released'])


if __name__=='__main__':unittest.main()
