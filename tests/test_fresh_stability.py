"""Failure-path proofs for the stabilization boundary; no cloud or OS clock edits."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/x) for x in ('evaluation','scripts','experiments')]
from fresh_read_budget import read_with_budget, transient_error
from fresh_analysis import judge
from fresh_fake import FakeBackend, synthetic_profile
from fresh_evidence import Evidence

class Clock:
    def __init__(self): self.t=0
    def __call__(self): return self.t
    def sleep(self,seconds): self.t+=seconds

class StabilityTests(unittest.TestCase):
    def test_outages_recover_without_extending_budget(self):
        for outage in (5,15,20,30,120):
            for slow in (False,True):
                with self.subTest(outage=outage,slow=slow),tempfile.TemporaryDirectory() as root:
                    clock=Clock();calls=[]
                    def invoke(left):
                        cap=left();calls.append(cap)
                        if clock.t<outage:
                            if slow:clock.sleep(cap)
                            raise RuntimeError('TLS handshake timeout')
                        return 'actual observation'
                    kwargs=dict(timeout=90,identity=lambda left:left(),label='fixture',evidence=root,clock=clock,sleep=clock.sleep)
                    if outage==120:
                        with self.assertRaises((RuntimeError,TimeoutError)):read_with_budget(invoke,**kwargs)
                    else:self.assertEqual(read_with_budget(invoke,**kwargs),'actual observation')
                    self.assertLessEqual(clock.t,90);self.assertLessEqual(len(calls),3)
                    self.assertTrue(all(cap<=20 for cap in calls))

    def test_short_phase_and_identity_share_deadline(self):
        clock=Clock();calls=[]
        def invoke(left):calls.append(left());raise RuntimeError('connection refused')
        with tempfile.TemporaryDirectory() as root,self.assertRaises(TimeoutError):
            read_with_budget(invoke,timeout=8,identity=lambda left:left(),label='H',evidence=root,clock=clock,sleep=clock.sleep)
        self.assertEqual(clock.t,8);self.assertEqual(calls,[8])

    def test_permanent_identity_and_nested_read_never_replay(self):
        for error in ('forbidden','not found','certificate failed'):
            invoke=Mock(side_effect=RuntimeError(error))
            with tempfile.TemporaryDirectory() as root,self.assertRaises(RuntimeError):
                read_with_budget(invoke,timeout=90,identity=Mock(),label='fixture',evidence=root)
            self.assertEqual(invoke.call_count,1)
        with tempfile.TemporaryDirectory() as root:
            clock=Clock();inner=Mock(side_effect=RuntimeError('broken pipe'));outer=Mock()
            def invoke(left):
                outer()
                return read_with_budget(inner,timeout=90,identity=Mock(),label='nested',evidence=root)
            with self.assertRaises(RuntimeError):
                read_with_budget(invoke,timeout=90,identity=Mock(),label='outer',evidence=root,clock=clock,sleep=clock.sleep)
            self.assertEqual(inner.call_count,3);self.assertEqual(outer.call_count,3)
            changed=Mock(side_effect=RuntimeError('UID changed'))
            once=Mock(side_effect=RuntimeError('connection refused'))
            with self.assertRaisesRegex(RuntimeError,'UID changed'):
                read_with_budget(once,timeout=90,identity=changed,label='fixture',evidence=root)
            self.assertEqual(once.call_count,1)

    def test_real_error_strings(self):
        for error in ("Error while connecting [4047: 'Failed to lookup instance']",'TLS handshake timeout','connection reset by peer','broken pipe',
                      'The connection to the server 127.0.0.1:16444 was refused - did you specify the right host or port?'):
            self.assertTrue(transient_error(RuntimeError(error)))

    def test_kubectl_refusal_reconnects_once_within_original_budget(self):
        clock=Clock();error=RuntimeError('The connection to the server 127.0.0.1:16444 was refused')
        invoke=Mock(side_effect=[error,'same owned Job log']);reconnect=Mock();identity=Mock()
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(read_with_budget(invoke,timeout=60,identity=identity,reconnect=reconnect,
                label='job-log',evidence=root,clock=clock,sleep=clock.sleep),'same owned Job log')
        self.assertEqual(invoke.call_count,2);reconnect.assert_called_once()
        self.assertEqual(identity.call_count,2)  # Before retry and after readback.
        self.assertLessEqual(clock.t,60)
        self.assertFalse(transient_error(RuntimeError(str(error)+'; forbidden')))

    def test_missing_horizon_and_empty_raw_are_explicit_invalid(self):
        profile=synthetic_profile(json.loads((ROOT/'config/graduation-evaluation-fresh.json').read_text()))
        for scenario,mode in (('s1','P'),('s2','P'),('s3','P3600'),('s4','on')):
            for missing in ('horizon_end','injection_applied','all'):
                with self.subTest(scenario=scenario,missing=missing),tempfile.TemporaryDirectory() as root:
                    case=next(c for c in profile['cases'] if c['scenario']==scenario and c['mode']==mode)
                    ev=Evidence(root);FakeBackend().execute(case,profile,ev)
                    p=Path(root)/'events.jsonl';rows=[json.loads(x) for x in p.read_text().splitlines()]
                    p.write_text(''.join(json.dumps(r)+'\n' for r in rows if missing!='all' and r['kind']!=missing))
                    if missing=='all':(Path(root)/'requests.jsonl').write_text('')
                    result=judge(root,case,profile)
                    self.assertFalse(result['trial_valid']);self.assertIn('horizon_missing',result['missing'])
                    self.assertIsNone(result['recovered'])


class BoundaryIntegrationTests(unittest.TestCase):
    def test_lost_mutation_ack_is_read_back_and_never_reissued(self):
        from fresh_mutation import mutation_once
        with tempfile.TemporaryDirectory() as root:
            ev=Evidence(root);invoke=Mock(side_effect=RuntimeError('connection reset'))
            readback=Mock(return_value={'uid':'owned','state':'applied'})
            result=mutation_once(ev,'fixture-scale',invoke,readback,
                lambda row:row=={'uid':'owned','state':'applied'})
            self.assertEqual(result['uid'],'owned');self.assertEqual(invoke.call_count,1)
            invoke.reset_mock();readback.return_value={'uid':'replacement','state':'applied'}
            with self.assertRaises(RuntimeError):
                mutation_once(ev,'fixture-scale',invoke,readback,lambda row:row['uid']=='owned')
            self.assertEqual(invoke.call_count,1)

    def test_service_proxy_and_sql_exec_are_never_registered_reads(self):
        from lib.fresh_reads import command_read,openstack_read
        self.assertIsNone(command_read(['kubectl','get','--raw=/api/v1/namespaces/ns/services/http/proxy/healthz']))
        self.assertIsNone(command_read(['kubectl','exec','probe','--','psql','-c','select count(*) from evidence']))
        for args in [('server','stop','x'),('port','set','x'),('network','qos','rule','create')]:
            self.assertFalse(openstack_read(args))
        self.assertTrue(openstack_read(('network','qos','rule','show','policy','rule')))

    def test_measurement_snapshot_survives_cleanup_failure_and_detects_tampering(self):
        from fresh_seal import seal_measurement,verify_measurement
        from lib.state import atomic_json
        from fresh_analysis import rows
        profile=synthetic_profile(json.loads((ROOT/'config/graduation-evaluation-fresh.json').read_text()))
        for scenario,mode in (('s1','P'),('s2','P'),('s3','P3600'),('s4','on')):
            with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as root:
                ev=Evidence(root);case=next(c for c in profile['cases'] if c['scenario']==scenario and c['mode']==mode)
                FakeBackend().execute(case,profile,ev);atomic_json(Path(root)/'identity.json',{'case_id':case['id']})
                seal=seal_measurement(ev,case,profile)
                original=(Path(root)/'measurement/requests.jsonl').read_bytes()
                ev.event('execution_error',phase='cleanup',detail='TLS handshake timeout')
                atomic_json(Path(root)/'cleanup.json',{'checks':{'same_uid':False}})
                self.assertTrue(verify_measurement(root));self.assertEqual((Path(root)/'measurement/requests.jsonl').read_bytes(),original)
                self.assertFalse(judge(root,case,profile)['trial_valid'])
                (Path(root)/'measurement/requests.jsonl').write_bytes(b'tampered')
                with self.assertRaisesRegex(RuntimeError,'sealed measurement changed'):verify_measurement(root)

    def test_no_seal_for_clock_step_or_missing_horizon(self):
        from fresh_seal import seal_measurement
        from lib.state import atomic_json
        profile=synthetic_profile(json.loads((ROOT/'config/graduation-evaluation-fresh.json').read_text()))
        for step in (2,4,-2,-4):
            with tempfile.TemporaryDirectory() as root:
                ev=Evidence(root);case=next(c for c in profile['cases'] if c['scenario']=='s2' and c['mode']=='P')
                FakeBackend().execute(case,profile,ev);atomic_json(Path(root)/'identity.json',{})
                path=Path(root)/'requests.jsonl';rows=[json.loads(x) for x in path.read_text().splitlines()]
                row=rows[-2]
                from fresh_evidence import utc,epoch
                row['completed_utc']=utc(epoch(row['completed_utc'])+step)
                path.write_text(''.join(json.dumps(x)+'\n' for x in rows))
                with self.assertRaises(RuntimeError):seal_measurement(ev,case,profile)
                self.assertFalse((Path(root)/'measurement-sealed.json').exists())

class HorizonRetryBudgetTests(unittest.TestCase):
    def test_normal_first_read_contract_survives_H_boundary_without_new_retry(self):
        import fresh_read_budget as budget
        with tempfile.TemporaryDirectory() as root:
            clock=Clock();budget.set_horizon_deadline(2);limits=[]
            def read(left):limits.append(left());clock.sleep(3);return 'same original snapshot'
            try:
                result=budget.read_with_budget(read,timeout=20,identity=lambda _:None,label='original-read',evidence=root,clock=clock,sleep=clock.sleep)
                self.assertEqual(result,'same original snapshot');self.assertEqual(limits,[20]);self.assertEqual(clock.t,3)
            finally:budget.set_horizon_deadline(None)
    def test_retry_cannot_cross_H_but_baseline_remains_hard(self):
        import fresh_read_budget as budget
        with tempfile.TemporaryDirectory() as root:
            clock=Clock();budget.set_horizon_deadline(5);calls=[]
            def broken(left):calls.append(left());raise ConnectionError('connection reset')
            try:
                with self.assertRaises(TimeoutError):budget.read_with_budget(broken,timeout=90,identity=lambda _:None,label='H retry',evidence=root,clock=clock,sleep=clock.sleep)
                self.assertEqual(len(calls),1);self.assertEqual(clock.t,5)
            finally:budget.set_horizon_deadline(None)
            clock=Clock()
            def late(left):clock.sleep(3);return 'too late'
            with budget.phase_deadline(2),self.assertRaises(TimeoutError):
                budget.read_with_budget(late,timeout=20,identity=lambda _:None,label='baseline',evidence=root,clock=clock,sleep=clock.sleep)

if __name__=='__main__':unittest.main()
