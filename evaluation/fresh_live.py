"""Live bridge for a future authorized pilot. Imported only by explicit live run."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import shutil
import sys

from lib.state import atomic_json
from graduation_evaluation import Campaign
from graduation_recovery import RecoveryLab
from fresh_evidence import epoch


class LiveBackend:
    def __init__(self, directory):
        self.directory=Path(directory)
        self.state=Path(os.environ['STATE_DIR'])
        self.lock=(self.state/'graduation-evaluation.lock').open('a+')
        fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)

    def helper(self, profile, ev):
        # Reuse environment/owned fixture cleanup, not the legacy schedule or verifier.
        h=Campaign.__new__(Campaign)
        h.directory=ev.directory;h.path=ev.directory/'fixture-ledger.json'
        h.profile=profile;h.state=self.state;h.lab=RecoveryLab('s3')
        contract=self.directory/'runtime-environment.json'
        h.data=json.loads(contract.read_text()) if contract.exists() else {}
        return h

    def require_clean_state(self):
        for name,allowed in (('s1-preparation.json',{'restored'}),('s1-auto.json',{'completed'}),
                             ('s1-contention.json',{'completed'}),('s2-experiment.json',{'cleaned'}),
                             ('s3-experiment.json',{'cleaned'}),('s4-preparation.json',{'restored'})):
            path=self.state/name
            if path.exists() and json.loads(path.read_text()).get('phase') not in allowed:
                raise RuntimeError('unfinished fixture blocks environment changes: '+name)
        record=self.state/'s4-experiment.json';prep=self.state/'s4-preparation.json'
        if record.exists() and json.loads(record.read_text()).get('phase') not in ('completed','completed_with_gap') and (not prep.exists() or json.loads(prep.read_text()).get('phase')!='restored'):
            raise RuntimeError('unfinished S4 experiment requires owned cleanup before environment changes')

    def execute(self, case, profile, ev):
        from workload_state import ROOT
        self.require_clean_state()
        h=self.helper(profile,ev)
        h.data['cases']=[case]
        prior=h.state_record(case['scenario'])
        prep_path=self.state/'s4-preparation.json'
        prep=json.loads(prep_path.read_text()) if prep_path.exists() else {}
        atomic_json(ev.directory/'prior-state.json',{'run_id':prior.get('run_id') if prior else None,'preparation_run_id':prep.get('run_id')})
        environment=h.environment()
        case['environment_run_id']=environment['run_id']
        atomic_json(self.directory/'runtime-environment.json',{k:h.data[k] for k in ('host_identity','flavors')})
        atomic_json(ev.directory/'runtime-environment.json',{k:h.data[k] for k in ('host_identity','flavors')})
        h.prepare_workers(case)
        if case['scenario']=='s1':h.make('graduation-s1-prepare','prepare.log')
        atomic_json(ev.directory/'case-contract.json',case)
        atomic_json(ev.directory/'profile-contract.json',profile)
        h.call([sys.executable,ROOT/'evaluation/fresh_scenarios.py',
                '--case',ev.directory/'case-contract.json','--profile',ev.directory/'profile-contract.json',
                '--evidence',ev.directory], 'run.log',timeout=profile['max_case_seconds'])

    def cleanup(self, case, profile, ev):
        h=self.helper(profile,ev)
        # Persisted ownership records are authoritative after lost responses/process interruption.
        ledger=ev.directory/'fixture-ledger.json'
        if ledger.is_file():
            for saved in json.loads(ledger.read_text()).get('cases',[]):
                if saved['id']==case['id']:
                    for key in ('original_worker','placement','migration','environment_run_id'):
                        if key in saved:case[key]=saved[key]
        record=h.state_record(case['scenario'])
        prior_path=ev.directory/'prior-state.json'
        previous=json.loads(prior_path.read_text()).get('run_id') if prior_path.exists() else None
        fresh_record=bool(record and record.get('run_id')!=previous and record.get('environment_run_id')==case.get('environment_run_id') and record.get('fresh_attempt')==str(ev.directory.resolve()))
        if record and record.get('run_id')!=previous and not fresh_record:
            raise RuntimeError('experiment record is not owned by this attempt; refusing cleanup')
        if record and not fresh_record and record.get('phase') not in ('completed','completed_with_gap','cleaned'):
            raise RuntimeError('prior experiment is unfinished; refusing to adopt it for cleanup')
        if fresh_record:
            metadata_path=ev.directory/'environment.json'
            metadata=json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
            metadata.update(environment_run_id=case.get('environment_run_id'),actual_placement=case.get('placement'),
                            environment_snapshot=next((str(p.name) for p in ev.directory.glob('environment-*.json')),None),
                            version_profile=profile['kubernetes_version'],raw_experiment_path=record['evidence'])
            atomic_json(metadata_path,metadata)
            case.update(run_id=record['run_id'])
            before=ev.directory/'raw-before-cleanup'
            if Path(record['evidence']).is_dir() and not before.exists():
                shutil.copytree(record['evidence'],before)
        if case['scenario']=='s4':
            # off retains the stopped original worker; rescue is strictly after H.
            from graduation_s4_run import nova_status
            from graduation_recovery import wait_for
            prep_path=self.state/'s4-preparation.json'
            prep=json.loads(prep_path.read_text()) if prep_path.exists() else {}
            target=record.get('target') if fresh_record else None
            if not fresh_record and prep and prep.get('phase')!='restored':
                prior=json.loads(prior_path.read_text()) if prior_path.exists() else {}
                if prep.get('environment_run_id')!=case.get('environment_run_id') or prep.get('run_id')==prior.get('preparation_run_id'):
                    raise RuntimeError('S4 preparation is not owned by this attempt')
            servers=h.lab.admin_json('server','list','--all-projects')
            present=next((s for s in servers if (s.get('ID') or s.get('id'))==(target or {}).get('nova_id')),None)
            if target and present:
                machine=h.lab.obj('machine',target['machine'],plane='m')
                node=h.lab.obj('node',target['node'],False)
                if not machine or machine['metadata']['uid']!=target['machine_uid'] or machine['metadata'].get('deletionTimestamp') or not node or node['metadata']['uid']!=target['node_uid']:
                    raise RuntimeError('S4 target identity/deletion changed; await native reconciliation before rescue')
            if present and (present.get('Status') or present.get('status'))=='SHUTOFF':
                ev.event('rescue_requested',target=target['nova_id'],actor='cleanup')
                h.lab.admin('server','start',target['nova_id'])
            if present and (case.get('mode')=='off' or (present.get('Status') or present.get('status'))=='SHUTOFF'):
                # A previous start may have succeeded before its response was lost.
                # ACTIVE alone is insufficient: keep MHC paused until Node Ready.
                wait_for(lambda: nova_status(target['nova_id'])['status']=='ACTIVE',seconds=180)
                from workload_state import condition
                wait_for(lambda:condition(h.lab.obj('node',target['node'],False),'Ready'),seconds=300)
            # Restore owned MHC pause before ordinary fixture cleanup, including interrupted off.
            owned=ev.directory/'mhc-ownership.json'
            if owned.is_file():
                from fresh_scenarios import restore_mhc
                restore_mhc(h.lab,json.loads(owned.read_text()),ev)
            if fresh_record and record.get('phase') not in ('completed','completed_with_gap'):
                # Explicit rescue/cleanup can close a failed observation without claiming recovery.
                h.make('graduation-s4-cleanup','cleanup-rescue.log')
        h.cleanup_case(case)
        # Preserve scenario raw as produced; normalized contract keeps its field-level provenance.
        if fresh_record and Path(record['evidence']).is_dir():
            target=ev.directory/'raw'
            if not target.exists():shutil.copytree(record['evidence'],target)
        proof=json.loads((ev.directory/'cases'/case['id']/'cleanup-verification.json').read_text())
        return {'actor':'cleanup','checks':proof['checks'],'source':'cases/'+case['id']+'/cleanup-verification.json'}
