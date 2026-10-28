import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'evaluation'))
from fresh_inventory_release import KIND,MAIN,SUPPLEMENTS,validate_scope,validate_delta

class InventoryReleaseTests(unittest.TestCase):
    def test_failed_first_attempt_cannot_be_replayed_or_supplements_added(self):
        a=dict(kind=KIND,remaining_main_ids=MAIN,supplemental_origins=SUPPLEMENTS,
            supplemental_limit=8,boundary_case='s4-b02-off',human_instruction='repair, verify, then resume')
        validate_scope(a)
        for changes in ({'remaining_main_ids':['s4-b02-off',*MAIN]},
                        {'supplemental_origins':[*SUPPLEMENTS,'s4-b02-off']},
                        {'boundary_case':'s4-b02-on'},{'human_instruction':''}):
            with self.assertRaises(ValueError):validate_scope({**a,**changes})
    def test_scientific_edits_and_undeclared_changes_block_continuation(self):
        base={'scripts/workload-inventory.sh':'old','evaluation/fresh_analysis.py':'science'}
        revised={**base,'scripts/workload-inventory.sh':'new'}
        self.assertEqual(validate_delta(base,revised,['scripts/workload-inventory.sh']),{'scripts/workload-inventory.sh'})
        with self.assertRaises(ValueError):validate_delta(base,revised,[])
        revised['evaluation/fresh_analysis.py']='changed'
        with self.assertRaises(ValueError):validate_delta(base,revised,list(base))

if __name__=='__main__':unittest.main()
