"""Calibration safety/selection/held-out validation tests; no cloud calls."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/d) for d in ('evaluation','scripts','experiments')]
from fresh_calibration import assess, choose, admission, normal_job, RULE, check_root, exclusive_json, measure, validate_binding, close_session, TransportWatch
from fresh_campaign import freeze
from fresh_evidence import utc, Evidence


def trace(latency=.10):
    return [dict(index=i,request_id=str(i),scheduled_utc=utc(1000+i/5),
        scheduled_monotonic=100+i/5,started_utc=utc(1000+i/5+.001),started_monotonic=100+i/5+.001,
        completed_utc=utc(1000+i/5+latency),completed_monotonic=100+i/5+latency,
        clock_id='one',ok=True,correct=True,deadline_seconds=5,generator_rejection=False) for i in range(1500)]


def cfg():
    return dict(rate=5,slo_ms=200,deadline_seconds=5,bin_seconds=20,stable_seconds=120,min_samples=100,bin_max_bad_fraction=.05)


class CalibrationTests(unittest.TestCase):
    def test_fixed_first_window_and_whole_index_missing_clock_deadline(self):
        good=trace()
        self.assertTrue(assess(good,cfg())['sustained_accepted'])
        mutations=[good[1:],good+[good[700]],good[:-1]]
        for field,value in [('scheduled_utc',utc(1)),('scheduled_monotonic',1),('clock_id','other'),('deadline_seconds',6),('completed_monotonic',-1)]:
            raw=copy.deepcopy(good);raw[900][field]=value;mutations.append(raw)
        for raw in mutations:
            self.assertFalse(assess(raw,cfg())['data_valid'])
        late=assess(trace(5.1),cfg())
        self.assertFalse(late['no_failures']);self.assertFalse(late['sustained_accepted'])

    def test_baseline_acceptance_does_not_claim_sustained_or_hide_relapse(self):
        raw=trace()
        for i in range(800,810):
            raw[i].update(completed_utc=utc(1000+i/5+.4),completed_monotonic=100+i/5+.4)
        a=assess(raw,cfg())
        self.assertTrue(a['baseline_accepted']);self.assertFalse(a['sustained_accepted'])
        self.assertEqual(a['relapse_bins'],[800])

    def test_selection_margin_rounding_ceiling_and_failures(self):
        self.assertEqual(choose([assess(trace(.1),cfg())]*3)['slo_ms'],200)
        self.assertEqual(choose([assess(trace(.201),cfg())]*3)['slo_ms'],250)
        with self.assertRaisesRegex(ValueError,'ceiling'):choose([assess(trace(.43),cfg())]*3)
        with self.assertRaises(ValueError):choose([assess(trace(5.1),cfg())]*3)
        with self.assertRaises(ValueError):choose([assess(trace(),cfg())]*2)
        frozen=choose([assess(trace(.201),cfg())]*3)
        validation=assess(trace(.3),{**cfg(),'slo_ms':frozen['slo_ms']})
        self.assertFalse(validation['baseline_accepted'])
        self.assertEqual(frozen['slo_ms'],250) # validation does not change selection

    def test_reserve_blocks_remaining_set_and_no_overwrite(self):
        self.assertEqual(admission(1000,5,1000),4600)
        with self.assertRaisesRegex(RuntimeError,'remaining full'):admission(1000,5,2600)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'freeze.json';exclusive_json(path,{'value':1})
            with self.assertRaises(FileExistsError):exclusive_json(path,{'value':2})
            self.assertEqual(json.loads(path.read_text()),{'value':1})

    def test_calibration_cannot_enter_campaign_or_dispatch_injection(self):
        p=json.loads((ROOT/'config/graduation-evaluation-fresh-candidate-2026-10-26.json').read_text())
        with self.assertRaises(ValueError):check_root(ROOT/'artifacts/fresh-evaluation-2026-10-26/bed-a/cal',p)
        with tempfile.TemporaryDirectory() as d,self.assertRaisesRegex(ValueError,'unknown stage'):
            freeze(ROOT/'config/graduation-evaluation-fresh-candidate-2026-10-26.json',d,'calibration',synthetic=True)
        tree=ast.parse((ROOT/'evaluation/fresh_calibration.py').read_text())
        calls=[n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
        for prohibited in ('execute','create_competitor','move_service','run_locked','finish'):
            # Samplers.finish is an observer join, the only permitted finish.
            if prohibited!='finish':self.assertNotIn(prohibited,calls)
        job=normal_job('test','control')
        env={e['name']:e['value'] for e in job['spec']['template']['spec']['containers'][0]['env']}
        self.assertEqual([env[k] for k in ('S1_RATE','S1_MEASURE_SECONDS','S1_WARMUP_SECONDS','S1_TIMEOUT_SECONDS')],['5','300','0','5'])
        self.assertIn('http.graduation-s1.svc.cluster.local',env['S1_URL'])

    def test_calibrated_profile_proof_and_document_drift_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            from fresh_calibration import sha
            directory=Path(d)
            profile={'s1':cfg(),'s2':{},'s3':{},'s4':{},'v1_condition':{},'analysis':{},'operations':{'preregistered_documents':['amend.md','docs/graduation/s1-baseline-calibration-protocol-2026-10-26.md']}}
            exclusive_json(directory/'candidate-profile.json',profile)
            source={n:sha(ROOT/n) for n in ('kubernetes/graduation-s1/app.py','kubernetes/graduation-s1/loadgen.py','evaluation/fresh_baseline.py','evaluation/fresh_analysis.py','evaluation/fresh_contract.py','evaluation/fresh_calibration.py')}
            exclusive_json(directory/'candidate-freeze.json',{'slo_ms':200,'source_sha256':source})
            exclusive_json(directory/'summary.json',{'accepted':True,'validation_baseline_passed':True,'validation_sustained_passed':True})
            exclusive_json(directory/'registration.json',{})
            for i in (1,2):
                target=directory/f'validation-{i:02}';target.mkdir()
                (target/'requests.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in trace()))
                exclusive_json(target/'metrics.json',assess(trace(),cfg()))
            binding={'directory':d,'evidence_sha256':{str(p.relative_to(directory)):sha(p) for p in directory.rglob('*.json*')},'amendment_path':'amend.md','amendment_sha256':'amend-hash'}
            profile['analysis']['s1_calibration']=binding
            real_sha=sha
            def hasher(path):return 'amend-hash' if Path(path).name=='amend.md' else real_sha(path)
            with patch('fresh_calibration.check_root'),patch('fresh_calibration.sha',side_effect=hasher):
                validate_binding(profile)
                altered=copy.deepcopy(profile);altered['s1']['slo_ms']=250
                with self.assertRaisesRegex(ValueError,'measurement differs'):validate_binding(altered)
                altered=copy.deepcopy(profile);altered['analysis']['s1_calibration']['amendment_sha256']='changed'
                with self.assertRaisesRegex(ValueError,'document binding'):validate_binding(altered)
                (directory/'validation-01/requests.jsonl').write_text('')
                with self.assertRaisesRegex(ValueError,'proof changed'):validate_binding(profile)

    def test_cleanup_failure_blocks_down_and_lock_drain_precedes_stop(self):
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d);helper=Mock();helper.directory=directory/'fixture'
            backend=Mock();case={'id':'one'};profile={'project':'p','hosts':{'host':'type'}}
            helper.cleanup_case.side_effect=RuntimeError('worker restoration failed')
            with patch.dict('os.environ',{'WORKLOAD_LOCAL_API_PORT':'16444'}):
                error=close_session(backend,helper,case,profile,directory)
            self.assertIn('restoration failed',error)
            backend.environment_action.assert_not_called()
            self.assertTrue(json.loads((directory/'cleanup-error.json').read_text())['down_blocked'])
            proof=helper.directory/'cases/one/cleanup-verification.json';proof.parent.mkdir(parents=True)
            def restored(case):
                proof.write_text(json.dumps({'passed':True,'checks':{'worker_auto_one':True}}))
            helper.cleanup_case.side_effect=[BlockingIOError(35,'draining'),None]
            helper.cleanup_case.side_effect=None
            calls=[0]
            def cleanup(case):
                calls[0]+=1
                if calls[0]==1:raise BlockingIOError(35,'draining')
                restored(case)
            helper.cleanup_case.side_effect=cleanup
            def down(*args):self.assertTrue(proof.exists())
            backend.environment_action.side_effect=down
            with patch.dict('os.environ',{'WORKLOAD_LOCAL_API_PORT':'16444'}),patch('fresh_calibration.time.sleep'),patch('workload_state.command',return_value=json.dumps([{'name':'host','status':'TERMINATED'}])):
                self.assertIsNone(close_session(backend,helper,case,profile,directory))
            backend.environment_action.assert_called_once_with(profile,'down')
            self.assertEqual(len((directory/'cleanup-retries.jsonl').read_text().splitlines()),1)

    def test_transport_watch_only_repairs_missing_local_listener_and_is_bounded(self):
        with tempfile.TemporaryDirectory() as d,patch.dict('os.environ',{'STATE_DIR':d}):
            helper=Mock();watch=TransportWatch(helper,d,port=16444)
            with patch.object(watch,'reachable',return_value=True):watch.check()
            helper.call.assert_not_called()
            with patch.object(watch,'reachable',return_value=False):
                watch.check();watch.check();watch.check()
            self.assertEqual(helper.call.call_count,2)
            self.assertTrue(watch.stop.is_set())
            self.assertIn('limit',watch.error)
            with TransportWatch(helper,d,port=16444,interval=100) as active:
                self.assertTrue(active.thread.is_alive())
            self.assertFalse(active.thread.is_alive())
            self.assertTrue(json.loads((Path(d)/'transport-watch-summary.json').read_text())['stopped'])

    def test_job_apply_exception_still_collects_deletes_and_joins_observers(self):
        with tempfile.TemporaryDirectory() as d:
            s1=Mock();s1.lock_path=Path(d)/'s1.lock'
            s1.verify.return_value={'node':'src','nova_id':'vm','pod':'http'}
            s1.environment.return_value={};s1.read.return_value={}
            s1.placement.return_value={'compute_host':'osk8s-compute02'}
            s1.client.get.return_value={'items':[{'metadata':{'name':'cp','labels':{'node-role.kubernetes.io/control-plane':''}},'status':{'conditions':[{'type':'Ready','status':'True'}]}}]}
            def obj(kind,name):
                if kind=='deployment':return {'metadata':{'uid':'dep','resourceVersion':'1'}}
                return {'metadata':{'uid':'job','annotations':{'openstack-k8s.dev/purpose':'calibration-validation'}}}
            s1.obj.side_effect=obj
            def command(*args,**kwargs):
                if args[0]=='apply':raise TimeoutError('lost apply response')
                return ''
            s1.k.side_effect=command
            sampler=Mock();sampler.finish.return_value=[]
            with patch('fresh_calibration.clock_check'),patch('fresh_calibration.Samplers',return_value=sampler),self.assertRaises(TimeoutError):
                measure(s1,{'placement':{'workers':[{'host':'osk8s-compute02','node':'src'}]}},{'source_compute':'osk8s-compute02'},Evidence(d))
            sampler.finish.assert_called_once()
            self.assertTrue(any('delete' in call.args for call in s1.k.call_args_list))

    def test_instrumentation_keeps_http_work_and_captures_handler_connect(self):
        def module(name,path):
            spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
        app=module('cal_app',ROOT/'kubernetes/graduation-s1/app.py')
        loadgen=module('cal_loadgen',ROOT/'kubernetes/graduation-s1/loadgen.py')
        server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            result=loadgen.request(f'http://127.0.0.1:{server.server_port}/work?rounds=100000','measure',0,5)
            self.assertTrue(result['ok']);self.assertTrue(result['correct'])
            self.assertGreaterEqual(result['dns_tcp_ms'],0)
            self.assertTrue(result['server_timing'].startswith('handler;dur='))
            self.assertGreaterEqual(result['latency_ms'],result['response_headers_ms'])
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
