import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'evaluation'))
from fresh_credit import forward_credit

class ForwardCreditTests(unittest.TestCase):
    def fixture(self,root):
        p=Path(root)/'credit.json'
        p.write_text(json.dumps(dict(recorded_utc=1000,latest_credit=dict(total_krw=435523,used_krw=298540,
            displayed_remaining_krw=136983,cash_overage_authorized=False,paid_conversion_authorized=False),
            historical_ledger=dict(estimated_cost_krw=999999),
            forward_plan=dict(cleanup_reserve_krw=40000,other_uncertainty_reserve_krw=20000),
            previous_credit_for_audit=dict(expires_utc='2026-11-18T15:00:00Z'))))
        return {'operations':{'cost_estimate':{'bed_hour_krw':2400,'calendar_day_krw':6400},
            'stability':{'credit_reference':{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}}}}
    def test_latest_balance_forward_only_with_unknown_lag_sensitivity(self):
        with tempfile.TemporaryDirectory() as root:
            profile=self.fixture(root);row=forward_credit(profile,3600,now=4600)
            rate=2666.6666666666665
            self.assertEqual(row['displayed_remaining_krw'],136983)
            self.assertFalse(row['historical_ledger_subtracted'])
            self.assertAlmostEqual(row['margin_krw'],136983-60000-14*rate)
            self.assertFalse(row['unposted_assumption_confirmed'])
            self.assertEqual([r['assumed_hours'] for r in row['sensitivity']],[0,6,12])
    def test_future_and_idle_costs_can_exhaust_the_reserve(self):
        with tempfile.TemporaryDirectory() as root:
            profile=self.fixture(root)
            self.assertGreater(forward_credit(profile,0,now=1000)['margin_krw'],0)
            self.assertLess(forward_credit(profile,24*3600,now=1000)['margin_krw'],0)
            self.assertLess(forward_credit(profile,0,now=1000+24*3600)['margin_krw'],0)
    def test_evidence_tamper_and_negative_reservation_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            profile=self.fixture(root)
            with self.assertRaises(ValueError):forward_credit(profile,-1,now=1000)
            Path(profile['operations']['stability']['credit_reference']['path']).write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'evidence changed'):forward_credit(profile,now=1000)
    def test_legacy_budget_unchanged_without_stability_reference(self):
        self.assertIsNone(forward_credit({'operations':{}}))
if __name__=='__main__':unittest.main()
