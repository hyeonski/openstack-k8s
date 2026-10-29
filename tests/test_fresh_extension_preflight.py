import copy
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/d) for d in ('evaluation','scripts','experiments')]
from fresh_extension_preflight import (assert_v12, lock_status, evaluation_processes,
                                       preflight, RESERVED_SECONDS)
from fresh_extension import require_committed_source
from lib.state import atomic_json


class ExtensionPreflightTests(unittest.TestCase):
    def test_v12_rejects_scientific_or_identity_drift(self):
        old={'hosts':{'host':'type'},'s2':{'slo_ms':500},'operations':{'artifact_root':'old',
              'stability':{'credit_reference':{'path':'old','sha256':'old'}}}}
        new=copy.deepcopy(old);new['operations']['artifact_root']='/new/bed-extension-v12'
        new['operations']['stability']['credit_reference']={'path':'new','sha256':'new'}
        self.assertEqual(len(assert_v12(new,old)),3)
        for key in ('hosts','s2'):
            changed=copy.deepcopy(new);changed[key]={}
            with self.assertRaisesRegex(ValueError,'only'):assert_v12(changed,old)

    def test_locked_file_blocks_and_empty_unlocked_file_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'campaign.lock';path.write_bytes(b'preserved')
            with path.open('rb') as stream:
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
                self.assertFalse(lock_status([path])['passed'])
            self.assertTrue(lock_status([path])['passed'])
            self.assertEqual(path.read_bytes(),b'preserved')
            missing=Path(temp)/'missing.lock'
            self.assertTrue(lock_status([missing])['passed']);self.assertFalse(missing.exists())

    def test_process_filter_blocks_live_runner_but_allows_guard_and_self(self):
        sample='''1 /usr/bin/python3 /project/evaluation/fresh_campaign.py run
2 /usr/bin/python3 /project/evaluation/fresh_clock_guard.py --serve 501
3 python3 /project/evaluation/fresh_extension_preflight.py --profile p
4 python3 /project/experiments/graduation_s2.py run
5 /usr/bin/python3 -I -S /Library/Application Support/openstack-k8s-clock-guard/service.py --serve 501
'''
        self.assertEqual([p['pid'] for p in evaluation_processes(sample,{3})],[1,4])

    def test_source_requires_clean_commit_including_untracked_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            def git(*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE,text=True).strip()
            git('init');git('config','user.name','Test');git('config','user.email','test@example.invalid')
            (root/'source').write_text('before');git('add','source');git('commit','-m','fixture')
            self.assertEqual(require_committed_source(root),git('rev-parse','HEAD'))
            (root/'new').write_text('untracked')
            with self.assertRaisesRegex(ValueError,'clean committed'):require_committed_source(root)
            (root/'new').unlink();(root/'source').write_text('modified')
            with self.assertRaisesRegex(ValueError,'clean committed'):require_committed_source(root)

    def fixture(self, root):
        (root/'evaluation').mkdir();(root/'evaluation/fresh_clock_guard.py').write_text('service')
        service=root/'service';service.mkdir();installed=service/'service.py';installed.write_text('service')
        atomic_json(service/'state.json',dict(status='restored',original_network_time=True,restored_network_time=True))
        request=root/'request';request.mkdir()
        state=root/'.state/env';state.mkdir(parents=True)
        ledger=root/'ledger.json';atomic_json(ledger,dict(environment='env',project='project',sessions=[{'stopped':'closed'}]))
        old=dict(environment='env',project='project',zone='zone',hosts={'a':'type','b':'type','c':'type'},
                 operations=dict(artifact_root='old',bed_ledger_path=str(ledger),
                     stability=dict(credit_reference={'path':'old','sha256':'old'},read_identity={'hosts':{'a':'1','b':'2','c':'3'}})))
        new=copy.deepcopy(old);new['operations']['artifact_root']=str(root/'bed-extension-v12')
        new['operations']['stability']['credit_reference']={'path':'new','sha256':'new'}
        prior=root/'v11.json';profile=root/'v12.json';atomic_json(prior,old);atomic_json(profile,new)
        self.hosts=[dict(name=n,id=str(i),machineType='types/type',zone='zones/zone',status='TERMINATED') for i,n in enumerate('abc',1)]
        self.pmset='AC Power:\n sleep 0\n';self.calls=[]
        def run(*args):
            self.calls.append(args)
            if args[0]=='gcloud':return json.dumps(self.hosts)
            if args[0]=='/bin/launchctl':return 'state = running'
            if args==('/usr/bin/pmset','-g','batt'):return "Now drawing from 'AC Power'"
            if args[0]=='/usr/bin/pmset':return self.pmset
            if args[0]=='/bin/ps':return ''
            if args[0]=='git':return 'codex/fresh-evaluation-execution-20261026'
            raise AssertionError(args)
        return dict(profile_path=profile,previous_path=prior,root=root,state=state,run=run,
                    service_root=service,request_root=request,installed_service=installed),new

    def test_preflight_aggregates_failures_without_mutations(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);kwargs,profile=self.fixture(root)
            before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch('fresh_extension_preflight.load',return_value=profile), \
                 patch('fresh_extension_preflight.validate_controller_policy'), \
                 patch('fresh_extension_preflight.require_committed_source',return_value='commit'), \
                 patch('fresh_extension_preflight.source_hashes',return_value={'source':'sha'}), \
                 patch('fresh_extension_preflight.audit',return_value={'calls':348}), \
                 patch('fresh_extension_preflight.forward_credit',return_value={'margin_krw':100}) as credit:
                result=preflight(**kwargs)
                self.assertTrue(result['passed'],result)
                credit.assert_called_with(profile,RESERVED_SECONDS)
                self.assertEqual(before,{str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()})
                (kwargs['request_root']/'request.json').write_text('{}')
                pending=preflight(**kwargs)
                self.assertFalse(pending['checks']['clock_guard']['passed'])
                (kwargs['request_root']/'request.json').unlink()
                self.hosts[0]['status']='RUNNING';self.pmset='AC Power:\n sleep 10\n'
                atomic_json(kwargs['service_root']/'state.json',{'status':'protected'})
                atomic_json(root/'ledger.json',dict(environment='env',project='project',sessions=[{'stopped':None}]))
                result=preflight(**kwargs)
                self.assertFalse(result['passed'])
                self.assertEqual({k for k,v in result['checks'].items() if not v['passed']},
                                 {'clock_guard','sleep_prevention','hosts','ledger'})
            cloud=[call for call in self.calls if call[0]=='gcloud']
            self.assertTrue(all(call[1:4]==('compute','instances','list') for call in cloud))

    def test_pending_clock_request_or_command_failure_is_not_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);kwargs,profile=self.fixture(root)
            (kwargs['request_root']/'request.json').write_text('{}')
            def fail(*args):raise RuntimeError('read unavailable')
            kwargs['run']=fail
            with patch('fresh_extension_preflight.load',return_value=profile), \
                 patch('fresh_extension_preflight.validate_controller_policy'), \
                 patch('fresh_extension_preflight.forward_credit',return_value={'margin_krw':-1}):
                result=preflight(**kwargs)
            self.assertFalse(result['passed'])
            self.assertFalse(result['checks']['clock_guard']['passed'])
            self.assertFalse(result['checks']['hosts']['passed'])
            self.assertFalse(result['checks']['credit']['passed'])


if __name__=='__main__':unittest.main()
