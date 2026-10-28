"""Transport release boundaries and supplemental first-attempt separation."""
import hashlib
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
