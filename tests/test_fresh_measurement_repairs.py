"""Regression tests for the observed UTC slew and slow S4 capacity collection."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/d) for d in ('evaluation','scripts','experiments')]
from fresh_evidence import OpenLoopProbe, wait_for_arrival, epoch
from fresh_scenarios import FreshS4Run
from fresh_failure_policy import next_action


class MeasurementRepairs(unittest.TestCase):
    def test_arrival_waits_for_both_clocks_and_rechecks_early_wake(self):
        for wall,mono in [(99.98,100.0),(100.02,99.99)]:
            clock={'wall':wall,'mono':mono};sleeps=[]
            def sleep(seconds):
                # First wake is early, as a signal-interrupted sleep can be.
                elapsed=seconds/2 if not sleeps else seconds
                sleeps.append(seconds);clock['wall']+=elapsed;clock['mono']+=elapsed
            with patch('fresh_evidence.time.time',side_effect=lambda:clock['wall']),patch('fresh_evidence.time.monotonic',side_effect=lambda:clock['mono']),patch('fresh_evidence.time.sleep',side_effect=sleep):
                wait_for_arrival(100,100)
            self.assertGreaterEqual(clock['wall'],100);self.assertGreaterEqual(clock['mono'],100)
            self.assertGreaterEqual(len(sleeps),2)

    def test_real_sampler_keeps_arrivals_ordered_during_twenty_ms_wall_slew(self):
        wall_now=time.time;mono_now=time.monotonic;start=mono_now()
        def slewed():return wall_now()-min(.020,(mono_now()-start)*.5)
        with tempfile.TemporaryDirectory() as root,patch('fresh_evidence.time.time',side_effect=slewed):
            with OpenLoopProbe(Path(root)/'requests.jsonl',lambda:{'ok':True},500,.08,1) as sampler:pass
            self.assertIsNone(sampler.error);self.assertEqual(len(sampler.rows),40)
            for row in sampler.rows:
                self.assertGreaterEqual(epoch(row['started_utc']),epoch(row['scheduled_utc'])-.001)
                self.assertGreaterEqual(row['started_monotonic'],row['scheduled_monotonic'])

    def test_horizon_includes_arrivals_until_both_registered_ends(self):
        sampler=OpenLoopProbe('/unused',lambda:{'ok':True},1,20,1)
        sampler.until=110;sampler.until_utc=1010
        self.assertFalse(sampler.outside_horizon(1009.99,110.01))
        self.assertFalse(sampler.outside_horizon(1010.01,109.99))
        self.assertTrue(sampler.outside_horizon(1010,110))

    def test_capacity_reads_overlap_and_preserve_per_query_error_and_timing(self):
        runner=FreshS4Run.__new__(FreshS4Run);runner.preparation=Mock(md_name='workers')
        runner.client=Mock(ns='ns',cluster='cluster');lock=threading.Lock();active=0;peak=0
        def get(*args):
            nonlocal active,peak
            with lock:active+=1;peak=max(peak,active)
            time.sleep(.01)
            with lock:active-=1
            if args[1]=='events':raise RuntimeError('connection reset')
            return {'resource':args[1]}
        runner.client.get.side_effect=get
        with tempfile.TemporaryDirectory() as root,patch('fresh_scenarios.nova',return_value=[]):
            snap=runner.snapshot(Path(root),0)
            self.assertEqual(json.loads((Path(root)/'0000.json').read_text()),snap)
        self.assertGreater(peak,1);self.assertLessEqual(peak,6)
        self.assertEqual(set(snap['collection_timing']),{'md','mhc','machines','osmachines','nodes','pods','deployment','events','nova'})
        self.assertEqual(set(snap['errors']),{'events'})
        self.assertNotIn('events',snap);self.assertIn('collected_utc',snap)

    def test_binding_and_probe_creation_are_once_per_replacement_not_per_poll(self):
        runner=FreshS4Run.__new__(FreshS4Run);runner.create_probe=Mock();lab=Mock()
        lab.binding.side_effect=[{'node':'new'},{'node':'other'}]
        self.assertEqual(runner.replacement_evidence({},'new',lab),{'node':'new'})
        self.assertEqual(runner.replacement_evidence({},'new',lab),{'node':'new'})
        self.assertEqual(lab.binding.call_count,1);self.assertEqual(runner.create_probe.call_count,1)
        self.assertEqual(runner.replacement_evidence({},'other',lab),{'node':'other'})
        self.assertEqual(lab.binding.call_count,2)

    def test_measurement_pause_does_not_hide_cleanup_safety_or_cost_failure(self):
        row={'trial_valid':False,'safety':True,'cleanup':True,'missing':['request_time_reversed']}
        self.assertEqual(next_action(row,cleanup_verified=True,budget_available=True),'pause_for_measurement_repair')
        self.assertEqual(next_action(row,cleanup_verified=False,budget_available=True),'resolve_owned_cleanup')
        self.assertEqual(next_action(row,cleanup_verified=True,budget_available=False),'safe_shutdown')
        self.assertEqual(next_action({**row,'safety':False},cleanup_verified=True,budget_available=True),'safe_shutdown')
        self.assertEqual(next_action({**row,'missing':['foreign_resource']},cleanup_verified=True,budget_available=True),'investigate_before_next_case')
        self.assertEqual(next_action({**row,'trial_valid':True,'recovered':False},cleanup_verified=True,budget_available=True),'record_result')


if __name__=='__main__':unittest.main()
