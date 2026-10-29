import json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/x) for x in ('evaluation','scripts','experiments')]
from fresh_dns_release import KIND,ORIGINS,PLAN,validate_scope,validate_delta,validate_probe_hook
from fresh_transport_release import select_cases

class DNSReleaseTests(unittest.TestCase):
    def authorization(self):
        return dict(kind=KIND,remaining_main_ids=[],supplemental_origins=ORIGINS,supplemental_plan=PLAN,supplemental_limit=1,boundary_case='s3-b02-m3600-supplement02',human_instruction='preserve invalid; separate final supplement')

    def test_only_pending_origin_selected_with_fresh_id_and_original_science(self):
        a=self.authorization();validate_scope(a);p=json.loads((ROOT/'config/graduation-evaluation-fresh.json').read_text())
        selected=select_cases(p,a,'s3','supplemental',origin=ORIGINS[0])
        self.assertEqual(len(selected),1);self.assertEqual(selected[0]['id'],'s3-b02-m3600-supplement03')
        self.assertEqual(selected[0]['order'],48)
        original=next(c for c in p['cases'] if c['id']==ORIGINS[0])
        for key in ('scenario','mode'):self.assertEqual(selected[0][key],original[key])

    def test_valid_origins_originals_and_immutable_failed_ids_cannot_be_replayed(self):
        for change in ({'remaining_main_ids':['s3-b02-m3600']},{'supplemental_limit':2},
                       {'supplemental_origins':['s1-b02-a']},{'supplemental_plan':[dict(origin=ORIGINS[0],id=ORIGINS[0]+'-supplement02',order=48)]}):
            with self.assertRaises(ValueError):validate_scope({**self.authorization(),**change})

    def test_gate_only_delta_prohibits_scenario_fault_load_and_analysis_changes(self):
        allowed='evaluation/fresh_dns_release.py';base={'evaluation/fresh_scenarios.py':'same','evaluation/fresh_analysis.py':'same','evaluation/fresh_contract.py':'same'}
        current={**base,allowed:'gate'};validate_delta(base,current,[allowed])
        for name in base:
            edited={**current,name:'changed'}
            with self.assertRaises(ValueError):validate_delta(base,edited,[allowed,name])
        with self.assertRaises(ValueError):validate_delta(base,current,[])

    def test_original_readiness_criterion_and_timeout_cannot_change(self):
        old='def probe(client, path, run_id, owner_id=None):\n    timeout=360\n    return timeout\n'
        new=old.replace('    timeout=360','    if os.environ.get("FRESH_READ_CONTEXT"):\n        from lib.neutron_members import reconcile_before_probe\n        reconcile_before_probe(client, path)\n    timeout=360')
        validate_probe_hook(old,new)
        with self.assertRaises(ValueError):validate_probe_hook(old,new.replace('timeout=360','timeout=600'))

if __name__=='__main__':unittest.main()
