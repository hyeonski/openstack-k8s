"""Live bridge for a future authorized pilot. Imported only by explicit live run."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import shutil
import sys
import time

from lib.state import atomic_json
from graduation_evaluation import Campaign
from graduation_recovery import RecoveryLab
from fresh_evidence import epoch, utc
from fresh_operations import phase, case_time_gate, BedLedger
from fresh_identity import validate_controller_policy, read_controller_architecture, identity_matches


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

    def admit(self, case, profile):
        from workload_state import command
        validate_controller_policy(profile,live=True)
        self.require_clean_state()
        ops=profile['operations']
        for key in ('artifact_root','development_artifact_root'):
            for saved in Path(ops[key]).rglob('campaign.json'):
                data=json.loads(saved.read_text())
                if data.get('synthetic'):continue
                for prior in data.get('cases',[]):
                    if prior.get('attempts') and prior['attempts'][-1]['state']!='VERIFIED':
                        raise RuntimeError('unfinished attempt blocks admission; resume-cleanup: '+str(saved.parent)+' '+prior['id'])
                    result=prior.get('judgement',{})
                    if result.get('trial_valid') and result.get('safety') is not True:
                        raise RuntimeError('prior safety violation blocks environment; preserve evidence and investigate')
        reserved=case_time_gate(profile)
        ledger=BedLedger(profile)
        ledger.require_active()
        ledger.gate(reserved)
        admission_until=os.environ.get('FRESH_ADMISSION_DEADLINE_UTC')
        with phase('admission readback',min(120,ops['fixture_prepare_timeout_seconds']),
                   until=float(admission_until) if admission_until else None):
            record=json.loads((self.state/'graduation-environment.json').read_text())
            if record.get('phase')!='ready':
                raise RuntimeError('environment not ready; explicit down/ensure required before attempt')
            hosts=json.loads(command(['gcloud','compute','instances','list','--project='+profile['project'],
                                      '--format=json(name,id,status,machineType,cpuPlatform,lastStartTimestamp,scheduling)']))
            hosts={h['name']:h for h in hosts if h['name'] in profile['hosts']}
            if set(hosts)!=set(profile['hosts']) or any(h['status']!='RUNNING' for h in hosts.values()):
                raise RuntimeError('case admission: hosts are not all RUNNING; no internal ensure')
            identity={n:dict(id=str(h['id']),machine_type=h['machineType'].split('/')[-1],cpuPlatform=h['cpuPlatform']) for n,h in hosts.items()}
            expected=profile.get('observed_environment',{}).get('host_identity')
            architecture=read_controller_architecture(profile,RecoveryLab('s3'),self.directory/'controller-architecture-readbacks.jsonl')
            if not expected or not identity_matches(profile,expected,identity,architecture):
                raise RuntimeError('case admission: actual host identity/platform differs from registered readback')
            for name,host in hosts.items():
                saved=record['final_hosts'][name]
                from fresh_host_lifetime import effective_host_deadline
                deadline=effective_host_deadline(profile,host)
                if saved['id']!=str(host['id']) or abs(epoch(saved['last_start'])-epoch(host['lastStartTimestamp']))>.001:
                    raise RuntimeError('case admission: environment host start changed')
                if deadline is not None and deadline-time.time()<profile['host_headroom_seconds']:
                    raise RuntimeError('case admission: host lifetime insufficient; explicit down/ensure required')

    def environment_action(self, profile, action):
        from fresh_evidence import Evidence
        from workload_state import command
        self.require_clean_state()
        validate_controller_policy(profile,live=True)
        ops=profile['operations']
        ledger=BedLedger(profile)
        if action=='rotate':
            reserved=case_time_gate(profile,rotate=True)
            ledger.gate(reserved)
            down=self.environment_action(profile,'down')
            ensure=self.environment_action(profile,'ensure')
            return {'down':str(down),'ensure':str(ensure)}
        ev=Evidence(self.directory/('environment-'+action+'-'+str(time.time_ns())))
        h=self.helper(profile,ev)
        if action=='ensure':
            reserved=case_time_gate(profile,cold=True)
            ledger.gate(reserved)
            # This records the entire ensure interval even if the process crashes.
            ledger.begin()
            seconds=ops['environment_ensure_timeout_seconds']
            until=epoch(ops['hard_stop_utc'])-reserved+seconds
        else:
            seconds=ops['host_shutdown_timeout_seconds']
            until=epoch(ops['hard_stop_utc'])
        from fresh_host_lifetime import time_targets_only
        if time_targets_only(profile):until=None
        with phase('environment '+action,seconds,ev.directory/'phases.jsonl',until):
            h.make('graduation-env-'+action,'environment.log',timeout=seconds)
            record=json.loads((self.state/'graduation-environment.json').read_text())
            atomic_json(ev.directory/'environment-record.json',record)
            if action=='down':
                hosts=json.loads(command(['gcloud','compute','instances','list','--project='+profile['project'],
                    '--format=json(name,id,status,machineType)']))
                selected={r['name']:r for r in hosts if r['name'] in profile['hosts']}
                if set(selected)!=set(profile['hosts']):raise RuntimeError('shutdown verification hosts missing')
                ledger.stopped(selected)
        return ev.directory

    def execute(self, case, profile, ev):
        from workload_state import ROOT
        from fresh_calibration import TransportWatch
        self.require_clean_state()
        h=self.helper(profile,ev)
        h.data['cases']=[case]
        prior=h.state_record(case['scenario'])
        prep_path=self.state/'s4-preparation.json'
        prep=json.loads(prep_path.read_text()) if prep_path.exists() else {}
        atomic_json(ev.directory/'prior-state.json',{'run_id':prior.get('run_id') if prior else None,'preparation_run_id':prep.get('run_id')})
        ops=profile['operations']
        deadline=time.time()+ops['fixture_prepare_timeout_seconds']
        with phase('fixture readiness/workers',ops['fixture_prepare_timeout_seconds'],ev.directory/'phases.jsonl'), TransportWatch(h,ev.directory/'preparation-transport'):
            record=json.loads((self.state/'graduation-environment.json').read_text())
            if record.get('phase')!='ready':raise RuntimeError('environment lost readiness after admission')
            environment=h.verify_ready_environment(record)
            case['environment_run_id']=environment['run_id']
            observed={k:h.data[k] for k in ('host_identity','flavors')}
            if h.data.get('controller_architecture') is not None:
                observed['controller_architecture']=h.data['controller_architecture']
            if not identity_matches(profile,profile['observed_environment']['host_identity'],observed['host_identity'],observed.get('controller_architecture')):
                raise RuntimeError('host identity changed during preparation')
            atomic_json(self.directory/'runtime-environment.json',observed)
            atomic_json(ev.directory/'runtime-environment.json',observed)
            h.prepare_workers(case)
            if case['scenario']=='s1':h.make('graduation-s1-prepare','prepare.log')
        atomic_json(ev.directory/'case-contract.json',case)
        atomic_json(ev.directory/'profile-contract.json',profile)
        old=os.environ.get('FRESH_FIXTURE_DEADLINE_UTC')
        os.environ['FRESH_FIXTURE_DEADLINE_UTC']=str(deadline)
        lifetime_keys=('FRESH_HOST_RUNTIME_LIMIT','FRESH_OPERATIONAL_HARD_STOP_UTC','FRESH_TIME_POLICY')
        prior_lifetime={key:os.environ.get(key) for key in lifetime_keys}
        os.environ['FRESH_HOST_RUNTIME_LIMIT']='disabled' if ops.get('host_lifetime_policy') else 'bounded'
        os.environ['FRESH_OPERATIONAL_HARD_STOP_UTC']=ops['hard_stop_utc']
        from fresh_host_lifetime import time_targets_only
        os.environ['FRESH_TIME_POLICY']='cost-bounded-targets-only' if time_targets_only(profile) else 'bounded'
        try:
            with phase('adapter',profile['max_case_seconds'],ev.directory/'phases.jsonl',None if time_targets_only(profile) else epoch(ops['drain_utc'])):
                h.call([sys.executable,ROOT/'evaluation/fresh_scenarios.py',
                        '--case',ev.directory/'case-contract.json','--profile',ev.directory/'profile-contract.json',
                        '--evidence',ev.directory], 'run.log',timeout=profile['max_case_seconds'])
        finally:
            if old is None:os.environ.pop('FRESH_FIXTURE_DEADLINE_UTC',None)
            else:os.environ['FRESH_FIXTURE_DEADLINE_UTC']=old
            for key,value in prior_lifetime.items():
                if value is None:os.environ.pop(key,None)
                else:os.environ[key]=value

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
        from fresh_calibration import TransportWatch
        with TransportWatch(h,ev.directory/'cleanup-transport'):
            h.cleanup_case(case)
        # Preserve scenario raw as produced; normalized contract keeps its field-level provenance.
        if fresh_record and Path(record['evidence']).is_dir():
            target=ev.directory/'raw'
            if not target.exists():shutil.copytree(record['evidence'],target)
        proof=json.loads((ev.directory/'cases'/case['id']/'cleanup-verification.json').read_text())
        return {'actor':'cleanup','checks':proof['checks'],'source':'cases/'+case['id']+'/cleanup-verification.json'}
