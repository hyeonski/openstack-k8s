"""Controller-only architecture amendment: fail closed without changing measurement."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/d) for d in ('evaluation','scripts','experiments')]
from fresh_identity import DOCUMENT, validate_controller_policy, identity_matches, read_controller_architecture
from fresh_campaign import pilot_contract, policy_manifest, source_hashes
from fresh_evidence import utc


def profile():
    p=json.loads((ROOT/'config/graduation-evaluation-fresh-candidate-2026-10-26.json').read_text())
    p['observed_environment']={'host_identity':{n:dict(id=str(i),machine_type=kind,cpuPlatform='Intel Broadwell' if n=='osk8s-controller' else 'Intel Cascade Lake') for i,(n,kind) in enumerate(p['hosts'].items(),1)}}
    p['operations']['controller_platform_policy']=dict(host='osk8s-controller',machine_type='e2-standard-4',architecture='x86_64',cpu_platform='provider-selected',scope='controller-only',same_instance_id=True,preregistered_document=DOCUMENT,document_sha256=hashlib.sha256((ROOT/DOCUMENT).read_bytes()).hexdigest())
    p['operations']['preregistered_documents'].append(DOCUMENT)
    return p


def hosts(p):
    return [dict(name=n,id=h['id'],machineType='/machineTypes/'+h['machine_type'],cpuPlatform='AMD Rome' if n=='osk8s-controller' else h['cpuPlatform'],status='RUNNING',lastStartTimestamp=utc(time.time()-60),scheduling={'maxRunDuration':{'seconds':'36000'}}) for n,h in p['observed_environment']['host_identity'].items()]


class ControllerIdentityTests(unittest.TestCase):
    def test_scope_architecture_document_and_instance_contract_are_validated(self):
        p=profile();validate_controller_policy(p,live=True)
        for field,value in [('architecture','aarch64'),('scope','all-hosts'),('host','osk8s-compute01'),('same_instance_id',False),('same_instance_id',1),('document_sha256','0'*64)]:
            q=copy.deepcopy(p);q['operations']['controller_platform_policy'][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):validate_controller_policy(q,live=True)
        q=copy.deepcopy(p);q['operations']['preregistered_documents'].remove(DOCUMENT)
        with self.assertRaisesRegex(ValueError,'preregistered'):validate_controller_policy(q,live=True)
        with tempfile.TemporaryDirectory() as root:
            doc=Path(root)/DOCUMENT;doc.parent.mkdir(parents=True);doc.write_text('changed')
            with patch('fresh_identity.ROOT',Path(root)),self.assertRaisesRegex(ValueError,'amendment changed'):
                validate_controller_policy(p,live=True)

    def test_controller_variation_only_and_legacy_profiles_remain_strict(self):
        p=profile();expected=p['observed_environment']['host_identity'];observed=copy.deepcopy(expected)
        observed['osk8s-controller']['cpuPlatform']='AMD Rome'
        saved=copy.deepcopy(observed)
        self.assertTrue(identity_matches(p,expected,observed,'x86_64'))
        self.assertEqual(observed,saved)  # Actual CPU readback must never be normalized away.
        for arch in ('aarch64','arm64','unknown',None):self.assertFalse(identity_matches(p,expected,observed,arch))
        for name,key,value in [('osk8s-controller','id','changed'),('osk8s-controller','machine_type','n2-standard-4'),('osk8s-controller','cpuPlatform','Google Axion'),('osk8s-compute01','cpuPlatform','Intel Ice Lake'),('osk8s-compute02','id','changed')]:
            damaged=copy.deepcopy(observed);damaged[name][key]=value
            self.assertFalse(identity_matches(p,expected,damaged,'x86_64'))
        p['operations'].pop('controller_platform_policy')
        self.assertFalse(identity_matches(p,expected,observed,'x86_64'))
        lab=Mock();self.assertIsNone(read_controller_architecture(p,lab));lab.remote.assert_not_called()

    def test_live_admission_reads_guest_architecture_before_attempt(self):
        from fresh_live import LiveBackend
        p=profile();current=hosts(p)
        with tempfile.TemporaryDirectory() as root:
            base=Path(root);p['operations'].update(artifact_root=str(base/'release'),development_artifact_root=str(base/'dev'))
            backend=LiveBackend.__new__(LiveBackend);backend.state=base/'state';backend.state.mkdir();backend.directory=base
            backend.require_clean_state=Mock()
            record={'phase':'ready','final_hosts':{h['name']:{'id':h['id'],'last_start':h['lastStartTimestamp']} for h in current}}
            (backend.state/'graduation-environment.json').write_text(json.dumps(record))
            lab=Mock();lab.remote.return_value='x86_64\n'
            with patch('fresh_live.BedLedger'),patch('fresh_live.case_time_gate',return_value=10800),patch('workload_state.command',return_value=json.dumps(current)),patch('fresh_live.RecoveryLab',return_value=lab):
                backend.admit({'scenario':'s1'},p)
                self.assertTrue((base/'controller-architecture-readbacks.jsonl').exists())
                self.assertFalse((base/'cases').exists())
                lab.remote.return_value='aarch64\n'
                with self.assertRaisesRegex(RuntimeError,'must be x86_64'):backend.admit({'scenario':'s1'},p)
                self.assertFalse((base/'cases').exists())

    def test_ready_consumer_allows_controller_change_and_preserves_actual_raw(self):
        from graduation_evaluation import Campaign
        p=profile();current=hosts(p)
        with tempfile.TemporaryDirectory() as root:
            h=Campaign.__new__(Campaign);h.profile=p;h.directory=Path(root);h.state=Path(root)
            h.data={'host_identity':copy.deepcopy(p['observed_environment']['host_identity'])};h.call=Mock();h.save=Mock();h.lab=Mock();h.lab.client.cluster='cluster';h.lab.remote.return_value='x86_64\n'
            flavor={'id':'flavor','name':'flavor','vcpus':2,'ram':2048,'disk':20}
            h.lab.admin_json.side_effect=[[{'Binary':'cinder-volume','Status':'enabled','State':'up'},{'Binary':'cinder-scheduler','Status':'enabled','State':'up'}],flavor,flavor]
            env={'KUBERNETES_CONTROL_PLANE_FLAVOR':'cp','KUBERNETES_WORKER_FLAVOR':'worker'}
            with patch('graduation_evaluation.command',return_value=json.dumps(current)),patch.dict(os.environ,env):
                h.verify_ready_environment({'run_id':'session2'})
            self.assertEqual(h.data['host_identity']['osk8s-controller']['cpuPlatform'],'AMD Rome')
            self.assertEqual(h.data['controller_architecture'],'x86_64')
            current[1]['cpuPlatform']='Intel Ice Lake'
            with patch('graduation_evaluation.command',return_value=json.dumps(current)),self.assertRaisesRegex(RuntimeError,'identity/platform changed'):
                h.verify_ready_environment({'run_id':'session3'})

    def test_cli_live_validate_and_freeze_consume_operational_policy(self):
        import fresh_campaign
        p=profile();p['operations']['controller_platform_policy']['architecture']='aarch64'
        with patch('fresh_campaign.load',return_value=p),patch.object(sys,'argv',['fresh_campaign.py','validate']),redirect_stdout(io.StringIO()),self.assertRaises(SystemExit) as stopped:
            fresh_campaign.main()
        self.assertEqual(stopped.exception.code,2)
        with tempfile.TemporaryDirectory() as root,patch('fresh_campaign.load',return_value=p),self.assertRaises(ValueError):
            fresh_campaign.freeze('/unused/profile',Path(root)/'campaign','development',synthetic=True)
        self.assertFalse((Path(root)/'campaign').exists())

    def test_pilot_contract_and_full_policy_hash_bind_controller_gate(self):
        p=profile();q=copy.deepcopy(p);q['operations'].pop('controller_platform_policy')
        self.assertNotEqual(pilot_contract(p,'s1'),pilot_contract(q,'s1'))
        policy=policy_manifest(source_hashes())
        for name in ('evaluation/fresh_identity.py','evaluation/fresh_live.py','evaluation/graduation_evaluation.py'):
            self.assertIn(name,policy)


if __name__=='__main__':unittest.main()
