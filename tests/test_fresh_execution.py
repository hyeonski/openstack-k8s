"""Execution handoff failure paths, entirely offline; no live assertion fixtures."""
import copy
import json
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/d) for d in ('evaluation','scripts','experiments')]
from fresh_baseline import baseline_metrics, baseline_gate
from fresh_campaign import FreshCampaign, freeze, report, check_frozen, pilot_contract
from fresh_contract import validate
from fresh_evidence import utc, epoch, Evidence
from fresh_fake import FakeBackend, synthetic_profile, operational_fixture
from fresh_operations import phase, reservation, case_time_gate, BedLedger
from lib.state import atomic_json


def candidate():
    p=json.loads((ROOT/'config/graduation-evaluation-fresh-candidate-2026-10-26.json').read_text())
    p.update(readiness='confirmed')
    p['operations']=operational_fixture(p['operations'])
    return p


def baseline(cfg, latency=.01):
    return [dict(index=i,request_id=str(i),scheduled_utc=utc(1000+i/cfg['rate']),
        scheduled_monotonic=100+i/cfg['rate'],started_utc=utc(1000+i/cfg['rate']+.001),
        started_monotonic=100+i/cfg['rate']+.001,completed_utc=utc(1000+i/cfg['rate']+latency),
        completed_monotonic=100+i/cfg['rate']+latency,clock_id='one',ok=True,correct=True,
        deadline_seconds=cfg['deadline_seconds']) for i in range(int(60*cfg['rate']))]


