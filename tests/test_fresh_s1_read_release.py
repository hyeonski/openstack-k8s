import json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/x) for x in ('evaluation','scripts','experiments')]
from fresh_s1_read_release import KIND, ORIGINS, PLAN, validate_scope, validate_delta
from fresh_transport_release import select_cases,supplemental_plan
from fresh_live import LiveBackend
from fresh_evidence import Evidence

class S1ReadReleaseTests(unittest.TestCase):
    def authorization(self):
        return dict(kind=KIND,remaining_main_ids=[],supplemental_origins=ORIGINS,supplemental_plan=PLAN,
                    supplemental_limit=8,boundary_case='s1-b02-a-supplement01',human_instruction='review operational invalid and run separate last supplement')

    def test_sealed_s1_supplement01_is_never_selected_again(self):
        a=self.authorization();validate_scope(a)
        profile=json.loads((ROOT/'config/graduation-evaluation-fresh.json').read_text())
        cases=[select_cases(profile,a,next(c['scenario'] for c in profile['cases'] if c['id']==entry['origin']),
                            'supplemental',origin=entry['origin'])[0] for entry in PLAN]
        self.assertEqual([c['id'] for c in cases],[p['id'] for p in PLAN])
        self.assertEqual(cases[-1]['id'],'s1-b02-a-supplement02')
        self.assertNotIn('s1-b02-a-supplement01',[c['id'] for c in cases])
        self.assertEqual(cases[-1]['purpose'],'supplemental')
        for changes in ({'remaining_main_ids':['s4-b03-off']},{'supplemental_plan':PLAN[::-1]},
                        {'supplemental_limit':9},{'human_instruction':''}):
            with self.assertRaises(ValueError):validate_scope({**a,**changes})

    def test_legacy_supplement_id_is_unchanged(self):
        self.assertEqual(supplemental_plan({'supplemental_origins':['s1-b02-a']}),
                         [dict(origin='s1-b02-a',id='s1-b02-a-supplement01',order=38)])

    def test_scientific_edits_are_rejected(self):
        base={'evaluation/fresh_collection.py':'old','evaluation/fresh_analysis.py':'science'}
        revised={**base,'evaluation/fresh_collection.py':'new'}
        validate_delta(base,revised,['evaluation/fresh_collection.py'])
        revised['evaluation/fresh_analysis.py']='changed'
        with self.assertRaises(ValueError):validate_delta(base,revised,list(base))

    def test_cleanup_repairs_transport_before_any_fixture_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            ev=Evidence(root);backend=LiveBackend.__new__(LiveBackend);backend.state=Path(root)
            backend.configure_reads=Mock();h=Mock();h.state_record.return_value=None;backend.helper=Mock(return_value=h)
            order=[]
            def call(*a,**kw):order.append('transport');raise RuntimeError('cannot restore local tunnel')
            h.call.side_effect=call
            with patch('fresh_worker_quiescence.wait_worker_quiescent'),self.assertRaisesRegex(RuntimeError,'cannot restore'):
                backend.cleanup({'id':'fixture','scenario':'s1'},{'operations':{'stability':True}},ev)
            self.assertEqual(order,['transport']);h.cleanup_case.assert_not_called();h.make.assert_not_called()

if __name__=='__main__':unittest.main()
