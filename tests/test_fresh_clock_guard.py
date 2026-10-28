import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'evaluation'))
from fresh_clock_guard import RestoreService

class Clock:
    def __init__(self):self.t=1000
    def __call__(self):return self.t
class Mac:
    def __init__(self,original=True):self.ntp=original;self.calls=[];self.bootid='boot-1';self.proc='501 start-1';self.killed=[]
    def boot(self):return self.bootid
    def process(self,pid):return self.proc
    def setting(self):return self.ntp
    def server(self):return 'original.server'
    def set(self,value):self.calls.append(value);self.ntp=value
    def stop(self,pid):self.killed.append(pid)

class ClockGuardTests(unittest.TestCase):
    def fixture(self,root,original=True):
        mac=Mac(original);clock=Clock();wall=Clock();s=RestoreService(root,501,mac,clock,wall)
        req=dict(op='arm',token='a'*32,pid=123,process=mac.proc,boot=mac.boot(),seconds=100,created_epoch=wall())
        return s,mac,clock,wall,req
    def test_restores_original_on_and_off(self):
        for original in (True,False):
            with tempfile.TemporaryDirectory() as root:
                s,m,c,w,r=self.fixture(root,original);s.request(r);self.assertFalse(m.ntp)
                s.request(dict(op='release',token=r['token']))
                self.assertEqual(m.ntp,original);self.assertEqual(s.state['status'],'restored')
                with self.assertRaisesRegex(ValueError,'replayed'):s.request(r)
    def test_owner_exit_expiry_service_restart_and_boot_recovery(self):
        for cause in ('owner_exit','lease_expired','service_restart','boot_recovery'):
            with self.subTest(cause=cause),tempfile.TemporaryDirectory() as root:
                s,m,c,w,r=self.fixture(root);s.request(r)
                if cause=='owner_exit':m.proc=None;s.tick()
                elif cause=='lease_expired':c.t+=100;w.t+=100;s.tick()
                else:
                    if cause=='boot_recovery':m.bootid='boot-2'
                    new=RestoreService(root,501,m,c,w);new.startup();s=new
                self.assertTrue(m.ntp);self.assertEqual(s.state['restore_reason'],cause)
                self.assertEqual(s.state['status'],'restored')
    def test_clock_steps_abort_owner_and_restore(self):
        for step in (2,4,-2,-4):
            with self.subTest(step=step),tempfile.TemporaryDirectory() as root:
                s,m,c,w,r=self.fixture(root);s.request(r);c.t+=1;w.t+=1+step;s.tick()
                self.assertEqual(s.state['restore_reason'],'wall_monotonic_step')
                self.assertEqual(m.killed,[123]);self.assertTrue(m.ntp)
    def test_interrupted_arming_restores_saved_original(self):
        with tempfile.TemporaryDirectory() as root:
            s,m,c,w,r=self.fixture(root);original=m.set
            def lost(value):original(value);raise RuntimeError('lost response')
            m.set=lost
            with self.assertRaises(RuntimeError):s.request(r)
            self.assertEqual(json.loads((Path(root)/'state.json').read_text())['status'],'arming')
            m.set=original;RestoreService(root,501,m,c,w).startup();self.assertTrue(m.ntp)
    def test_foreign_pid_boot_and_fields_rejected_before_os_change(self):
        for patch in ({'process':'501 replacement'},{'boot':'old'},{'seconds':6000},{'command':'anything'}):
            with tempfile.TemporaryDirectory() as root:
                s,m,c,w,r=self.fixture(root);r.update(patch)
                with self.assertRaises(ValueError):s.request(r)
                self.assertEqual(m.calls,[])
if __name__=='__main__':unittest.main()