class FreshExecutionTests(unittest.TestCase):
    def test_baseline_fixed_indexes_clock_schedule_and_deadline_fail_closed(self):
        cfg=candidate()['s1'];good=baseline(cfg)
        self.assertTrue(baseline_metrics(good,cfg)['passed'])
        variants=[]
        variants.append(good[1:]+[{**good[-1],'index':300,'request_id':'300'}])
        variants.append(good+[good[100]])
        for field,value in [('scheduled_utc',utc(1050)),('clock_id','other'),('completed_utc',None),
                            ('completed_monotonic',-1),('deadline_seconds',6)]:
            damaged=copy.deepcopy(good);damaged[100][field]=value;variants.append(damaged)
        for damaged in variants:
            with self.subTest(row=damaged[0]),self.assertRaisesRegex(RuntimeError,'baseline rejected'),tempfile.TemporaryDirectory() as root:
                baseline_gate(Evidence(root),cfg,lambda:damaged,wait=False,source='offline failure')
        # A time-boundary rounding perturbation cannot move index 100 to bin 0.
        good[100]['scheduled_utc']=utc(1020-.0000005)
        self.assertEqual([b['samples'] for b in baseline_metrics(good,cfg)['bins']],[100]*3)

    def test_v1_uses_dedicated_slo_and_baseline_never_includes_post_injection(self):
        p=candidate();cfg=p['s1'];raw=baseline(cfg,.15)
        self.assertTrue(baseline_metrics(raw,cfg)['passed'])
        self.assertFalse(baseline_metrics(raw,{**cfg,**p['v1_condition']})['passed'])
        self.assertFalse(baseline_metrics(raw,cfg,before=1050)['passed'])
        slow=baseline(cfg,5.1)
        self.assertFalse(baseline_metrics(slow,cfg)['passed'])
        v1={**cfg,**p['v1_condition']}
        self.assertTrue(baseline_metrics(baseline(cfg,.1),v1)['passed'])
        self.assertFalse(baseline_metrics(baseline(cfg,.100001),v1)['passed'])

    def test_whole_phase_does_not_reset_per_command_and_restores_outer_timer(self):
        started=time.monotonic()
        with self.assertRaisesRegex(TimeoutError,'whole-phase'):
            with phase('sum',.04):
                time.sleep(.025);time.sleep(.025)
        self.assertLess(time.monotonic()-started,.2)
        with phase('outer',.1):
            with phase('inner',.01):pass
            self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0],.05)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)

    def test_operational_keys_missing_ranges_credit_and_headroom_rejected(self):
        p=candidate();validate(p,live=True)
        for key in ('fixture_prepare_timeout_seconds','last_case_start_utc','hard_stop_utc','preregistered_documents','cost_estimate','credit_evidence'):
            damaged=copy.deepcopy(p);del damaged['operations'][key]
            with self.subTest(key=key),self.assertRaises(ValueError):validate(damaged,live=True)
        mutations=[lambda p:p['operations'].update(fixture_prepare_timeout_seconds=1801),
            lambda p:p.update(host_headroom_seconds=7200),lambda p:p['operations'].update(credit_budget_krw=100),
            lambda p:p['analysis'].pop('baseline_contract'),lambda p:p['analysis'].pop('secondary_metrics')]
        for change in mutations:
            damaged=copy.deepcopy(p);change(damaged)
            with self.assertRaises(ValueError):validate(damaged,live=True)

    def test_cutoffs_and_whole_phase_reservations_are_consumed(self):
        p=candidate();hard=epoch(p['operations']['hard_stop_utc'])
        self.assertEqual([reservation(p),reservation(p,cold=True),reservation(p,rotate=True)],[10800,14400,16200])
        for options,seconds in [({},10800),({'cold':True},14400),({'rotate':True},16200)]:
            case_time_gate(p,now=hard-seconds-1,**options)
            with self.assertRaisesRegex(RuntimeError,'admission rejected'):
                case_time_gate(p,now=hard-seconds,**options)

    def test_pilot_contract_binds_every_phase_and_host_headroom(self):
        p=candidate()
        for key in ('environment_ensure_timeout_seconds','fixture_prepare_timeout_seconds','cleanup_seconds','host_shutdown_timeout_seconds'):
            q=copy.deepcopy(p);q['operations'][key]-=1
            self.assertNotEqual(pilot_contract(p,'s1'),pilot_contract(q,'s1'))
        q=copy.deepcopy(p);q['host_headroom_seconds']+=1
        self.assertNotEqual(pilot_contract(p,'s1'),pilot_contract(q,'s1'))

    def test_dev_snapshot_primary_exclusion_and_interrupted_cleanup_without_replay(self):
        class Interrupted(FakeBackend):
            def execute(self,*args):
                super().execute(*args);raise KeyboardInterrupt()
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'profile.json';atomic_json(source,synthetic_profile(candidate()))
            dest=Path(root)/'dev';freeze(source,dest,'development',synthetic=True)
            backend=Interrupted(fail_cleanup=True);campaign=FreshCampaign(dest,backend)
            with self.assertRaisesRegex(RuntimeError,'cleanup failed'):campaign.run()
            self.assertEqual(backend.executed,['dev-s1-a'])
            backend.fail_cleanup=False;campaign.resume_cleanup('dev-s1-a')
            out=report(dest,True)
            self.assertEqual(out['primary_sample_count'],0)
            self.assertEqual([r['purpose'] for r in out['run_results']],['development'])
            self.assertEqual(backend.executed,['dev-s1-a'])
            self.assertFalse(out['run_results'][0]['trial_valid'])

    def test_admission_rejection_creates_no_attempt_or_case_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'profile.json';atomic_json(source,synthetic_profile(candidate()))
            dest=Path(root)/'pilot';freeze(source,dest,'preparation',scenario='s1',synthetic=True)
            data=check_frozen(dest);data['synthetic']=False
            backend=Mock();backend.admit.side_effect=RuntimeError('explicit down/ensure required')
            with patch('fresh_campaign.check_frozen',return_value=data),patch('fresh_campaign.spent_budget_seconds',return_value=0),patch('fresh_campaign.case_time_gate'):
                campaign=FreshCampaign(dest,backend)
                with self.assertRaisesRegex(RuntimeError,'explicit down'):campaign.run(limit=1)
            self.assertFalse((dest/'cases').exists())
            self.assertTrue(all(not c.get('attempts') for c in data['cases']))
            backend.execute.assert_not_called()

    def test_live_execute_uses_readiness_only_and_passes_remaining_fixture_deadline(self):
        from fresh_live import LiveBackend
        p=candidate();p['observed_environment']={'host_identity':{'h':{'id':'1'}}}
        with tempfile.TemporaryDirectory() as root:
            base=Path(root);state=base/'state';state.mkdir();atomic_json(state/'graduation-environment.json',{'phase':'ready','run_id':'env'})
            backend=LiveBackend.__new__(LiveBackend);backend.state=state;backend.directory=base/'campaign';backend.directory.mkdir()
            backend.require_clean_state=Mock();h=Mock();h.data={'host_identity':p['observed_environment']['host_identity'],'flavors':{}}
            h.state_record.return_value=None;h.verify_ready_environment.return_value={'run_id':'env'}
            backend.helper=Mock(return_value=h)
            with patch('fresh_calibration.TransportWatch') as watcher:
                backend.execute({'id':'dev','scenario':'s1'},p,Evidence(base/'attempt'))
                watcher.return_value.__exit__.assert_called_once()
            h.environment.assert_not_called()
            h.verify_ready_environment.assert_called_once()
            h.prepare_workers.assert_called_once()
            self.assertIn('fresh_scenarios.py',str(h.call.call_args.args[0][1]))

    def test_p95_difference_is_secondary_first_attempt_only_and_null_on_invalid(self):
        class InvalidFirst(FakeBackend):
            def execute(self,case,profile,ev):
                super().execute(case,profile,ev)
                if case['mode']=='M':
                    path=ev.directory/'requests.jsonl';raw=[json.loads(line) for line in path.read_text().splitlines()]
                    row=next(r for r in raw if epoch(r['scheduled_utc'])>=1792972800)
                    row.update(ok=True,correct=True,completed_utc=utc(epoch(row['scheduled_utc'])+.013),completed_monotonic=row['scheduled_monotonic']+.013)
                    path.write_text(''.join(json.dumps(r)+'\n' for r in raw))
                if case['id']=='s2-b01-p' and len(case['attempts'])==1:
                    ev.event('execution_error',detail='offline first-attempt failure')
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'profile.json';atomic_json(source,synthetic_profile(candidate()))
            dest=Path(root)/'main';freeze(source,dest,'main',scenario='s2',synthetic=True)
            campaign=FreshCampaign(dest,InvalidFirst());campaign.run();campaign.run(retry_case='s2-b01-p')
            contrasts=report(dest,True)['paired_contrasts']
            self.assertIsNone(contrasts[0]['scheduled_latency_p95_ms_difference'])
            self.assertAlmostEqual(contrasts[1]['scheduled_latency_p95_ms_difference'],-2,places=3)

    def test_registered_document_copy_and_current_document_are_both_verified(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root);(base/'docs').mkdir();doc=base/'docs/registered.md';doc.write_text('registered')
            p=synthetic_profile(candidate());p['operations']['preregistered_documents']=['docs/registered.md']
            source=base/'profile.json';atomic_json(source,p);dest=base/'campaign'
            with patch('fresh_campaign.ROOT',base),patch('fresh_campaign.source_hashes',return_value={}):
                freeze(source,dest,'development',synthetic=True)
                check_frozen(dest,current=True)
                doc.write_text('changed')
                with self.assertRaisesRegex(ValueError,'document changed'):check_frozen(dest,current=True)
                snapshot=dest/'preregistered-documents/docs/registered.md';snapshot.write_text('corrupt')
                with self.assertRaisesRegex(ValueError,'snapshot changed'):check_frozen(dest)

    def test_uptime_counts_preparation_idle_and_failed_ensure_until_verified_down(self):
        p=candidate()
        with tempfile.TemporaryDirectory() as root:
            p['operations']['bed_ledger_path']=str(Path(root)/'bed.json')
            ledger=BedLedger(p);ledger.begin()
            start=epoch(ledger.data['sessions'][0]['started'])
            self.assertAlmostEqual(ledger.usage(start+3600)['bed_seconds'],3600)
            with self.assertRaisesRegex(RuntimeError,'all hosts'):ledger.stopped({'h':{'status':'RUNNING'}})
            with self.assertRaisesRegex(RuntimeError,'still active'):ledger.begin()
            ledger.data['sessions'][0]['started']=utc(time.time()-158401);ledger.save()
            with self.assertRaisesRegex(RuntimeError,'uptime gate'):ledger.gate(10800)
            ledger.stopped({'h':{'status':'TERMINATED'}})


if __name__=='__main__':unittest.main()
