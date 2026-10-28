import json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/x) for x in ('evaluation','scripts','experiments')]
from fresh_s3_capture_release import KIND,ORIGINS,PLAN,validate_scope,validate_delta
from fresh_transport_release import select_cases

class S3CaptureReleaseTests(unittest.TestCase):
    def authorization(self):
        return dict(kind=KIND,remaining_main_ids=[],supplemental_origins=ORIGINS,supplemental_plan=PLAN,supplemental_limit=7,boundary_case='s3-b02-m3600-supplement01',human_instruction='repair operational failure; preserve invalid; separate final supplement')

    def test_s2_valid_is_not_replayed_and_s3_invalid_has_distinct_final_id(self):
        a=self.authorization();validate_scope(a);profile=json.loads((ROOT/'config/graduation-evaluation-fresh.json').read_text())
        selected=[select_cases(profile,a,p['origin'][:2],'supplemental',origin=p['origin'])[0] for p in PLAN]
        self.assertEqual(selected[-1]['id'],'s3-b02-m3600-supplement02')
        self.assertEqual(selected[-2]['id'],'s1-b02-a-supplement02')
        self.assertTrue(all(c['purpose']=='supplemental' for c in selected))
        self.assertNotIn('s2-b03-p-supplement01',[c['id'] for c in selected])

    def test_old_invalid_id_and_extra_retries_are_rejected(self):
        for change in ({'remaining_main_ids':['s3-b02-m3600']},{'supplemental_limit':8},
                       {'supplemental_plan':PLAN[:-1]},{'supplemental_origins':[*ORIGINS,'s2-b03-p']}):
            with self.assertRaises(ValueError):validate_scope({**self.authorization(),**change})

    def test_scientific_or_undeclared_edits_are_rejected(self):
        base={'evaluation/fresh_scenarios.py':'old','evaluation/fresh_analysis.py':'fixed'}
        revised={**base,'evaluation/fresh_scenarios.py':'read-only repair'}
        validate_delta(base,revised,['evaluation/fresh_scenarios.py'])
        with self.assertRaises(ValueError):validate_delta(base,revised,[])
        revised['evaluation/fresh_analysis.py']='policy changed'
        with self.assertRaises(ValueError):validate_delta(base,revised,list(base))

    def test_explicit_order_keeps_prior_pending_cases_before_new_retry(self):
        self.assertEqual([p['order'] for p in PLAN],list(range(41,48)))
        self.assertEqual(len({p['id'] for p in PLAN}),7)

if __name__=='__main__':unittest.main()
