"""Transport release boundaries and supplemental first-attempt separation."""
import hashlib
import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/d) for d in ('evaluation','scripts','experiments')]
from fresh_transport_release import (validate_scenario_transport_diff,
    validate_live_transport_diff,historical_campaign, audit_transition, select_cases, REVIEWED_FILES)
from fresh_campaign import FreshCampaign, evidence_hashes, operational_judgement, operational_failure_action

BEFORE='''class FreshS1:
    def move_service(self): return self.policy()
    def finish(self): return self.run(seconds=1800)
class OtherScenario:
    def finish(self): return self.fixed_horizon()
'''
AFTER='''from contextlib import contextmanager
import os
class FreshS1:
    def move_service(self): return self.policy()
    @contextmanager
    def transport_reads(self): yield
    def finish(self):
        with self.transport_reads():
            return self.finish_once()
    def finish_once(self): return self.run(seconds=1800)
class OtherScenario:
    def finish(self): return self.fixed_horizon()
'''


class TransportReleaseTests(unittest.TestCase):
    def test_clean_analyser_failure_pauses_without_inventing_scientific_safety(self):
        result=dict(execution='judgement_failed',cleanup=True,safety=None,trial_valid=False)
        self.assertEqual(operational_failure_action(result,cleanup_verified=True,budget_available=True),'investigate_before_next_case')
        self.assertIsNone(result['safety'])

    def test_analyser_failure_keeps_real_cleanup_and_budget_safety_gates(self):
        result=dict(execution='judgement_failed',cleanup=True,safety=None,trial_valid=False)
        self.assertEqual(operational_failure_action(result,cleanup_verified=False,budget_available=True),'resolve_owned_cleanup')
        self.assertEqual(operational_failure_action(result,cleanup_verified=True,budget_available=False),'safe_shutdown')

    def test_analyser_exception_seals_only_invalid_unknown_outcomes_without_raw_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            (path/'cleanup.json').write_text(json.dumps({'checks':{'owned_absent':True}}))
            before=evidence_hashes(path)
            with patch('fresh_campaign.judge',side_effect=UnboundLocalError('start unavailable')):
                result=operational_judgement(path,{}, {})
            self.assertFalse(result['trial_valid'])
            self.assertTrue(result['cleanup'])
            self.assertEqual(result['execution'],'judgement_failed')
            for key in ('fault_realized','impact_realized','recovered','safety'):
                self.assertIsNone(result[key])
            self.assertIn('UnboundLocalError',result['missing'][0])
            self.assertEqual(evidence_hashes(path),before)

    def test_missing_or_failed_cleanup_is_never_inferred_from_analyser_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            for checks in ({}, {'owned_absent':False}):
                (path/'cleanup.json').write_text(json.dumps({'checks':checks}))
                with patch('fresh_campaign.judge',side_effect=RuntimeError('broken raw')):
                    self.assertFalse(operational_judgement(path,{}, {})['cleanup'])

    def test_normal_judgements_are_returned_unchanged_and_interrupts_propagate(self):
        expected={'trial_valid':True,'metrics':{'raw':123}}
        with patch('fresh_campaign.judge',return_value=expected):
            self.assertIs(operational_judgement('.',{}, {}),expected)
        with patch('fresh_campaign.judge',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):operational_judgement('.',{}, {})

    def _supplement_driver_flow(self, fail_second=False):
        script=ast.parse((ROOT/'evaluation/fresh_release_driver.py').read_text())
        loop=next(n for n in ast.walk(script) if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='origin')
        tree=ast.Module(body=[loop,ast.parse("environment('down')").body[0]],type_ignores=[])
        events=[];campaigns={}
        profile={'cases':[{'id':'s1-b02-a','scenario':'s1'},{'id':'s2-b03-p','scenario':'s2'}]}
        def frozen(name,*args,**kwargs):
            campaigns[name]={'cases':[{'status':'pending'}]};return name
        def run_one(name):
            events.append(('run',name))
            if fail_second and name.startswith('s2'):raise RuntimeError('second supplement failed')
            campaigns[name]['cases'][0].update(status='finished',attempts=[{'state':'VERIFIED'}])
        values=dict(TRANSITION={'supplemental_origins':['s1-b02-a','s2-b03-p']},
            supplemental_origins=lambda a:a['supplemental_origins'],P=profile,pilots={'s1':'p1','s2':'p2'},
            frozen=frozen,check_frozen=lambda name:campaigns[name],run_one=run_one,
            measured=lambda name:events.append(('reported',name)),
            environment=lambda name:events.append(('environment',name)))
        try:exec(compile(tree,'driver-supplement-flow','exec'),values)
        except RuntimeError:
            if not fail_second:raise
        return events

    def test_driver_down_follows_both_actual_supplement_attempts(self):
        events=self._supplement_driver_flow()
        self.assertEqual([v for k,v in events if k=='run'],['s1-supplement-transport-v2','s2-supplement-transport-v2'])
        self.assertEqual(events[-1],('environment','down'))
        self.assertEqual(len([1 for k,v in events if k=='reported']),2)

    def test_driver_does_not_down_when_second_supplement_has_not_finished(self):
        events=self._supplement_driver_flow(fail_second=True)
        self.assertFalse(any(k=='environment' for k,v in events))

    def test_two_separate_supplements_keep_original_main_and_order(self):
        profile=json.loads((ROOT/'config/graduation-evaluation-fresh.json').read_text())
        from fresh_contract import schedule
        profile['cases']=schedule(profile)
        authorization={'supplemental_origins':['s1-b02-a','s2-b03-p']}
        first=select_cases(profile,authorization,'s1','supplemental')[0]
        second=select_cases(profile,authorization,'s2','supplemental')[0]
        self.assertEqual((first['id'],second['id']),('s1-b02-a-supplement01','s2-b03-p-supplement01'))
        self.assertEqual((first['purpose'],second['purpose']),('supplemental','supplemental'))
        self.assertEqual((first['order'],second['order']),(38,39))
        self.assertNotEqual(first['block'],second['block'])
        self.assertEqual(sum(c['purpose']=='main' for c in profile['cases']),29)
        self.assertNotIn('attempts',first);self.assertNotIn('attempts',second)

    def test_scenario_read_guard_rejects_policy_horizon_mutation_changes(self):
        previous=BEFORE+"\nclass FreshS2:\n def snapshot(self): return self.remote('curl -fsS http://198.18.0.2:8090/progress')\n"
        current=AFTER+"\nclass FreshS2:\n def snapshot(self): return self.read_remote('curl -fsS http://198.18.0.2:8090/progress')\n"
        validate_scenario_transport_diff(previous,current)
        for script in ('sudo reboot','curl -fsS http://198.18.0.2:8090/progress; reboot'):
            changed=current.replace("self.read_remote('curl -fsS http://198.18.0.2:8090/progress')",'self.read_remote('+repr(script)+')')
            with self.assertRaises(ValueError):validate_scenario_transport_diff(previous,changed)
        with self.assertRaises(ValueError):validate_scenario_transport_diff(previous,current.replace('seconds=1800','seconds=900'))

    def test_live_adapter_changes_only_reconnect_helper_and_calibration_stays_bound(self):
        current=(ROOT/'evaluation/fresh_live.py').read_text()
        hook='        from fresh_transport import coordinate_reconnect\n        h.call=coordinate_reconnect(h.call,h.state,Path(__file__).resolve().parents[1])\n'
        self.assertIn(hook,current);previous=current.replace(hook,'')
        validate_live_transport_diff(previous,current)
        with self.assertRaisesRegex(ValueError,'semantics changed'):
            validate_live_transport_diff(previous,current.replace('self.require_clean_state()','self.skip_clean_state()'))
        self.assertNotIn('evaluation/fresh_calibration.py',REVIEWED_FILES)
    def test_transport_wrapper_is_the_only_scenario_ast_change(self):
        validate_scenario_transport_diff(BEFORE, AFTER)
        for changed in (AFTER.replace('seconds=1800','seconds=900'),
                        AFTER.replace('self.policy()','self.other_policy()'),
                        AFTER.replace('self.fixed_horizon()','self.shorter_horizon()')):
            with self.assertRaisesRegex(ValueError,'scenario change'):
                validate_scenario_transport_diff(BEFORE, changed)

    def test_finish_wrapper_cannot_add_an_action(self):
        changed=AFTER.replace('return self.finish_once()','self.restart()\n            return self.finish_once()')
        with self.assertRaisesRegex(ValueError,'finish wrapper'):
            validate_scenario_transport_diff(BEFORE, changed)

    def test_scientific_analysis_workload_and_fault_files_cannot_be_exempted(self):
        for name in ('evaluation/fresh_analysis.py','evaluation/fresh_contract.py',
                     'kubernetes/graduation-s1/loadgen.py','experiments/graduation_s1_auto.py',
                     'experiments/graduation_s3.py'):
            self.assertNotIn(name, REVIEWED_FILES)

    def test_authorization_requires_exactly_one_supplement_and_human_instruction(self):
        for value in ({}, {'kind':'user-authorized-transport-continuation-v1','supplemental_limit':2},
                      {'kind':'user-authorized-transport-continuation-v1','supplemental_limit':1}):
            with self.assertRaises(ValueError):audit_transition({},value,ROOT)

    def test_historical_evidence_changes_and_unsealed_attempts_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);(path/'frozen-manifest.json').write_text('{}')
            attempt=path/'cases/x/attempt-01';attempt.mkdir(parents=True)
            (attempt/'raw.json').write_text('{"original":true}')
            (attempt/'judgement.json').write_text('{"trial_valid":false}')
            row={'id':'attempt-01','path':'cases/x/attempt-01','state':'VERIFIED',
                 'evidence_sha256':evidence_hashes(attempt)}
            manifest={'synthetic':False,'cases':[{'attempts':[row],'judgement':{'trial_valid':False}}]}
            frozen=hashlib.sha256((path/'frozen-manifest.json').read_bytes()).hexdigest()
            with patch('fresh_campaign.check_frozen',return_value=manifest):
                self.assertEqual(historical_campaign(path,frozen),manifest)
                (attempt/'raw.json').write_text('{"original":false}')
                with self.assertRaisesRegex(ValueError,'changed'):historical_campaign(path,frozen)
                row['state']='CLEANUP'
                with self.assertRaisesRegex(ValueError,'active'):historical_campaign(path,frozen)

    def test_historical_manifest_hash_and_synthetic_contamination_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);f=path/'frozen-manifest.json';f.write_text('{}')
            with self.assertRaisesRegex(ValueError,'freeze'):historical_campaign(path,'0'*64)
            with patch('fresh_campaign.check_frozen',return_value={'synthetic':True}):
                with self.assertRaisesRegex(ValueError,'synthetic'):
                    historical_campaign(path,hashlib.sha256(f.read_bytes()).hexdigest())

    def test_supplement_cannot_be_retried_even_when_invalid_and_max_attempts_is_two(self):
        with tempfile.TemporaryDirectory() as folder:
            runner=FreshCampaign.__new__(FreshCampaign);runner.directory=Path(folder)
            runner.profile={'max_attempts':2};runner.backend=Mock()
            case={'id':'a-supplement01','status':'finished','depends_on':[],
                  'judgement':{'trial_valid':False},'attempts':[{'id':'attempt-01','state':'VERIFIED'}]}
            manifest={'synthetic':True,'stage':'supplemental','cases':[case]}
            with patch('fresh_campaign.check_frozen',return_value=manifest):
                with self.assertRaisesRegex(ValueError,'retry cap'):
                    runner.run(retry_case=case['id'])
            self.assertEqual(len(case['attempts']),1)
            runner.backend.execute.assert_not_called()

    def test_remaining_selection_preserves_main_order_and_does_not_copy_completed_cases(self):
        profile=json.loads((ROOT/'config/graduation-evaluation-fresh-candidate-2026-10-26.json').read_text())
        main=[case for case in profile['cases'] if case['purpose']=='main']
        authorization={'remaining_main_ids':[case['id'] for case in main[9:]],'supplemental_origin':'s1-b02-a'}
        selected=[case for scenario in ('s1','s2','s3','s4') for case in select_cases(profile,authorization,scenario,'main')]
        self.assertEqual([case['id'] for case in selected],authorization['remaining_main_ids'])
        self.assertEqual(len(selected),20)
        self.assertFalse({case['id'] for case in selected}&{case['id'] for case in main[:9]})
        self.assertTrue(all(case['status']=='pending' and 'attempts' not in case for case in selected))
        supplement=select_cases(profile,authorization,'s1','supplemental')
        self.assertEqual(len(supplement),1)
        self.assertEqual(supplement[0]['mode'],'A')
        self.assertEqual(supplement[0]['purpose'],'supplemental')
        self.assertNotEqual(supplement[0]['block'],'b02')
        self.assertGreater(supplement[0]['order'],max(case['order'] for case in profile['cases']))
        self.assertEqual(sum(case['purpose']=='main' for case in profile['cases']),29)


