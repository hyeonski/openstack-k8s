import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/d) for d in ('evaluation','scripts','experiments')]
from fresh_extension_analysis import analyze, post_action, campaign_rows, write_new_json
from fresh_extension import freeze_extension
from fresh_campaign import freeze, FreshCampaign, evidence_hashes, check_frozen
from fresh_contract import digest
from fresh_fake import synthetic_profile, FakeBackend
from fresh_evidence import utc
from lib.state import atomic_json


class ExtensionAnalysisTests(unittest.TestCase):
    def fixture(self, root, scenario=None):
        profile = synthetic_profile(json.loads((ROOT/'config/graduation-evaluation-fresh.json').read_text()))
        path = root/'profile.json';atomic_json(path,profile)
        if scenario:
            directory = freeze(path,root/scenario,'main',scenario,synthetic=True)
        else:
            directory = freeze_extension(path,root/'extension',ROOT,synthetic=True)
        FreshCampaign(directory,FakeBackend()).run()
        return directory

    def test_synthetic_extension_table_keeps_strict_and_never_writes_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=self.fixture(Path(temp));before=evidence_hashes(directory)
            report=analyze(directory,allow_synthetic=True)
            self.assertIn('원래 primary를 대체하지 않는다',report['notice'])
            self.assertEqual([r['mode'] for r in report['tables']['s2']],['S','S','S','P'])
            for row in report['tables']['s2']:
                self.assertTrue(row['strict']['trial_valid'])
                self.assertEqual(row['post_action']['seconds'],7)
                self.assertAlmostEqual(row['post_action']['service_slo_violation_fraction'],6/66)
                self.assertEqual(row['service_slo_violation_fraction'],.25)
                self.assertEqual(row['failure_rate'],.25)
                self.assertEqual(row['unhealthy_bins'],2)
                self.assertIsNotNone(row['conditional_p95_ms'])
                self.assertGreater(row['upload_goodput_Bps'],0)
            self.assertEqual(evidence_hashes(directory),before)
            with self.assertRaisesRegex(ValueError,'synthetic'):
                analyze(directory)

    def test_s1_and_main_s2_remain_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            extension=self.fixture(root)
            main=self.fixture(root,'s2')
            s1=self.fixture(root,'s1')
            report=analyze(extension,[main,s1],allow_synthetic=True)
            self.assertEqual(len(report['tables']['s2']),10)
            self.assertEqual(len(report['tables']['s1']),9)
            self.assertEqual({r['mode'] for r in report['tables']['s1']},{'P','M','A'})
            s1_m=next(r for r in report['tables']['s1'] if r['mode']=='M')
            self.assertIsNone(s1_m['post_action']['service_slo_violation_fraction'])
            with self.assertRaisesRegex(ValueError,'duplicate'):
                analyze(extension,[main,main],allow_synthetic=True)

    def test_invalid_first_attempt_is_never_replaced_by_a_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            main=self.fixture(Path(temp),'s2')
            data=check_frozen(main);case=data['cases'][0];attempt=case['attempts'][0]
            path=main/attempt['path'];judgement=json.loads((path/'judgement.json').read_text())
            judgement.update(trial_valid=False,missing=['synthetic_missing'])
            atomic_json(path/'judgement.json',judgement)
            attempt['evidence_sha256']=evidence_hashes(path)
            case['attempts'].append({'id':'attempt-02','path':'does-not-exist'})
            atomic_json(main/'campaign.json',data)
            included,excluded=campaign_rows(main,'main',True)
            self.assertEqual(len(included),5)
            self.assertEqual(excluded[0]['case_id'],case['id'])
            self.assertEqual(excluded[0]['reason'],'strict_invalid_first_attempt')

    def test_named_supplement_is_reported_separately(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);directory=self.fixture(root)
            # Build a distinct synthetic supplemental manifest, never touch live evidence.
            data=check_frozen(directory);case=data['cases'][3]
            case.update(id='s2-b03-p-supplement01',purpose='supplemental')
            data.update(stage='supplemental',cases=[case])
            atomic_json(directory/'campaign.json',data)
            atomic_json(directory/'frozen-manifest.json',data)
            (directory/'manifest.sha256').write_text(digest(data)+'\n')
            included,excluded=campaign_rows(directory,'supplemental',True)
            self.assertEqual(len(included),1);self.assertEqual(excluded,[])
            self.assertEqual(included[0]['cohort'],'supplemental')
            self.assertEqual(included[0]['case_id'],'s2-b03-p-supplement01')

    def test_modified_saved_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=self.fixture(Path(temp));data=check_frozen(directory)
            path=directory/data['cases'][0]['attempts'][0]['path']/'metrics.json'
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError,'evidence changed'):
                analyze(directory,allow_synthetic=True)

    def test_diagnosis_fallback_fractional_anchor_and_missingness(self):
        cfg=dict(rate=2,deadline_seconds=5,slo_ms=100,bin_seconds=20,min_samples=1,
                 stable_seconds=20,bin_max_bad_fraction=.05)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'requests.jsonl'
            rows=[dict(index=i,request_id=str(i),scheduled_utc=utc(100+i/2),
                       started_utc=utc(100+i/2+.001),completed_utc=utc(100+i/2+.011),
                       ok=True,correct=True) for i in range(10) if i!=5]
            path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            result=post_action(temp,cfg,dict(interval=[100,105],action_applied_seconds=None,diagnosis_seconds=2.1))
            self.assertEqual(result['anchor'],'diagnosis_seconds')
            self.assertEqual(result['expected_arrivals'],5)
            self.assertEqual(result['missing'],1)
            self.assertEqual(result['service_slo_violation_fraction'],.2)
            self.assertIn('request_arrivals_incomplete',result['errors'])
            result=post_action(temp,cfg,dict(interval=[100,105],action_applied_seconds=0,diagnosis_seconds=2.1))
            self.assertEqual(result['anchor'],'action_applied_seconds')

    def test_no_action_or_empty_post_window_is_null_not_zero(self):
        for metrics in ({'interval':[0,40]}, {'interval':[0,40],'action_applied_seconds':40},
                        {'interval':[0,40],'action_applied_seconds':-1}):
            result=post_action('/unused',{},metrics)
            self.assertIsNone(result['service_slo_violation_fraction'])
            self.assertTrue(result['errors'])

    def test_outputs_cannot_overwrite_or_write_into_campaigns(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);campaign=root/'campaign';campaign.mkdir()
            with self.assertRaisesRegex(ValueError,'outside input'):
                write_new_json(campaign/'new.json',{},[campaign])
            output=root/'report.json';write_new_json(output,{'notice':'posthoc'},[campaign])
            before=output.read_bytes()
            with self.assertRaises(FileExistsError):write_new_json(output,{},[campaign])
            self.assertEqual(output.read_bytes(),before)


if __name__=='__main__':unittest.main()
