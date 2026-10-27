"""B01-B06/B08-B10: fresh contracts, independent synthetic judgements, no cloud."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/d) for d in ('evaluation','scripts','experiments')]
from fresh_contract import validate, schedule, expected_requests
from fresh_campaign import freeze, check_frozen, FreshCampaign, report, evidence_hashes
from fresh_fake import FakeBackend, synthetic_profile
from fresh_analysis import judge, read, rows, request_metrics
from fresh_evidence import Evidence, elapsed, append, epoch, utc
from lib.state import atomic_json
from graduation_evaluation import schedule as legacy_schedule


def profile():return json.loads((ROOT/'config/graduation-evaluation-fresh.json').read_text())


class FreshTests(unittest.TestCase):
    def test_B01_schedule_counts_and_legacy_exact_ids(self):
        p=profile();counts=validate(p)
        self.assertEqual(counts,dict(main=29,preparation=8,development='separate'))
        self.assertEqual(len(schedule(p)),37)
        old=json.loads((ROOT/'config/graduation-evaluation.json').read_text())
        expected={'s4-normal-01','s4-interrupt-resume','s1-no-destination','s2-qos-rejection','s3-fence-refusal'}
        expected|={f'{s}-{m}-{i:02}' for i in range(1,6) for s,ms in [('s1',['automatic','no-action']),('s3',['automatic','runbook']),('s4',['normal'])] for m in ms}
        expected|={f's2-{"fixed-first" if i%2 else "dynamic-first"}-{i:02}' for i in range(1,6)}
        self.assertEqual({c['id'] for c in legacy_schedule(old)},expected)
        self.assertEqual(expected_requests(p['s1']),9000)
        self.assertEqual(expected_requests({'rate':3,'seconds':17}),51)
        self.assertEqual(len({tuple(c['mode'] for c in p['cases'] if c['scenario']=='s1' and c['block']==b) for b in ('b01','b02','b03')}),3)

    def test_B01_draft_live_blocked_and_bad_schema(self):
        with self.assertRaisesRegex(ValueError,'unresolved live'):validate(profile(),live=True)
        for mutate in (lambda p:p['cases'].append(p['cases'][0]),lambda p:p['cases'][0].update(mode='H'),
                       lambda p:p['cases'][0].update(purpose='main'),lambda p:p.update(schema_version=2),
                       lambda p:p['cases'][0].update(depends_on=['missing'])):
            p=profile();mutate(p)
            with self.assertRaises(ValueError):validate(p)

    def fixture(self,root,scenario='s1',mode='P'):
        p=synthetic_profile(profile())
        case=next(c for c in p['cases'] if c['scenario']==scenario and c['mode']==mode and c['purpose']=='main')
        ev=Evidence(root);fake=FakeBackend();fake.execute(case,p,ev)
        ev.state('CLEANUP');atomic_json(Path(root)/'cleanup.json',fake.cleanup(case,p,ev));ev.state('VERIFIED')
        return p,case

    def test_B02_B05_normal_relapse_unrecovered_queue_and_missing(self):
        with tempfile.TemporaryDirectory() as root:
            p,c=self.fixture(root)
            j=judge(root,c,p)
            self.assertTrue(j['trial_valid'],j)
            self.assertTrue(j['recovered'])
            self.assertEqual(j['metrics']['recovery_seconds'],10)
            raw=rows(Path(root)/'requests.jsonl')
            # Late relapse removes an earlier healthy recovery.
            raw[next(i for i,r in enumerate(raw) if epoch(r['scheduled_utc'])>=1792972800+35)]['ok']=False
            (Path(root)/'requests.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in raw))
            self.assertFalse(judge(root,c,p)['recovered'])
        for s,m in [('s1','M'),('s2','M'),('s3','M3600'),('s4','off')]:
            with self.subTest(s=s),tempfile.TemporaryDirectory() as root:
                p,c=self.fixture(root,s,m);j=judge(root,c,p)
                self.assertTrue(j['trial_valid'],j)
                self.assertFalse(j['recovered'])

    def test_B02_B05_request_defects_and_clock_domains(self):
        p=synthetic_profile(profile());cfg=p['s2'];start=1000
        good=dict(request_id='0',scheduled_utc=utc(start),started_utc=utc(start+.5),completed_utc=utc(start+.6),ok=True,correct=True)
        m=request_metrics([good],cfg,start,start+1,expected=1)
        self.assertAlmostEqual(m['scheduled_latency_p95_ms'],600)
        self.assertAlmostEqual(m['queue_p95_ms'],500)
        self.assertIn('missing_or_duplicate_request_id',request_metrics([good,good],cfg,start,start+1,expected=2)['errors'])
        self.assertEqual(request_metrics([],cfg,start,start+1,expected=2)['failures'],2)
        rejected={**good,'ok':False,'generator_rejection':True,'started_utc':None,'completed_utc':None}
        self.assertEqual(request_metrics([rejected],cfg,start,start+1,expected=1)['generator_rejections'],1)
        reversed_time={**good,'completed_utc':utc(start-.1)}
        self.assertIn('request_time_reversed',request_metrics([reversed_time],cfg,start,start+1,expected=1)['errors'])
        with self.assertRaisesRegex(ValueError,'different processes'):elapsed(dict(clock_id='a',monotonic_ns=1),dict(clock_id='b',monotonic_ns=2))

    def test_B03_B04_wrong_target_v1_outcomes_and_summary_independence(self):
        for mode in ('P','A','V1'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as root:
                p,c=self.fixture(root,mode=mode)
                first=judge(root,c,p)
                atomic_json(Path(root)/'summary.json',{'passed':False,'state':'failed'})
                self.assertEqual(judge(root,c,p),first)
                raw=read(Path(root)/'observations/contract.json')
                if mode=='A':raw['service_after']['node']='wrong-node'
                elif mode=='V1':raw['host_metrics']['cpu_utilization']=0
                else:raw['compute_after']=raw['compute_before']
                atomic_json(Path(root)/'observations/contract.json',raw)
                j=judge(root,c,p)
                if mode=='V1':self.assertEqual(j['v1_outcome'],'condition_not_realized')
                else:self.assertFalse(j['safety'])

    def test_B08_B09_B10_safety_snapshots(self):
        for s,m,key in [('s2','P','uploader'),('s3','P3600','fence'),('s4','on','identity'),('s4','off','restore')]:
            with self.subTest(s=s,key=key),tempfile.TemporaryDirectory() as root:
                p,c=self.fixture(root,s,m)
                self.assertTrue(judge(root,c,p)['trial_valid'])
                raw=read(Path(root)/'observations/contract.json')
                if key=='uploader':raw['upload_windows'][0]['after']['bytes']=0
                if key=='fence':raw['fence']['server']['id']='wrong-vm'
                if key=='identity':raw['replacement_binding']['nova_id']='wrong-vm'
                if key=='restore':
                    restored=read(Path(root)/'mhc-restored.json');restored['spec']={}
                    atomic_json(Path(root)/'mhc-restored.json',restored)
                atomic_json(Path(root)/'observations/contract.json',raw)
                result=judge(root,c,p)
                if key=='uploader':
                    self.assertTrue(result['trial_valid'])
                    self.assertFalse(result['metrics']['upload_progress_each_window'])
                else:self.assertFalse(result['safety'])

    def campaign(self,root,stage='main',scenario=None):
        source=Path(root)/'profile.json';atomic_json(source,synthetic_profile(profile()))
        destination=Path(root)/'campaign'
        freeze(source,destination,stage,scenario,synthetic=True)
        return destination

    def test_B01_B06_freeze_profile_source_analysis_hash_and_history(self):
        with tempfile.TemporaryDirectory() as root:
            d=self.campaign(root,scenario='s2')
            data=check_frozen(d,current=True)
            p=Path(data['profile_path']);p.write_text(p.read_text()+' ')
            with self.assertRaisesRegex(ValueError,'profile changed'):check_frozen(d,current=True)
            p.write_bytes((d/'selected-profile.json').read_bytes())
            with patch('fresh_campaign.source_hashes',return_value={}):
                with self.assertRaisesRegex(ValueError,'source changed'):check_frozen(d,current=True)
            data['profile']['analysis']['version']=99;atomic_json(d/'campaign.json',data)
            with self.assertRaisesRegex(ValueError,'frozen field'):check_frozen(d)

    def test_B05_B06_all29_and8_synthetic_campaigns_and_primary_rejection(self):
        for stage,count in [('main',29),('preparation',8)]:
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as root:
                d=self.campaign(root,stage)
                campaign=FreshCampaign(d,FakeBackend());campaign.run()
                with self.assertRaisesRegex(ValueError,'synthetic evidence'):report(d)
                out=report(d,allow_synthetic=True)
                self.assertEqual(len(out['run_results']),count)
                self.assertEqual(out['primary_sample_count'],0)
                self.assertTrue(all(r['trial_valid'] for r in out['run_results']),[(r['case_id'],r['missing']) for r in out['run_results'] if not r['trial_valid']])
                self.assertEqual(out['missingness'],[])
                if stage=='main':self.assertEqual(len(out['paired_contrasts']),15)
                # Foreign identity must be rejected even if an attacker refreshes file digests.
                a=campaign.data['cases'][0]['attempts'][0];path=d/a['path']
                identity=read(path/'identity.json');identity['campaign_id']='historical'
                atomic_json(path/'identity.json',identity);a['evidence_sha256']=evidence_hashes(path);campaign.save()
                with self.assertRaisesRegex(ValueError,'historical'):report(d,True)

    def test_B06_cleanup_failure_resume_no_replay_and_retry(self):
        with tempfile.TemporaryDirectory() as root:
            d=self.campaign(root,scenario='s2');fake=FakeBackend(fail_cleanup=True)
            c=FreshCampaign(d,fake)
            with self.assertRaisesRegex(RuntimeError,'next case blocked'):c.run()
            self.assertEqual(len(fake.executed),1)
            with self.assertRaisesRegex(RuntimeError,'resume-cleanup'):c.run()
            fake.fail_cleanup=False;c.resume_cleanup(fake.executed[0])
            self.assertEqual(len(fake.executed),1)
            self.assertTrue((d/'attempts.jsonl').exists())
            # Cleanup-only resume preserves the observation gap; explicit retry creates a fresh path.
            c.run(retry_case=fake.executed[0])
            self.assertEqual(len(c.data['cases'][0]['attempts']),2)

    def test_B03_restart_hook_and_unknown_effect_never_replayed(self):
        from fresh_scenarios import FreshS1
        runner=FreshS1.__new__(FreshS1);runner.case={'mode':'A'};runner.ev=Mock();runner.s1=Mock();runner.write=Mock()
        before=dict(pod_uid='pod',node='n',nova_id='vm',image_id='image')
        runner.s1.verify.return_value=before
        runner.s1.obj.return_value={'metadata':{'uid':'dep','resourceVersion':'1'},'spec':{'template':{'metadata':{},'spec':{'nodeSelector':{'kubernetes.io/hostname':'n'}}}}}
        record={'service_before':{**before,'time':'earlier'},'run_id':'attempt','automatic_trigger':True}
        runner.s1.k.side_effect=TimeoutError('applied then response lost')
        with self.assertRaises(TimeoutError):runner.move_service(record)
        self.assertEqual(runner.s1.k.call_count,1)
        patch_ops=json.loads(runner.s1.k.call_args.args[-1])
        self.assertEqual(patch_ops[-1]['path'],'/spec/template/metadata/annotations')
        self.assertFalse(any('nodeSelector' in x['path'] for x in patch_ops))

    def test_B08_real_split_hook_suppresses_M_and_confirms_P(self):
        from fresh_scenarios import FreshS2
        for mode in ('P','M'):
            r=FreshS2.__new__(FreshS2);r.case={'mode':mode};r.ev=Mock();r.set_rate=Mock();r.k=Mock();r.ready=Mock(return_value=True);r.ns='ns'
            r.pods=Mock(return_value=[{'spec':{'nodeName':'b'}}])
            a={'node':'a','port':{'id':'a-port'}};b={'node':'b','port':{'id':'b-port'}}
            self.assertEqual(r.split_if_enabled(a,b,6000),mode=='P')
            self.assertEqual(r.set_rate.call_count,mode=='P')
            self.assertEqual(r.k.call_count,mode=='P')

    def test_B09_real_fencing_hook_order_M_suppression_and_deadline(self):
        from fresh_scenarios import FreshS3
        for mode in ('P3600','M3600'):
            r=FreshS3.__new__(FreshS3);r.case={'mode':mode};r.record={'run_id':'run'};r.ev=Mock()
            calls=[];r.fence=Mock(side_effect=lambda:calls.append('fence'));r.mark_out_of_service=Mock(side_effect=lambda:calls.append('oos'))
            r.obj=Mock(return_value={'spec':{'taints':[{'key':'node.kubernetes.io/out-of-service','value':'run'}]}})
            source={'nova_id':'v','node':'n','node_uid':'uid'}
            with patch('fresh_scenarios.time.monotonic',return_value=1):
                r.recover_if_enabled(source,0,{'horizon_seconds':1000})
            self.assertEqual(calls,['fence','oos'] if mode=='P3600' else [])
            calls.clear()
            with patch('fresh_scenarios.time.monotonic',return_value=999):
                self.assertFalse(r.recover_if_enabled(source,0,{'horizon_seconds':1000}))
            self.assertEqual(calls,[])
            if mode=='P3600':
                r.fence.side_effect=RuntimeError('fence unconfirmed');r.mark_out_of_service.reset_mock()
                with patch('fresh_scenarios.time.monotonic',return_value=1),self.assertRaises(RuntimeError):
                    r.recover_if_enabled(source,0,{'horizon_seconds':1000})
                r.mark_out_of_service.assert_not_called()

    def test_B10_restore_mhc_ownership_and_readback(self):
        from fresh_scenarios import restore_mhc
        before={'metadata':{'uid':'mhc','resourceVersion':'1'},'spec':{'selector':{'matchLabels':{'worker':'yes'}}}}
        current=copy.deepcopy(before);current['metadata']['annotations']={'cluster.x-k8s.io/paused':'true','openstack-k8s.dev/fresh-owner':'case'}
        lab=Mock();lab.obj.side_effect=[current,before]
        with tempfile.TemporaryDirectory() as root:
            restore_mhc(lab,{'before':before,'owner':'case'},Evidence(root))
            self.assertEqual(lab.k.call_count,1)
            wrong=copy.deepcopy(current);wrong['metadata']['uid']='foreign'
            lab.obj.side_effect=[wrong];lab.k.reset_mock()
            with self.assertRaisesRegex(RuntimeError,'identity changed'):restore_mhc(lab,{'before':before,'owner':'case'},Evidence(root))
            lab.k.assert_not_called()

    def test_B02_event_time_reversal_and_execution_exception_not_hold(self):
        with tempfile.TemporaryDirectory() as root:
            p,c=self.fixture(root,mode='V1')
            self.assertEqual(judge(root,c,p)['v1_outcome'],'held')
            append(Path(root)/'events.jsonl',dict(event_id='oops',kind='execution_error',utc=utc(),monotonic_ns=1,clock_id='extra',observer='test',target_uid=None))
            self.assertEqual(judge(root,c,p)['v1_outcome'],'exception')
            raw=rows(Path(root)/'events.jsonl');raw[1]['monotonic_ns']=raw[0]['monotonic_ns']-1
            (Path(root)/'events.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in raw))
            self.assertIn('event_time_reversed',judge(root,c,p)['missing'])

    def test_B02_open_loop_probe_records_every_arrival_offline(self):
        from fresh_evidence import OpenLoopProbe
        with tempfile.TemporaryDirectory() as root:
            with OpenLoopProbe(Path(root)/'requests.jsonl',lambda:{'ok':True,'correct':True},1000,.004,.1) as sampler:
                pass
            actual=rows(Path(root)/'requests.jsonl')
            self.assertEqual({r['request_id'] for r in actual},{str(i) for i in range(4)})
            self.assertTrue(all(r['scheduled_utc'] and r['clock_id'] for r in actual))

    def test_B06_partial_S4_prepare_without_record_can_cleanup(self):
        from fresh_live import LiveBackend
        with tempfile.TemporaryDirectory() as root:
            r=LiveBackend.__new__(LiveBackend);r.state=Path(root)/'state';r.state.mkdir()
            ev=Evidence(Path(root)/'attempt');h=Mock();h.state_record.return_value=None;h.lab.admin_json.return_value=[]
            r.helper=Mock(return_value=h)
            atomic_json(ev.directory/'cases/s4/cleanup-verification.json',{'checks':{'owned_resources_absent':True}})
            with patch('fresh_calibration.TransportWatch'):
                result=r.cleanup({'id':'s4','scenario':'s4'},profile(),ev)
            self.assertTrue(result['checks']['owned_resources_absent'])
            h.lab.admin.assert_not_called()
            h.cleanup_case.assert_called_once()

    def test_B06_all_scenario_freeze_cannot_duplicate_S1_main(self):
        from fresh_campaign import source_hashes,policy_manifest
        from fresh_contract import digest
        with tempfile.TemporaryDirectory() as root:
            base=Path(root);p=profile();override=base/'override.env';override.write_text('# offline mock only')
            p['operations'].update(execution_checkout=str(ROOT),environment_override=str(override),artifact_root=str(base))
            policy=policy_manifest(source_hashes());policy_path=base/'policy.json';atomic_json(policy_path,policy)
            atomic_json(base/'existing/campaign.json',dict(schema_version=3,status='batch-complete',synthetic=False,stage='main',policy_sha256=digest(policy),cases=[{'scenario':'s1'}]))
            preparation=[dict(case_id=c['id'],trial_valid=True,mode=c['mode'],v1_outcome='held',safety=True,cleanup=True,fault_realized=True,recovered=True) for c in p['cases'] if c['purpose']!='main']
            env={'ENVIRONMENT_NAME':p['environment'],'GCP_PROJECT_ID':p['project'],'GCP_ZONE':p['zone'],'ENV_OVERRIDE_FILE':str(override)}
            with patch('fresh_campaign.load',return_value=p),patch('fresh_campaign.case_time_gate'),patch.dict('os.environ',env),patch('fresh_campaign.report',return_value=dict(stage='preparation',missingness=[],run_results=preparation)),patch('fresh_campaign.check_frozen',return_value={'policy_sha256':digest(policy),'profile':p}):
                with self.assertRaisesRegex(ValueError,'same existing freeze'):
                    freeze(base/'profile.json',base/'new','main',policy_path=policy_path,pilot_campaign=base/'pilot')
            self.assertFalse((base/'new').exists())


if __name__=='__main__':unittest.main()