if __name__=='__main__':unittest.main()


class FourSupplementTests(unittest.TestCase):
    origins=['s1-b02-a','s2-b03-p','s3-b02-m3600','s3-b03-m3600']
    def profile(self):
        return {'cases':[dict(id=o,scenario=o[:2],mode='M3600' if o.startswith('s3') else ('A' if o.startswith('s1') else 'P'),block='b02' if 'b02' in o else 'b03',purpose='main',order=i) for i,o in enumerate(self.origins)]}
    def test_each_s3_origin_is_explicit_unique_and_never_a_main_replacement(self):
        p=self.profile();before=json.dumps(p,sort_keys=True);a={'supplemental_origins':self.origins}
        with self.assertRaisesRegex(ValueError,'explicit'):select_cases(p,a,'s3','supplemental')
        for i,o in enumerate(self.origins):
            c=select_cases(p,a,o[:2],'supplemental',origin=o)[0]
            self.assertEqual(c['id'],o+'-supplement01');self.assertEqual(c['purpose'],'supplemental');self.assertEqual(c['order'],38+i);self.assertTrue(c['block'].startswith('supplement-'))
        self.assertEqual(json.dumps(p,sort_keys=True),before)
    def flow(self, fail=None):
        script=ast.parse((ROOT/'evaluation/fresh_release_driver.py').read_text());loop=next(n for n in ast.walk(script) if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='origin');events=[];manifests={}
        def frozen(name,*args,**kwargs):
            events.append(('freeze',kwargs['origin']));manifests[name]={'cases':[{'status':'pending'}]};return name
        def run(name):
            events.append(('run',name))
            if fail and fail in name:raise RuntimeError('single attempt failed')
            manifests[name]['cases'][0].update(status='finished',attempts=[{'state':'VERIFIED'}])
        values=dict(P=self.profile(),TRANSITION={'supplemental_origins':self.origins},supplemental_origins=lambda a:a['supplemental_origins'],pilots={'s1':'p1','s2':'p2','s3':'p3'},frozen=frozen,check_frozen=lambda name:manifests[name],run_one=run,measured=lambda name:None,save=lambda *a:None,environment=lambda action:events.append(('environment',action)))
        try:exec(compile(ast.Module(body=[loop,ast.parse("environment('down')").body[0]],type_ignores=[]),'four-supp-flow','exec'),values)
        except RuntimeError:
            if not fail:raise
        return events
    def test_down_follows_four_actual_distinct_attempts_in_order(self):
        events=self.flow();self.assertEqual([v for k,v in events if k=='freeze'],self.origins);self.assertEqual(len(set(v for k,v in events if k=='run')),4);self.assertEqual(events[-1],('environment','down'))
    def test_missing_fourth_attempt_blocks_down(self):
        events=self.flow(fail='s3-b03-m3600');self.assertFalse(any(k=='environment' for k,v in events))
    def test_two_supplement_authorization_cannot_admit_four(self):
        a=dict(kind='user-authorized-ssh-read-two-supplement-continuation-v2',supplemental_limit=4,supplemental_origins=self.origins,human_instruction='yes',boundary_case='closed')
        with self.assertRaises(ValueError):audit_transition({},a,ROOT)
        a.update(kind='user-authorized-four-supplement-cleanup-read-continuation-v3',human_instruction='')
        with self.assertRaisesRegex(ValueError,'human instruction'):audit_transition({},a,ROOT)


