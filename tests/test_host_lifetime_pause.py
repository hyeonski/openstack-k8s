import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/d) for d in ('evaluation','scripts','experiments')]
from lib.host_lifetime import host_deadline
from fresh_host_lifetime import validate_host_lifetime_policy, effective_host_deadline, DOCUMENT
from fresh_pause import pause_decision
from fresh_scenarios import horizon
from fresh_operations import case_time_gate, reservation, BedLedger
from fresh_evidence import utc
from fresh_fake import operational_fixture
import time


class HostLifetimePauseTests(unittest.TestCase):
    def profile(self):
        p=json.loads((ROOT/'config/graduation-evaluation-fresh-candidate-2026-10-26.json').read_text())
        p['operations']=operational_fixture(p['operations'])
        p['operations'].update(hard_stop_utc='2026-10-28T23:00:00+00:00',calendar_targets_only=True,uptime_targets_only=True,new_work_budget_krw=146234,credit_budget_krw=186234)
        p['operations']['preregistered_documents'].append(DOCUMENT)
        p['operations']['host_lifetime_policy']={'mode':'no-cloud-runtime-limit','scope':'existing-three-hosts-only','completion_target_utc':p['operations']['hard_stop_utc'],'time_policy':'cost-bounded-targets-only','preregistered_document':DOCUMENT,'document_sha256':hashlib.sha256((ROOT/DOCUMENT).read_bytes()).hexdigest()}
        return p

    def test_missing_or_zero_cloud_cap_needs_explicit_finite_authorization(self):
        for limit in [None,0,'0']:
            h={'max_run_seconds':limit}
            with self.assertRaises(RuntimeError):host_deadline(h,hard_stop='2026-10-28T23:00:00Z')
            self.assertEqual(host_deadline(h,hard_stop='2026-10-28T23:00:00Z',allow_unlimited=True),1793228400)
            with self.assertRaises(RuntimeError):host_deadline(h,allow_unlimited=True)

    def test_legacy_positive_cloud_cap_remains_earliest_bound(self):
        h={'last_start':'2026-10-27T00:00:00Z','max_run_seconds':36000}
        self.assertEqual(host_deadline(h,hard_stop='2026-10-28T23:00:00Z'),1793095200)
        for value in [-1,True,'invalid']:
            with self.assertRaises(RuntimeError):host_deadline({**h,'max_run_seconds':value})

    def test_no_timer_policy_is_hash_bound_and_rejects_remaining_cloud_timer(self):
        p=self.profile();validate_host_lifetime_policy(p,True)
        self.assertIsNone(effective_host_deadline(p,{'scheduling':{}}))
        for h in [{'max_run_seconds':36000},{'scheduling':{'terminationTime':'2026-10-27T12:00:00Z'}}]:
            with self.assertRaises(RuntimeError):effective_host_deadline(p,h)
        q=copy.deepcopy(p);q['operations']['cleanup_reserve_krw']=39999
        with self.assertRaises(ValueError):validate_host_lifetime_policy(q,True)
        q=copy.deepcopy(p);q['operations']['host_lifetime_policy']['document_sha256']='0'*64
        with self.assertRaises(ValueError):validate_host_lifetime_policy(q,True)

    def test_pause_is_at_case_boundary_and_resume_never_needs_cloud_rotation(self):
        self.assertFalse(pause_decision(100,500,900,200,100)['hold'])
        self.assertTrue(pause_decision(200,500,900,200,100)['hold'])
        self.assertTrue(pause_decision(500,500,900,0,0)['hold'])
        self.assertFalse(pause_decision(900,500,900,10000,600)['hold'])

    def test_explicit_time_targets_do_not_disable_cost_gate(self):
        p=self.profile()
        self.assertEqual(case_time_gate(p,now=1793401200),reservation(p))
        with tempfile.TemporaryDirectory() as root:
            p['operations']['bed_ledger_path']=str(Path(root)/'ledger.json')
            ledger=BedLedger(p);ledger.begin()
            ledger.data['sessions'][0]['started']=utc(time.time()-48*3600-60)
            ledger.gate(1)  # More than48h is traced, not a wall-clock veto.
            p['operations']['new_work_budget_krw']=100
            with self.assertRaisesRegex(RuntimeError,'cost estimate gate'):
                ledger.gate(1)

    def test_horizon_waits_for_utc_slew_without_relaxing_registered_H(self):
        for mono,wall in [([1200.01,1200.08],[2199.98,2200.06]),([1199.98,1200.08],[2200.01,2200.06])]:
            with tempfile.TemporaryDirectory() as root:
                p=Path(root);(p/'events.jsonl').write_text(json.dumps({'kind':'injection_applied','utc':'1970-01-01T00:16:40+00:00'})+'\n')
                ev=SimpleNamespace(directory=p,event=Mock(),state=Mock())
                with patch('fresh_scenarios.time.monotonic',side_effect=mono),patch('fresh_scenarios.time.time',side_effect=wall),patch('fresh_scenarios.time.sleep') as sleep:
                    horizon(ev,0,1200)
                self.assertGreaterEqual(sleep.call_args.args[0],.069)
                ev.event.assert_called_once_with('horizon_end')


if __name__=='__main__':unittest.main()
