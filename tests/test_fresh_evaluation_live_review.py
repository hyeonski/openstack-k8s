"""Live-path integration regressions; all external operations remain mocked."""
import hashlib
import copy
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import Mock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / d) for d in ('evaluation', 'scripts', 'experiments')]

from fresh_contract import digest
from fresh_evidence import Evidence
from fresh_scenarios import FreshS3, injection_guard, remote_tail_seconds, run_s4
from fresh_campaign import source_hashes, freeze, check_frozen, FreshCampaign, report, pilot_contract
from fresh_fake import synthetic_profile, FakeBackend
from fresh_evidence import utc
from fresh_analysis import event_metrics, judge, request_metrics, rows, read
from lib.state import atomic_json
import test_fresh_evaluation as fixtures


class LiveReviewTests(unittest.TestCase):
    fixture=fixtures.FreshTests.fixture
    campaign=fixtures.FreshTests.campaign

    def test_malformed_requests_close_and_seal_the_attempt(self):
        class Broken(FakeBackend):
            def execute(self, case, profile, ev):
                super().execute(case,profile,ev)
                with (ev.directory/'requests.jsonl').open('a') as stream:stream.write('truncated JSON\n')
        with tempfile.TemporaryDirectory() as root:
            directory=self.campaign(root,scenario='s2')
            campaign=FreshCampaign(directory,Broken());campaign.run(limit=1)
            case=check_frozen(directory)['cases'][0]
            self.assertEqual(case['status'],'finished')
            self.assertFalse(case['judgement']['trial_valid'])
            self.assertEqual(case['attempts'][0]['state'],'VERIFIED')
            self.assertTrue(case['attempts'][0]['evidence_sha256'])
            self.assertNotEqual(check_frozen(directory)['status'],'running')
            result=report(directory,allow_synthetic=True)
            self.assertFalse(result['run_results'][0]['trial_valid'])

    def test_s4_off_finishes_H_without_unpausing_unhealthy_machine(self):
        with tempfile.TemporaryDirectory() as root:
            ev=Evidence(Path(root)/'attempt');evidence=Path(root)/'legacy';evidence.mkdir()
            prep=Mock();runner=Mock();lab=Mock()
            before={'metadata':{'uid':'mhc','resourceVersion':'1'},'spec':{'maxUnhealthy':1}}
            during=copy.deepcopy(before);during['metadata']['annotations']={'cluster.x-k8s.io/paused':'true'}
            target={'node':'n1','node_uid':'node1','pod':'http','nova_id':'v1'}
            runner.check_preflight.return_value=({'environment_run_id':'env','run_id':'prep'},
                {'mhc_uid':'mhc'},evidence,target,['m1','m3'],10000)
            lab.obj.side_effect=[{'metadata':{'uid':'node1'}},before,during]
            prep.object.return_value={'status':{'containerStatuses':[{'imageID':'image'}]}}
            sampler=MagicMock();sampler.rows=[{'ok':True}]*3
            cfg=synthetic_profile(fixtures.profile())
            with patch('fresh_scenarios.EvaluationS4Preparation',return_value=prep), \
                 patch('fresh_scenarios.FreshS4Run',return_value=runner), \
                 patch('fresh_scenarios.RecoveryLab',return_value=lab), \
                 patch('fresh_scenarios.OpenLoopProbe',return_value=sampler), \
                 patch('fresh_scenarios.injection_guard'),patch('fresh_scenarios.nova'), \
                 patch('fresh_scenarios.nova_status',return_value={'status':'SHUTOFF','id':'v1'}), \
                 patch('fresh_scenarios.wait_for',side_effect=lambda fn,**kw:fn()), \
                 patch('fresh_scenarios.time.monotonic',side_effect=[0,100]), \
                 patch('fresh_scenarios.horizon'),patch('fresh_scenarios.restore_mhc') as restore:
                run_s4({'id':'off','mode':'off'},cfg,ev)
            restore.assert_not_called()
            self.assertNotIn('mhc_restored',read(ev.directory/'observations/contract.json'))

    def test_s4_off_cleanup_rescues_ready_node_before_unpause(self):
        from fresh_live import LiveBackend
        from fresh_scenarios import MHC_NAME
        with tempfile.TemporaryDirectory() as root:
            base=Path(root);ev=Evidence(base/'attempt');legacy=base/'legacy';legacy.mkdir()
            backend=LiveBackend.__new__(LiveBackend);backend.state=base/'state';backend.state.mkdir()
            case=dict(id='off',scenario='s4',mode='off',environment_run_id='env')
            target=dict(nova_id='v1',machine='m1',machine_uid='machine1',node='n1',node_uid='node1')
            record=dict(run_id='run',phase='completed',environment_run_id='env',fresh_attempt=str(ev.directory.resolve()),evidence=str(legacy),target=target)
            h=Mock();h.state_record.return_value=record;backend.helper=Mock(return_value=h)
            atomic_json(ev.directory/'prior-state.json',{'run_id':'previous'})
            before={'metadata':{'uid':'mhc','resourceVersion':'1'},'spec':{'maxUnhealthy':1}}
            mhc=copy.deepcopy(before);mhc['metadata']['annotations']={'cluster.x-k8s.io/paused':'true','openstack-k8s.dev/fresh-owner':'off'}
            atomic_json(ev.directory/'mhc-ownership.json',{'before':before,'owner':'off'})
            operations=[];ready=[False]
            def obj(kind,*args,**kw):
                if kind=='machine':return {'metadata':{'uid':'machine1'}}
                if kind=='node':
                    if ready[0]:operations.append('ready')
                    return {'metadata':{'uid':'node1'},'status':{'conditions':[{'type':'Ready','status':'True' if ready[0] else 'False'}]}}
                if kind=='machinehealthcheck':return copy.deepcopy(mhc)
                raise AssertionError(kind)
            def admin(*args,**kw):
                self.assertEqual(args,('server','start','v1'));operations.append('start');ready[0]=True
            def mutate(*args,**kw):
                self.assertIn(MHC_NAME,args)
                # A native controller would start deletion if this happens while unhealthy.
                if not ready[0]:raise AssertionError('unpause caused native deletion race')
                operations.append('unpause');mhc['metadata']['annotations']={}
            def cleanup(case):
                operations.append('cleanup')
                atomic_json(ev.directory/'cases'/case['id']/'cleanup-verification.json',{'checks':{'clean':True}})
            h.lab.obj.side_effect=obj;h.lab.admin.side_effect=admin;h.lab.k.side_effect=mutate
            h.lab.admin_json.return_value=[{'ID':'v1','Status':'SHUTOFF'}]
            h.cleanup_case.side_effect=cleanup
            def wait(fn,**kw):
                value=fn();self.assertTrue(value);return value
            with patch('graduation_s4_run.nova_status',return_value={'status':'ACTIVE'}),patch('graduation_recovery.wait_for',side_effect=wait):
                proof=backend.cleanup(case,fixtures.profile(),ev)
            self.assertTrue(proof['checks']['clean'])
            self.assertEqual(operations,['start','ready','unpause','cleanup'])
            self.assertEqual(read(ev.directory/'mhc-restored.json')['metadata']['annotations'],{})
            # Resume after an acknowledged/lost-response VM start must still await Ready.
            operations.clear();ready[0]=False
            mhc['metadata']['annotations']={'cluster.x-k8s.io/paused':'true','openstack-k8s.dev/fresh-owner':'off'}
            h.lab.admin_json.return_value=[{'ID':'v1','Status':'ACTIVE'}]
            def becomes_ready(fn,**kw):
                ready[0]=True;return wait(fn,**kw)
            with patch('graduation_s4_run.nova_status',return_value={'status':'ACTIVE'}),patch('graduation_recovery.wait_for',side_effect=becomes_ready):
                backend.cleanup(case,fixtures.profile(),ev)
            self.assertEqual(operations,['ready','unpause','cleanup'])

    def test_seed_unavailable_is_unknown_but_confirmed_corruption_is_unsafe(self):
        with tempfile.TemporaryDirectory() as root:
            p,c=self.fixture(root,'s3','P3600');path=Path(root)/'observations/contract.json'
            raw=read(path);raw['seed_after']=None;atomic_json(path,raw)
            result=judge(root,c,p)
            self.assertFalse(result['trial_valid'])
            self.assertIn('seed_after_unavailable',result['missing'])
            self.assertIsNone(result['safety']);self.assertIsNone(result['metrics']['safe_recovered'])
            raw['seed_after']=[];atomic_json(path,raw)
            result=judge(root,c,p)
            self.assertFalse(result['safety'])
        with tempfile.TemporaryDirectory() as root:
            p,c=self.fixture(root,'s3','M3600')
            self.assertTrue(judge(root,c,p)['trial_valid'])

    def test_bin_allows_registered_outlier_count_and_still_requires_p95(self):
        cfg=dict(rate=10,bin_seconds=10,min_samples=100,deadline_seconds=5,
                 slo_ms=100,stable_seconds=10,bin_max_bad_fraction=.01)
        data=[dict(request_id=str(i),scheduled_utc=utc(i/10),started_utc=utc(i/10),
                   completed_utc=utc(i/10+(.2 if i==0 else .01)),ok=True,correct=True) for i in range(100)]
        result=request_metrics(data,cfg,0,10)
        self.assertTrue(result['recovered']);self.assertEqual(result['failure_rate'],0)
        self.assertEqual(result['service_slo_violation_fraction'],.01)
        data[1]['completed_utc']=utc(.3)
        self.assertFalse(request_metrics(data,cfg,0,10)['recovered'])
        cfg['bin_max_bad_fraction']=.5
        for i in range(10):data[i]['completed_utc']=utc(i/10+.2)
        self.assertFalse(request_metrics(data,cfg,0,10)['recovered'])

    def test_remote_tail_keeps_slow_receiver_clock_arrivals(self):
        cfg=synthetic_profile(fixtures.profile())['s2'];cfg['max_clock_offset_seconds']=2
        def trace(tail):
            return [dict(request_id=str(i),index=i,scheduled_utc=utc(100-1.5+i/2),
                         started_utc=utc(100-1.5+i/2),completed_utc=utc(100-1.5+i/2+.01),ok=True,correct=True)
                    for i in range(int((40+tail)*2))]
        self.assertIn('request_arrivals_incomplete',request_metrics(trace(0),cfg,100,140)['errors'])
        self.assertNotIn('request_arrivals_incomplete',request_metrics(trace(remote_tail_seconds(cfg)),cfg,100,140)['errors'])

    def test_v1_own_slo_and_relative_policy_condition_both_apply(self):
        with tempfile.TemporaryDirectory() as root:
            p,c=self.fixture(root,'s1','V1')
            p['s1']['slo_ms']=1 # Heavy workload SLO must not determine the V1 condition.
            self.assertEqual(judge(root,c,p)['v1_outcome'],'held')
            data=rows(Path(root)/'requests.jsonl')
            for row in data:row['latency_ms']=20 # Own absolute SLO still passes, baseline ratio does not.
            (Path(root)/'requests.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in data))
            self.assertEqual(judge(root,c,p)['v1_outcome'],'condition_not_realized')

    def test_pilot_contract_is_scenario_specific_but_includes_measurement(self):
        p=fixtures.profile();q=copy.deepcopy(p)
        q['s2']['slo_ms']=200
        self.assertEqual(pilot_contract(p,'s1'),pilot_contract(q,'s1'))
        self.assertNotEqual(pilot_contract(p,'s2'),pilot_contract(q,'s2'))
        q=copy.deepcopy(p);q['v1_selected']={'cpu_workers':4,'workload_rounds':10000}
        self.assertNotEqual(pilot_contract(p,'s1'),pilot_contract(q,'s1'))

    def test_paired_report_exposes_harm_when_control_does_not_recover_and_A_holds(self):
        class HoldA(FakeBackend):
            def execute(self,case,profile,ev):
                super().execute(case,profile,ev)
                if case['mode']=='A':
                    path=ev.directory/'events.jsonl'
                    path.write_text(''.join(json.dumps(e)+'\n' for e in rows(path) if e['kind'] not in ('action_requested','action_applied')))
                    raw=read(ev.directory/'observations/contract.json');raw['service_after']=raw['service_before']
                    atomic_json(ev.directory/'observations/contract.json',raw)
        with tempfile.TemporaryDirectory() as root:
            directory=self.campaign(root,scenario='s1');FreshCampaign(directory,HoldA()).run()
            result=report(directory,allow_synthetic=True)
            pm=next(c for c in result['paired_contrasts'] if c['arms']==['P','M'])
            self.assertEqual([r['recovered'] for r in pm['arm_results']],[True,False])
            self.assertLess(pm['violation_seconds_lower_bound_difference'],0)
            pa=next(c for c in result['paired_contrasts'] if c['arms']==['P','A'])
            self.assertTrue(pa['trial_valid']);self.assertFalse(pa['arm_results'][1]['intervention_delivered'])
            self.assertTrue(any('assignment-policy' in text for text in pa['claim_limitations']))

    def test_event_metrics_keep_absent_cross_clock_and_late_events_unknown(self):
        def event(kind, seconds, clock='same'):
            return dict(kind=kind, event_id=kind + str(seconds), utc=utc(seconds),
                        monotonic_ns=int(seconds * 1e9), clock_id=clock)
        injected = event('injection_applied', 10)
        events = [event('diagnosis_completed', 14), event('action_requested', 15),
                  event('action_applied', 18), event('action_requested', 20),
                  event('action_applied', 23), event('fence_confirmed', 60),
                  event('symptom_detected', 12, 'other')]
        metrics = event_metrics(events, injected, 40)
        self.assertEqual(metrics['diagnosis_seconds'], 4)
        self.assertEqual(metrics['action_start_seconds'], 5)
        self.assertEqual(metrics['action_applied_seconds'], 8)
        self.assertIsNone(metrics['detection_seconds'])
        self.assertIsNone(metrics['node_not_ready_seconds'])
        self.assertIsNone(metrics['fence_seconds'])
        self.assertEqual(len(metrics['observed_event_timeline']), 7)

    def test_host_budget_is_rechecked_after_long_preparation(self):
        profile = {'operations': {'last_injection_utc': utc(10000), 'cleanup_seconds': 900}}
        environment = {'final_hosts': {'compute': {'last_start': utc(0), 'max_run_seconds': 5000}}}
        with patch('fresh_scenarios.time.time', return_value=2000):
            injection_guard(profile, 1200, environment)
        with patch('fresh_scenarios.time.time', return_value=3000):
            with self.assertRaisesRegex(RuntimeError, 'no longer covers H'):
                injection_guard(profile, 1200, environment)
        with patch('fresh_scenarios.time.time', return_value=2000):
            with self.assertRaisesRegex(RuntimeError, 'evidence unavailable'):
                injection_guard(profile, 1200, {})

    def test_pilot_reference_is_not_overwritten_by_previous_cohort(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = synthetic_profile(json.loads((ROOT / 'config/graduation-evaluation-fresh.json').read_text()))
            profile['operations']['impact_analysis'] = dict(judgement_semantics_changed=False,
                policy_changed=False, reason='reference regression only', affected_scenarios=['s2'])
            path = root / 'profile.json'
            path.write_text(json.dumps(profile))
            pilot = freeze(path, root / 'pilot', 'preparation', synthetic=True)
            previous = freeze(path, root / 'previous', 'main', synthetic=True)
            main = freeze(path, root / 'main', 'main', synthetic=True,
                          pilot_campaign=pilot, previous_campaign=previous)
            manifest = check_frozen(main)
            self.assertEqual(manifest['pilot_campaign_id'], check_frozen(pilot)['id'])
            self.assertNotEqual(manifest['pilot_campaign_id'], check_frozen(previous)['id'])

    def test_source_snapshot_excludes_ignored_overrides_and_generated_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', directory], check=True)
            (root / '.gitignore').write_text('config/environments/local.env\nkolla/**/generated/\n')
            public = root / 'config/environments/public.env'
            public.parent.mkdir(parents=True)
            public.write_text('ENVIRONMENT_NAME=example\n')
            private = public.with_name('local.env')
            private.write_text('SECRET=never-copy\n')
            generated = root / 'kolla/example/generated/passwords.yaml'
            generated.parent.mkdir(parents=True)
            generated.write_text('password: never-copy\n')
            hashes = source_hashes(root)
            self.assertIn('config/environments/public.env', hashes)
            self.assertNotIn('config/environments/local.env', hashes)
            self.assertNotIn('kolla/example/generated/passwords.yaml', hashes)

    def test_s3_real_preparation_reaches_probe_with_seed_and_mhc_digests(self):
        """Exercise finish(), not just the recovery hook or hand-written fake evidence."""
        case = dict(seed=20261026, block='b01', purpose='main', mode='P3600')
        seed = digest({k: case[k] for k in ('seed', 'block', 'purpose')} | {'scenario': 's3'})
        committed = [{'id': i, 'value': hashlib.md5((str(i) + seed).encode()).hexdigest()}
                     for i in range(1, 1001)]
        mhc_specs = [{'maxUnhealthy': 1}, {'maxUnhealthy': 2}]

        class ProbeReached(Exception):
            pass

        with tempfile.TemporaryDirectory() as directory:
            runner = FreshS3.__new__(FreshS3)
            runner.case = case
            runner.profile = {'s3': {'deadline_seconds': 5, 'horizon_seconds': 600, 'rate': 1},
                              'timers': {'mhc_policy': {'s3_specs': list(reversed(mhc_specs))}}}
            runner.ev = Evidence(directory)
            runner.record = {'run_id': 'owned-run', 'source': {'machine': 'source', 'machine_uid': 'm1'}}
            runner.start = Mock(return_value=[{'port': {'network_id': 'net'}}])
            runner.client = Mock(ns='cluster')
            runner.client.get.side_effect = [
                {'items': [{'metadata': {'labels': {'node-role.kubernetes.io/control-plane': ''}}}]},
                {'items': [{'spec': spec} for spec in mhc_specs]}]
            runner.binding = Mock(return_value={})
            runner.admin_json = Mock(side_effect=[[{'ID': 'router-port'}], {'device_id': 'router'}])
            runner.obj = Mock(side_effect=[{'metadata': {'annotations': {}}},
                {'metadata': {'uid': 'm1', 'annotations': {'cluster.x-k8s.io/skip-remediation': 'owned-run'}}}, {}])
            for name in ('write', 'controller_policy', 'build_database', 'k', 'save'):
                setattr(runner, name, Mock())
            runner.sql = Mock(side_effect=['', json.dumps(committed), '1000:db-checksum',
                                          'on:on:on:/var/lib/postgresql/data/pgdata'])
            runner.sample = Mock(return_value=[{'ok': True}] * 30)
            runner.guest = Mock(return_value='controller manifest')
            with patch('fresh_scenarios.OpenLoopProbe', side_effect=ProbeReached), self.assertRaises(ProbeReached):
                runner.finish()
            self.assertIn(seed, runner.sql.call_args_list[0].args[0])
            runner.write.assert_any_call('baseline-ready', committed_digest='1000:db-checksum',
                                         durability='on:on:on:/var/lib/postgresql/data/pgdata')


if __name__ == '__main__':
    unittest.main()