class SupplementScopeSafetyTests(unittest.TestCase):
    def test_scientific_unknown_or_false_with_actual_cleanup_pauses_before_down(self):
        tree=ast.parse((ROOT/'evaluation/fresh_release_driver.py').read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_one')
        for budget in (True,False):
            with self.subTest(budget=budget),tempfile.TemporaryDirectory() as folder:
                events=[];case={'id':'supplement','status':'pending'};row=dict(case_id='supplement',attempt='attempt-01',cleanup=True,safety=False,trial_valid=False)
                class Pause(RuntimeError):pass
                values=dict(check_frozen=lambda *a,**k:{'cases':[case]},operational_gate=lambda *a:None,remaining_budget=lambda *a:None,verify_headroom=lambda *a:None,save=lambda *a,**k:None,cli=lambda *a,**k:None,measured=lambda *a:{'run_results':[row]},operational_failure_action=lambda *a,**k:'safe_shutdown',BedLedger=lambda p:type('Ledger',(),{'usage':lambda self:{'estimated_cost_krw':10 if budget else 101}})(),P={'operations':{'new_work_budget_krw':100}},BASE=Path(folder),atomic_json=lambda *a:None,utc=lambda:'now',DATA={},environment=lambda action:events.append(action),OperationalPause=Pause)
                exec(compile(ast.Module(body=[fn],type_ignores=[]),'run-one-scope','exec'),values)
                with self.assertRaises(Pause):values['run_one']('campaign')
                self.assertEqual(events,[] if budget else ['down'])
