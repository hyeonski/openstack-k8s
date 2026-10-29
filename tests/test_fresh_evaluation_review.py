"""Agreement audit regressions; all API and mutation paths are fake/mocked."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/d) for d in ('evaluation','scripts','experiments')]
import test_fresh_evaluation as fixtures
from fresh_analysis import judge, read, rows, uploader_metrics
from fresh_campaign import FreshCampaign, check_frozen, source_hashes
from fresh_contract import validate, SUPPORTED_FAULTS, SUPPORTED_FIXTURE
from fresh_evidence import Evidence, OpenLoopProbe, utc
from fresh_fake import FakeBackend, synthetic_profile
from fresh_scenarios import FreshS1, FreshS2, RemoteProbe
from lib.state import atomic_json


class AgreementReviewTests(unittest.TestCase):
    fixture=fixtures.FreshTests.fixture
    campaign=fixtures.FreshTests.campaign

    def test_schema_rejects_malformed_types_nonfinite_and_incomplete_pilot_pairs(self):
        changes=[lambda p:p['s1'].update(bin_seconds='ten'),lambda p:p['s2'].update(horizon_seconds=600.5),
                 lambda p:p['s3'].update(rate=float('nan')),lambda p:p.update(operations=None),
                 lambda p:p['cases'][0].update(id=[]),lambda p:p['cases'][0].update(depends_on='unknown'),
                 lambda p:p['cases'][17].update(mode='P')]
        # Explicitly damage the S2 M pilot rather than depend on a positional case index.
        changes[-1]=lambda p:next(c for c in p['cases'] if c['scenario']=='s2' and c['purpose']=='pilot' and c['mode']=='M').update(mode='P')
        for change in changes:
            p=fixtures.profile();change(p)
            with self.subTest(change=change),self.assertRaises(ValueError):validate(p)

    def test_complete_live_schema_requires_concrete_fixture_and_actual_mhc_policy(self):
        p=fixtures.profile()
        for scenario in ('s1','s2','s3','s4'):
            p[scenario].update(horizon_seconds=900 if scenario=='s1' else 600,stable_seconds=30,bin_seconds=10,min_samples=5,deadline_seconds=5,slo_ms=100,bin_max_bad_fraction=0)
        p['s3']['evidence_timeout_seconds']=60
        p['v1_condition']={'slo_ms':100,'bin_max_bad_fraction':0,'baseline_p95_ratio':1.5}
        p.update(readiness='confirmed',fault=SUPPORTED_FAULTS,initial_fixture=copy.deepcopy(SUPPORTED_FIXTURE),
                 v1_candidates=[{'cpu_workers':4,'workload_rounds':10000}],v1_selected={'cpu_workers':4,'workload_rounds':10000})
        p['s1']['max_clock_offset_seconds']=1;p['s2']['max_clock_offset_seconds']=1
        p['s2']['uploader_seconds']=1200;p['timers']['mhc_policy']={'s3_specs':[]}
        p['operations'].update(operator='offline schema only',budget_seconds=100000,cleanup_seconds=900,last_injection_utc='2026-10-27T00:00:00Z',environment_override='/unused',execution_checkout=str(ROOT),artifact_root='/unused')
        candidate=json.loads((ROOT/'config/graduation-evaluation-fresh-candidate-2026-10-26.json').read_text())
        from fresh_fake import operational_fixture
        p['operations']=operational_fixture(candidate['operations'])
        p['analysis']=candidate['analysis'];p['host_headroom_seconds']=10800
        self.assertEqual(validate(p,live=True)['main'],29)
        p['initial_fixture']['s4_capacity']['workers']=3
        with self.assertRaisesRegex(ValueError,'initial fixture'):validate(p,live=True)

    def test_same_worker_restart_ignores_observation_time_and_is_namespaced(self):
        r=FreshS1.__new__(FreshS1);r.case={'mode':'A'};r.ev=Mock();r.s1=Mock();r.write=Mock()
        before=dict(time='before',pod_uid='p',node='n',nova_id='v',image_id='image',container_id='c',restart_count=0,machine_uid='m',service_uid='s')
        r.s1.verify.return_value={**before,'time':'later'}
        r.s1.obj.return_value={'metadata':{'uid':'dep','resourceVersion':'1'},'spec':{'template':{'metadata':{},'spec':{'nodeSelector':{'kubernetes.io/hostname':'n'}}}}}
        with tempfile.TemporaryDirectory() as root:
            r.ev.directory=Path(root)
            r.move_service({'service_before':before,'run_id':'run','automatic_trigger':True})
        self.assertEqual(r.s1.k.call_args.args[:5],('-n','graduation-s1','patch','deployment','http'))
        r.s1.k.assert_called_once()

    def test_real_policy_defer_remains_a_hold_for_all_S1_arms(self):
        for mode in ('P','M','A','V1'):
            r=FreshS1.__new__(FreshS1);r.case={'mode':mode};r.ev=Mock();r.s1=Mock();r.write=Mock()
            record={'phase':'deferred','defer_reason':'sustained_service_and_host_evidence_missing','service_before':{'pod':'http'}}
            with patch('graduation_evaluation_case.EvaluationS1.observe_contention',side_effect=RuntimeError('deferred')):
                r.observe_contention(record,None,None,None,None,Mock())
            if mode!='M':
                r.move_service(record);r.s1.k.assert_not_called()

    def test_S2_diagnosis_keeps_cross_layer_guards(self):
        metric=dict(complete=True,failures=1,p95_ms=200,upload_bytes=1024)
        before={'monotonic':0,'hosts':{'h':{}},'qdisc':{'bytes':0,'overlimits':0}}
        after={'monotonic':60,'hosts':{'h':{}},'qdisc':{'bytes':150_000_000,'overlimits':10}}
        with patch('lib.runtime.host_cpu_utilization',return_value=.2):
            self.assertTrue(FreshS2.contention_diagnosis(100,metric,before,after)['trigger'])
            after['qdisc']['overlimits']=0
            self.assertFalse(FreshS2.contention_diagnosis(100,metric,before,after)['trigger'])
        after['qdisc']['overlimits']=10
        with patch('lib.runtime.host_cpu_utilization',return_value=.9):
            self.assertFalse(FreshS2.contention_diagnosis(100,metric,before,after)['trigger'])

    def test_probe_preserves_generator_clock_and_arrival_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            result={'ok':True,'clock_id':'unrelated-clock','started_utc':'invalid','request_id':'forged','completed_utc':'invalid'}
            with OpenLoopProbe(Path(root)/'requests.jsonl',lambda:result,1000,.003,.1):pass
            requests=rows(Path(root)/'requests.jsonl')
            self.assertEqual(len(requests),3)
            self.assertTrue(all(r['clock_id'].startswith('probe:') for r in requests))
            self.assertEqual({r['request_id'] for r in requests},{'0','1','2'})

    def test_uploader_bounds_exclude_late_bytes_and_detect_observer_gaps(self):
        samples=[{'utc':utc(t),'progress':{'bytes':t*100,'next':0}} for t in range(12)]
        metric=uploader_metrics(samples,0,10)
        self.assertEqual(metric['unique_bytes_lower_bound'],900)
        self.assertEqual(metric['goodput_lower_bound_Bps'],90)
        self.assertEqual(metric['errors'],[])
        self.assertIn('uploader_observation_gap',uploader_metrics([samples[0],samples[9]],0,10)['errors'])

    def test_S3_registered_seed_and_fencing_readback_are_independent(self):
        for defect in ('seed','power','restart','process','volume','mhc'):
            with self.subTest(defect=defect),tempfile.TemporaryDirectory() as root:
                p,c=self.fixture(root,'s3','P3600');raw=read(Path(root)/'observations/contract.json')
                if defect=='seed':
                    raw['seed_before'][0]['value']='corrupt';raw['seed_after'][0]['value']='corrupt'
                elif defect=='power':raw['fence']['server']['OS-EXT-STS:power_state']=1
                elif defect=='restart':raw['source_final']['status']='ACTIVE'
                elif defect=='process':raw['old_database_processes']['containers'][0]['id']='wrong-container'
                elif defect=='volume':raw['volume_after']['attachments'].append({'server_id':'unexpected'})
                else:raw['mhc_snapshot']['items'][0]['spec']['maxUnhealthy']=99
                atomic_json(Path(root)/'observations/contract.json',raw)
                result=judge(root,c,p)
                self.assertTrue(result['safety'] is not True or not result['trial_valid'],result)

    def test_S3_pair_uses_same_registered_seed(self):
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            self.fixture(a,'s3','P3600');self.fixture(b,'s3','M3600')
            self.assertEqual(read(Path(a)/'observations/contract.json')['seed_before'],read(Path(b)/'observations/contract.json')['seed_before'])

    def test_S4_capacity_collected_after_H_cannot_prove_recovery(self):
        with tempfile.TemporaryDirectory() as root:
            p,c=self.fixture(root,'s4','on')
            self.assertTrue(judge(root,c,p)['recovered'])
            for path in (Path(root)/'observations').glob('capacity-*.json'):
                snap=read(path);snap['collected_utc']=utc(1792972800+100)
                atomic_json(path,snap)
            result=judge(root,c,p)
            self.assertFalse(result['metrics']['capacity_recovered'])
            self.assertFalse(result['recovered'])

        with tempfile.TemporaryDirectory() as root:
            p,c=self.fixture(root,'s4','on')
            path=next((Path(root)/'observations').glob('capacity-*.json'))
            snap=read(path);snap['mhc']['metadata']['annotations']={'cluster.x-k8s.io/paused':'true'}
            atomic_json(path,snap)
            self.assertIn('mhc_arm_changed_during_H',judge(root,c,p)['missing'])

    def test_malformed_raw_closes_as_unknown_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as root:
            p,c=self.fixture(root,'s2','M')
            (Path(root)/'requests.jsonl').write_text('{broken')
            result=judge(root,c,p)
            self.assertFalse(result['trial_valid']);self.assertIsNone(result['recovered'])
            self.assertTrue(result['missing'][0].startswith('malformed_evidence:'))

    def test_campaign_reloads_state_after_acquiring_lock(self):
        with tempfile.TemporaryDirectory() as root:
            directory=self.campaign(root,scenario='s2')
            first=FreshCampaign(directory,FakeBackend());second=FreshCampaign(directory,FakeBackend())
            first.run(limit=1);second.run(limit=1)
            self.assertNotEqual(first.backend.executed[0],second.backend.executed[0])

    def test_interrupt_stops_after_cleanup_and_seals_attempt(self):
        class Interrupt(FakeBackend):
            def execute(self,case,profile,ev):
                self.executed.append(case['id']);raise KeyboardInterrupt()
        with tempfile.TemporaryDirectory() as root:
            directory=self.campaign(root,scenario='s2');backend=Interrupt();campaign=FreshCampaign(directory,backend)
            with self.assertRaises(KeyboardInterrupt):campaign.run()
            self.assertEqual(len(backend.executed),1)
            data=read(directory/'campaign.json')
            self.assertEqual(data['status'],'interrupted')
            self.assertTrue(data['cases'][0]['attempts'][0]['evidence_sha256'])

    def test_source_change_after_case_does_not_lose_evidence_seal(self):
        changed=[False];baseline=source_hashes()
        class Change(FakeBackend):
            def execute(self,case,profile,ev):
                super().execute(case,profile,ev);changed[0]=True
        with tempfile.TemporaryDirectory() as root:
            directory=self.campaign(root,scenario='s2')
            with patch('fresh_campaign.source_hashes',side_effect=lambda:{} if changed[0] else baseline):
                campaign=FreshCampaign(directory,Change())
                with self.assertRaisesRegex(ValueError,'source changed'):campaign.run()
            data=read(directory/'campaign.json')
            self.assertEqual(data['cases'][0]['status'],'finished')
            self.assertTrue(data['cases'][0]['attempts'][0]['evidence_sha256'])

    def test_cleanup_resume_preserves_failed_proof_and_strict_booleans(self):
        with tempfile.TemporaryDirectory() as root:
            directory=self.campaign(root,scenario='s2');backend=FakeBackend(fail_cleanup=True);campaign=FreshCampaign(directory,backend)
            with self.assertRaises(RuntimeError):campaign.run()
            case=campaign.data['cases'][0];path=directory/case['attempts'][0]['path']
            backend.fail_cleanup=False;campaign.resume_cleanup(case['id'])
            self.assertFalse(read(path/'cleanup-attempt-001.json')['checks']['owned_resources_absent'])
            self.assertTrue(read(path/'cleanup-attempt-002.json')['checks']['owned_resources_absent'])
            self.assertFalse(read(path/'judgement.json')['trial_valid'])

    def test_foreign_S4_record_is_never_rescued_or_cleaned(self):
        from fresh_live import LiveBackend
        with tempfile.TemporaryDirectory() as root:
            r=LiveBackend.__new__(LiveBackend);r.state=Path(root);ev=Evidence(Path(root)/'attempt')
            h=Mock();h.state_record.return_value={'run_id':'other','environment_run_id':'env','phase':'failed','fresh_attempt':'foreign-path'}
            r.helper=Mock(return_value=h)
            with self.assertRaisesRegex(RuntimeError,'not owned'):r.cleanup({'id':'s4','scenario':'s4','environment_run_id':'env'},fixtures.profile(),ev)
            h.lab.admin.assert_not_called();h.cleanup_case.assert_not_called()

    def test_remote_probe_captures_raw_on_failure(self):
        with tempfile.TemporaryDirectory() as root:
            runner=Mock();runner.ev=Evidence(root);runner.remote.return_value='raw evidence';runner.read_remote=runner.remote;runner.stop_probe=Mock()
            probe=RemoteProbe(runner,'command','/owned/fresh-api.jsonl','/owned/stop',40)
            probe.future=Mock();probe.future.result.side_effect=RuntimeError('remote failure');probe.pool=Mock()
            with self.assertRaises(RuntimeError):probe.__exit__(None,None,None)
            self.assertEqual((Path(root)/'requests.jsonl').read_text(),'raw evidence')
            self.assertEqual((Path(root)/'uploader-progress.jsonl').read_text(),'raw evidence')

    def test_clock_bound_failure_is_recorded_and_blocks_confirmation(self):
        from fresh_evidence import clock_check
        import time
        with tempfile.TemporaryDirectory() as root:
            ev=Evidence(root)
            with self.assertRaisesRegex(RuntimeError,'clock bound'):
                clock_check(ev,'before-injection',lambda:time.time()+100,1,'fake remote UTC')
            self.assertEqual(len(rows(Path(root)/'clock-checks.jsonl')),1)
            p,c=self.fixture(Path(root)/'trace','s2','M')
            (Path(root)/'trace/clock-checks.jsonl').unlink()
            result=judge(Path(root)/'trace',c,p)
            self.assertIn('clock_alignment_unverified',result['missing'])
            self.assertIsNone(result['recovered'])

    def test_clock_step_between_requests_is_not_hidden_as_queue_delay(self):
        from fresh_analysis import request_metrics
        cfg=synthetic_profile(fixtures.profile())['s3']
        data=[dict(request_id=str(i),index=i,clock_id='one',scheduled_utc=utc(i),started_utc=utc(i+(.5 if i else 0)),completed_utc=utc(i+(.5 if i else 0)+.01),started_monotonic=i,completed_monotonic=i+.01,ok=True,correct=True) for i in range(2)]
        self.assertIn('clock_step_between_requests',request_metrics(data,cfg,0,2,expected=2)['errors'])

    def test_environment_changes_are_blocked_by_unfinished_fixture(self):
        from fresh_live import LiveBackend
        with tempfile.TemporaryDirectory() as root:
            backend=LiveBackend.__new__(LiveBackend);backend.state=Path(root);backend.helper=Mock()
            atomic_json(Path(root)/'s3-experiment.json',{'phase':'fence-intent'})
            with self.assertRaisesRegex(RuntimeError,'blocks environment changes'):
                backend.execute({'scenario':'s4'},fixtures.profile(),Evidence(Path(root)/'attempt'))
            backend.helper.assert_not_called()

    def test_budget_counts_other_live_scenario_cohorts_only(self):
        from fresh_campaign import spent_budget_seconds
        from fresh_evidence import append
        with tempfile.TemporaryDirectory() as root:
            for name,synthetic,policy in [('s1',False,'policy'),('s2',False,'policy'),('fake',True,'policy'),('other',False,'different')]:
                d=Path(root)/name;atomic_json(d/'campaign.json',dict(schema_version=3,synthetic=synthetic,policy_sha256=policy))
                append(d/'attempts.jsonl',dict(case_id='case',attempt_id='attempt',state='started',utc=utc(100)))
                append(d/'attempts.jsonl',dict(case_id='case',attempt_id='attempt',state='finished',utc=utc(130)))
            self.assertEqual(spent_budget_seconds(root,'policy'),60)

    def test_missing_S3_volume_identity_is_evidence_failure(self):
        with tempfile.TemporaryDirectory() as root:
            p,c=self.fixture(root,'s3','M3600');raw=read(Path(root)/'observations/contract.json')
            del raw['volume_after'];atomic_json(Path(root)/'observations/contract.json',raw)
            result=judge(root,c,p)
            self.assertFalse(result['trial_valid']);self.assertIsNone(result['recovered'])

    def test_horizon_end_requires_matching_monotonic_duration(self):
        with tempfile.TemporaryDirectory() as root:
            p,c=self.fixture(root,'s2','M');events=rows(Path(root)/'events.jsonl')
            injected=next(e for e in events if e['kind']=='injection_applied')
            end=next(e for e in events if e['kind']=='horizon_end');end['monotonic_ns']=injected['monotonic_ns']+1
            (Path(root)/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
            result=judge(root,c,p)
            self.assertIn('early_monotonic_horizon_end',result['missing'])
            self.assertIsNone(result['recovered'])

    def test_S1_contention_must_still_be_observed_at_completion(self):
        with tempfile.TemporaryDirectory() as root:
            p,c=self.fixture(root,'s1','V1');raw=read(Path(root)/'observations/contract.json')
            raw['completion_host_metrics']['cpu_utilization']=0
            atomic_json(Path(root)/'observations/contract.json',raw)
            result=judge(root,c,p)
            self.assertFalse(result['fault_realized'])
            self.assertEqual(result['v1_outcome'],'condition_not_realized')

    def test_freeze_protects_scope_counts_and_commit_metadata(self):
        for field,value in [('scope','F-bounded'),('schedule_counts',{'main':1}),('git_head','changed')]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as root:
                directory=self.campaign(root,scenario='s2');data=read(directory/'campaign.json')
                data[field]=value;atomic_json(directory/'campaign.json',data)
                with self.assertRaisesRegex(ValueError,'frozen field changed'):check_frozen(directory)
        p=fixtures.profile();p['cases'][0]['horizon_seconds']=1
        with self.assertRaisesRegex(ValueError,'unsupported case'):validate(p)

    def test_S4_capacity_probe_lifetime_covers_registered_H(self):
        from fresh_scenarios import FreshS4Run
        runner=FreshS4Run.__new__(FreshS4Run);runner.preparation=Mock()
        runner.preparation.object.return_value=None
        runner.create_probe({'probe_name':'capacity','horizon_seconds':5000},'replacement')
        manifest=json.loads(runner.preparation.k.call_args.kwargs['data'])
        self.assertEqual(manifest['spec']['containers'][0]['command'],['sh','-c','sleep 5600'])
        self.assertNotIn('nodeName',manifest['spec'])
        self.assertEqual(manifest['spec']['nodeSelector'],{'kubernetes.io/hostname':'replacement'})

    def test_S2_fault_realization_recomputes_raw_counters(self):
        with tempfile.TemporaryDirectory() as root:
            p,c=self.fixture(root,'s2','M')
            self.assertTrue(judge(root,c,p)['fault_realized'])
            decisions=rows(Path(root)/'decisions.jsonl')
            decisions[0]['diagnosis']={'trigger':True}
            decisions[0]['raw_after']['qdisc']['overlimits']=0
            (Path(root)/'decisions.jsonl').write_text(''.join(json.dumps(d)+'\n' for d in decisions))
            result=judge(root,c,p)
            self.assertTrue(result['trial_valid'])
            self.assertFalse(result['fault_realized'])

    def test_S3_M_cannot_hide_unnecessary_fencing_in_raw(self):
        with tempfile.TemporaryDirectory() as root:
            p,c=self.fixture(root,'s3','M3600');raw=read(Path(root)/'observations/contract.json')
            raw['fence']={'server':{'id':'v1','status':'SHUTOFF'}}
            atomic_json(Path(root)/'observations/contract.json',raw)
            result=judge(root,c,p)
            self.assertFalse(result['trial_valid']);self.assertFalse(result['safety'])


if __name__=='__main__':unittest.main()


class S3PreControllerCleanupTests(unittest.TestCase):
    def checker(self):
        import ast,hashlib
        tree=ast.parse((ROOT/'evaluation/graduation_evaluation.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='s3_controller_cleanup_checks')
        namespace={'Path':Path,'hashlib':hashlib}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<cleanup-check>','exec'),namespace)
        return namespace['s3_controller_cleanup_checks']

    def test_no_intent_and_no_files_is_explicitly_not_started(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(self.checker()({'evidence':folder}),{'controller_configuration_not_started':True})

    def test_normal_restoration_requires_original_sha_and_actual_matching_files(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'controller-manager-before.yaml').write_bytes(b'original');(p/'controller-manager-after.yaml').write_bytes(b'original')
            record={'evidence':folder,'controller_original_sha256':hashlib.sha256(b'original').hexdigest()}
            self.assertEqual(self.checker()(record),{'controller_policy_restored':True})
            (p/'controller-manager-after.yaml').write_bytes(b'changed')
            self.assertEqual(self.checker()(record),{'controller_policy_restored':False})
            (p/'controller-manager-after.yaml').write_bytes(b'original');record['controller_original_sha256']='wrong'
            self.assertEqual(self.checker()(record),{'controller_policy_restored':False})

    def test_missing_file_after_intent_is_never_waived(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):self.checker()({'evidence':folder,'controller_original_sha256':'set'})

    def test_orphan_intent_or_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RuntimeError):self.checker()({'evidence':folder,'controller_configured_sha256':'set'})
            (Path(folder)/'controller-manager-before.yaml').write_text('orphan')
            with self.assertRaises(RuntimeError):self.checker()({'evidence':folder})

    def test_helper_ast_rejects_unrelated_cleanup_change(self):
        from fresh_transport_release import validate_cleanup_helper_diff,HELPER_EXPECTED
        current=(ROOT/'evaluation/graduation_evaluation.py').read_text()
        original=current.replace(HELPER_EXPECTED,'').replace('checks.update(s3_controller_cleanup_checks(record))',"checks['controller_policy_restored'] = (Path(record['evidence']) / 'controller-manager-before.yaml').read_bytes() == (Path(record['evidence']) / 'controller-manager-after.yaml').read_bytes()")
        validate_cleanup_helper_diff(original,current)
        with self.assertRaises(ValueError):validate_cleanup_helper_diff(original,current.replace("mode == 'auto' and current['workers'] == 1","mode == 'auto' and current['workers'] == 2"))
