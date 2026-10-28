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
    validate_calibration_transport_diff, review_dev_sources, WATCH_RECONNECT,
    historical_campaign, audit_transition, select_cases, REVIEWED_FILES)
from fresh_campaign import FreshCampaign, evidence_hashes

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
    def watcher_sources(self):
        import textwrap
        current=(ROOT/'evaluation/fresh_calibration.py').read_text()
        new=textwrap.indent(WATCH_RECONNECT,'            ')
        old="            self.helper.call([ROOT/'scripts/gcp-workload-api-tunnel.sh','ensure'],\n                             'transport-reconnect.log',timeout=60)\n"
        self.assertIn(new,current)
        return current.replace(new,old),current

    def test_watcher_only_shared_lock_changes_and_scientific_rule_cannot_change(self):
        old,new=self.watcher_sources();validate_calibration_transport_diff(old,new)
        for changed in (new.replace('multiplier=1.20','multiplier=1.10'),
                        new.replace('deadline = time.monotonic() + 60','deadline = time.monotonic() + 120'),
                        new.replace("'reconnect_completed'","'reconnect_hidden'")):
            with self.assertRaises(ValueError):validate_calibration_transport_diff(old,changed)

    def test_dev_reuse_requires_explicit_review_for_changed_watcher_and_keeps_sha_difference(self):
        old,new=self.watcher_sources()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);prior={'source_sha256':{}};source={}
            names=('kubernetes/graduation-s1/app.py','kubernetes/graduation-s1/loadgen.py',
                'evaluation/fresh_baseline.py','evaluation/fresh_analysis.py','evaluation/fresh_contract.py','evaluation/fresh_calibration.py')
            for name in names:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(new if name.endswith('fresh_calibration.py') else '# identical')
                raw=old if name.endswith('fresh_calibration.py') else '# identical'
                prior['source_sha256'][name]=hashlib.sha256(raw.encode()).hexdigest();source[name]=hashlib.sha256(p.read_bytes()).hexdigest()
            original=root/'old/source/evaluation/fresh_calibration.py';original.parent.mkdir(parents=True);original.write_text(old)
            auth={'changed_files':['evaluation/fresh_calibration.py'],'approved_source_sha256':source,'prior_campaigns':{'s1-main-v1':{'path':str(root/'old')}}}
            with self.assertRaisesRegex(ValueError,'scientific source'):review_dev_sources(prior,None,root)
            result=review_dev_sources(prior,auth,root)['evaluation/fresh_calibration.py']
            self.assertNotEqual(result['historical_sha256'],result['current_sha256'])
            self.assertIn('explicit transport',result['kind'])
            (root/'evaluation/fresh_analysis.py').write_text('# changed analysis')
            with self.assertRaisesRegex(ValueError,'scientific source'):review_dev_sources(prior,auth,root)

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
