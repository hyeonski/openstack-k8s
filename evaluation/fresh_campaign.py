"""Append-only fresh campaigns, frozen inputs and explicit attempt lifecycle."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / d) for d in ('scripts', 'experiments')]
from lib.state import atomic_json
from fresh_contract import digest, load, schedule, validate
from fresh_evidence import Evidence, append, utc, epoch
from fresh_analysis import judge, read, rows
from fresh_operations import PHASE_LIMITS, TIME_KEYS, phase, case_time_gate
from fresh_identity import validate_controller_policy
from fresh_host_lifetime import time_targets_only


def source_hashes(root=ROOT):
    # Include entire mixed policy/instrumentation modules: never silently exempt a policy edit.
    # Respect ignored local overrides/generated secrets before reading file contents.
    inventory = subprocess.run(['git', '-C', str(root), 'ls-files', '--cached', '--others',
                                '--exclude-standard', '-z'], capture_output=True, check=True)
    eligible = {name for name in inventory.stdout.decode().split('\0') if name}
    paths = [root / 'Makefile']
    for d in ('evaluation','experiments','scripts','config','kubernetes','make','ansible','kolla','systemd','infra/gcp','observability','tests'):
        paths += [p for p in (root / d).rglob('*') if p.is_file() and '__pycache__' not in p.parts
                  and '.terraform' not in p.parts and p.suffix in ('.py','.sh','.json','.yaml','.yml','.mk','.env','.tf','.j2','.tpl','.service')]
    paths += [root/'docs/graduation'/name for name in ('fresh-evaluation-build-plan-2026-10-26.md','fresh-evaluation-run-plan-2026-10-26.md','consensus-research-plan-2026-10-26.md','consensus-discussion-2026-10-26/README.md','fresh-execution-settings-2026-10-26.md','fresh-evaluation-execution-prompt-2026-10-26.md')]
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(paths)) if str(p.relative_to(root)) in eligible}


def policy_manifest(source):
    return {name: value for name, value in source.items() if name.startswith(('experiments/','scripts/','kubernetes/')) or name in ('evaluation/fresh_transport.py','evaluation/fresh_transport_release.py','evaluation/fresh_pause.py','evaluation/fresh_host_lifetime.py','evaluation/fresh_collection.py','evaluation/fresh_scenarios.py','evaluation/fresh_live.py','evaluation/fresh_contract.py','evaluation/fresh_campaign.py','evaluation/fresh_baseline.py','evaluation/fresh_operations.py','evaluation/fresh_identity.py','evaluation/fresh_analysis.py','evaluation/fresh_evidence.py','evaluation/graduation_evaluation.py','evaluation/graduation_evaluation_case.py')}


def pilot_contract(profile, scenario):
    """Calibration must have tested this scenario's main contract, not merely its code."""
    common=('seed','environment','project','zone','hosts','kubernetes_version',
            'source_compute','target_compute','control_plane_compute','analysis')
    result={key:profile[key] for key in common}
    result['observed_environment']=profile.get('observed_environment')
    result.update(measurement=profile[scenario],fault=profile['fault'][scenario])
    result['execution_limits']={k:profile.get(k) for k in ('max_case_seconds','host_headroom_seconds')}
    result['execution_limits'].update({k:profile['operations'].get(k) for k in (*PHASE_LIMITS,*TIME_KEYS,'bed_uptime_limit_seconds','bed_uptime_soft_limit_seconds','clock_failure_stop_after_attempts')})
    result['controller_platform_policy']=profile['operations'].get('controller_platform_policy')
    result['host_lifetime_policy']=profile['operations'].get('host_lifetime_policy')
    fixture={'s2':'s2_port_qos_workload_progress','s3':'s3_volume_seed','s4':'s4_capacity'}
    if scenario in fixture:result['fixture']=profile['initial_fixture'][fixture[scenario]]
    if scenario=='s1':
        result.update(v1_candidates=profile['v1_candidates'],v1_selected=profile['v1_selected'],v1_condition=profile['v1_condition'])
    if scenario in ('s3','s4'):result['timers']=profile['timers']
    return result


def freeze(profile_path, destination, stage, scenario=None, policy_path=None, synthetic=False, pilot_campaign=None, previous_campaign=None):
    profile_path = Path(profile_path).resolve()
    profile = load(profile_path, live=not synthetic)
    validate_controller_policy(profile, live=not synthetic)
    destination = Path(destination).resolve()
    if destination == ROOT or ROOT.is_relative_to(destination):
        raise ValueError('campaign must have a dedicated artifact directory')
    if stage not in ('main','preparation','development'):raise ValueError('unknown stage')
    selected = ([dict(id='dev-s1-a',scenario='s1',mode='A',purpose='development',block='dev01',seed=profile['seed'],session='DEVELOPMENT',order=1,depends_on=[],status='pending',negative=False)] if stage=='development' else
                [c for c in schedule(profile) if (c['purpose'] == 'main') == (stage == 'main') and (not scenario or c['scenario'] == scenario)])
    selected_ids={c['id'] for c in selected}
    if any(dep not in selected_ids for c in selected for dep in c.get('depends_on',[])):
        raise ValueError('selected campaign does not include its explicit dependencies')
    if not selected:
        raise ValueError('empty campaign selection')
    source = source_hashes()
    policy = policy_manifest(source)
    if not synthetic and stage == 'main' and not policy_path:
        raise ValueError('main requires --policy-manifest from approved preparation freeze')
    if policy_path and read(policy_path) != policy:
        raise ValueError('policy manifest differs; new research release required')
    if not synthetic:
        ops = profile['operations']
        if any(os.environ.get(k)!=profile[v] for k,v in [('ENVIRONMENT_NAME','environment'),('GCP_PROJECT_ID','project'),('GCP_ZONE','zone')]):
            raise ValueError('explicit environment/project/zone override must match profile')
        if Path(ops['execution_checkout']).resolve() != ROOT:
            raise ValueError('execution checkout must match frozen source checkout')
        override = Path(os.environ.get('ENV_OVERRIDE_FILE', ''))
        if not override.is_file() or override.resolve() != Path(ops['environment_override']).resolve():
            raise ValueError('explicit environment override path does not match profile')
        root_key='development_artifact_root' if stage=='development' else 'artifact_root'
        if not destination.is_relative_to(Path(ops[root_key]).resolve()):
            raise ValueError('campaign must be inside registered artifact root')
        case_time_gate(profile)
    pilot_manifest = check_frozen(pilot_campaign) if pilot_campaign else None
    if not synthetic and stage=='main':
        if not pilot_campaign:
            raise ValueError('main requires --pilot-campaign with independently valid preparation evidence')
        pilot=report(pilot_campaign)
        if pilot['stage']!='preparation' or pilot['missingness']:
            raise ValueError('preparation campaign incomplete')
        required={c['id'] for c in profile['cases'] if c['purpose']!='main' and (not scenario or c['scenario']==scenario)}
        valid={r['case_id'] for r in pilot['run_results'] if r['trial_valid'] and r.get('safety') is True and r.get('cleanup') is True and r.get('fault_realized') is True and (r['mode'] not in ('P','P3600','on') or r.get('recovered') is True) and (r['mode']!='V1' or r['v1_outcome']=='held')}
        if not required.issubset(valid):
            raise ValueError('required smoke/pilot evidence missing or invalid')
        if pilot_manifest['policy_sha256']!=digest(policy):
            raise ValueError('pilot policy differs from main')
        for selected_scenario in {c['scenario'] for c in selected}:
            if pilot_contract(profile,selected_scenario)!=pilot_contract(pilot_manifest['profile'],selected_scenario):
                raise ValueError('main contract differs from validated pilot: '+selected_scenario+'; run a new pilot')
        # The first main waits for the complete registered wave, even with per-scenario freezes.
        wave_valid=set(valid)
        for saved in Path(profile['operations']['artifact_root']).rglob('campaign.json'):
            previous=read(saved,{})
            if previous.get('schema_version')!=3 or previous.get('synthetic') or previous.get('stage')!='preparation':continue
            if previous['policy_sha256']!=digest(policy):continue
            check_frozen(saved.parent,current=True)
            previous_report=report(saved.parent)
            for row in previous_report['run_results']:
                s=row['scenario']
                if pilot_contract(profile,s)!=pilot_contract(previous['profile'],s):continue
                if row['trial_valid'] and row.get('safety') is True and row.get('cleanup') is True and row.get('fault_realized') is True and (row['mode'] not in ('P','P3600','on') or row.get('recovered') is True) and (row['mode']!='V1' or row.get('v1_outcome')=='held'):
                    wave_valid.add(row['case_id'])
        if not {c['id'] for c in profile['cases'] if c['purpose']!='main'}.issubset(wave_valid):
            raise ValueError('all four scenario pilot go/no-go decisions required before the first main')
    if not synthetic:
        for saved in Path(profile['operations']['artifact_root']).rglob('campaign.json'):
            existing=read(saved,{})
            if existing.get('status')=='running' or any(c.get('status')=='running' for c in existing.get('cases',[])):
                raise ValueError('active campaign exists; use its frozen execution checkout: '+str(saved))
            if stage=='preparation' and existing.get('stage')=='preparation' and not existing.get('synthetic') and existing.get('policy_sha256')==digest(policy):
                for selected_scenario in {c['scenario'] for c in selected}&{c['scenario'] for c in existing['cases']}:
                    if pilot_contract(profile,selected_scenario)==pilot_contract(existing['profile'],selected_scenario):
                        raise ValueError('same pilot contract already frozen; resume existing campaign/retry, never select a new successful pilot')
            if stage=='main' and existing.get('schema_version')==3 and not existing.get('synthetic') and existing.get('stage')=='main':
                if existing['policy_sha256']!=digest(policy):
                    raise ValueError('policy differs from existing main research release; isolate a new artifact root/release')
                if any(c['scenario']=='s1' for c in selected) and any(c['scenario']=='s1' for c in existing['cases']):
                    raise ValueError('all S1 main sessions must use the same existing freeze')
    change_audit=None
    if previous_campaign:
        prior=check_frozen(previous_campaign)
        changed={n for n in source.keys()|prior['source_sha256'].keys() if source.get(n)!=prior['source_sha256'].get(n)}
        allowed=set(profile['operations'].get('tool_change_allowlist',[]))
        if policy!=read(Path(previous_campaign)/'policy-manifest.json') or not changed.issubset(allowed):
            raise ValueError('change crosses policy boundary or tool change allowlist')
        analysis=profile['operations'].get('impact_analysis')
        if not isinstance(analysis,dict) or analysis.get('judgement_semantics_changed') is not False or analysis.get('policy_changed') is not False or not analysis.get('reason') or not analysis.get('affected_scenarios'):
            raise ValueError('tool change requires structured impact_analysis; policy/common judgement changes require a new research release')
        import difflib
        diffs={n:''.join(difflib.unified_diff((Path(previous_campaign)/'source'/n).read_text().splitlines(True) if (Path(previous_campaign)/'source'/n).exists() else [],(ROOT/n).read_text().splitlines(True) if (ROOT/n).exists() else [],fromfile='previous/'+n,tofile='current/'+n)) for n in changed}
        change_audit=dict(previous_campaign=prior['id'],changed=sorted(changed),diff=diffs,impact_analysis=analysis)
    profile_blob=profile_path.read_bytes()
    if json.loads(profile_blob)!=profile:
        raise ValueError('selected profile changed while freezing')
    destination.mkdir(parents=True, exist_ok=False)
    documents={}
    for name in profile['operations'].get('preregistered_documents',[]):
        original=ROOT/name
        documents[name]=hashlib.sha256(original.read_bytes()).hexdigest()
        target=destination/'preregistered-documents'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(original,target)
    for name in source:
        target = destination / 'source' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    (destination / 'selected-profile.json').write_bytes(profile_blob)
    for name,expected in source.items():
        if hashlib.sha256((destination/'source'/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('source changed while freezing: '+name)
    atomic_json(destination / 'policy-manifest.json', policy)
    git=subprocess.run(['git','-C',str(ROOT),'rev-parse','HEAD'],capture_output=True,text=True,timeout=10)
    manifest = dict(git_head=git.stdout.strip() if git.returncode==0 else None,schema_version=3, id='fresh-' + uuid.uuid4().hex, created=utc(),
                    synthetic=synthetic, stage=stage, scope='F-repeated', profile=profile,
                    profile_path=str(profile_path), profile_sha256=hashlib.sha256(profile_blob).hexdigest(),
                    analysis_sha256=digest(profile['analysis']), policy_sha256=digest(policy),
                    source_sha256=source, preregistered_documents_sha256=documents, cases=selected, status='frozen',
                    schedule_counts=validate(profile), historical_results='excluded')
    override = os.environ.get('ENV_OVERRIDE_FILE')
    if not synthetic:
        manifest['override_path'] = str(Path(override).resolve())
        manifest['override_sha256'] = hashlib.sha256(Path(override).read_bytes()).hexdigest()
    if pilot_campaign:
        manifest['pilot_campaign_id']=pilot_manifest['id']
        manifest['pilot_profile_changes']={key:{'pilot':pilot_manifest['profile'].get(key),'main':profile.get(key)}
            for key in profile.keys()|pilot_manifest['profile'].keys() if profile.get(key)!=pilot_manifest['profile'].get(key)}
    if change_audit:
        atomic_json(destination/'tool-change-audit.json',change_audit)
        manifest['tool_change_audit_sha256']=digest(change_audit)
    atomic_json(destination / 'campaign.json', manifest)
    # Immutable copy is authoritative; campaign.json contains mutable lifecycle only.
    atomic_json(destination / 'frozen-manifest.json', manifest)
    (destination / 'manifest.sha256').write_text(digest(manifest) + '\n')
    return destination


def check_frozen(directory, current=False):
    directory = Path(directory)
    frozen = read(directory / 'frozen-manifest.json')
    if not frozen or digest(frozen) != (directory / 'manifest.sha256').read_text().strip():
        raise ValueError('frozen manifest changed')
    data = read(directory / 'campaign.json')
    for key in frozen.keys()-{'cases','status'}:
        if data.get(key) != frozen[key]:
            raise ValueError('campaign frozen field changed: ' + key)
    contract_keys = ('id','scenario','mode','purpose','block','seed','order','session','depends_on')
    if [[c.get(k) for k in contract_keys] for c in data['cases']] != [[c.get(k) for k in contract_keys] for c in frozen['cases']]:
        raise ValueError('campaign schedule changed')
    if hashlib.sha256((directory / 'selected-profile.json').read_bytes()).hexdigest() != frozen['profile_sha256']:
        raise ValueError('selected profile snapshot changed')
    if digest(read(directory / 'policy-manifest.json')) != frozen['policy_sha256']:
        raise ValueError('policy manifest changed')
    for name, expected in frozen['source_sha256'].items():
        if hashlib.sha256((directory / 'source' / name).read_bytes()).hexdigest() != expected:
            raise ValueError('source snapshot changed: ' + name)
    for name,expected in frozen.get('preregistered_documents_sha256',{}).items():
        if hashlib.sha256((directory/'preregistered-documents'/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('preregistered document snapshot changed: '+name)
        if current and hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('preregistered document changed: '+name)
    if frozen.get('tool_change_audit_sha256') and digest(read(directory/'tool-change-audit.json'))!=frozen['tool_change_audit_sha256']:
        raise ValueError('tool change audit changed')
    if frozen.get('transport_transition_sha256') and digest(read(directory/'transport-transition.json')) != frozen['transport_transition_sha256']:
        raise ValueError('transport transition audit changed')
    if current:
        if source_hashes() != frozen['source_sha256']:
            raise ValueError('source changed; freeze a new cohort with diff and impact analysis')
        if hashlib.sha256(Path(frozen['profile_path']).read_bytes()).hexdigest() != frozen['profile_sha256']:
            raise ValueError('selected profile changed')
        if not frozen['synthetic']:
            override = Path(os.environ.get('ENV_OVERRIDE_FILE', '')).resolve()
            if str(override) != frozen['override_path'] or hashlib.sha256(override.read_bytes()).hexdigest() != frozen['override_sha256']:
                raise ValueError('environment override changed')
    return data


def save_cleanup(directory,proof):
    directory=Path(directory)
    index=len(list(directory.glob('cleanup-attempt-*.json')))+1
    atomic_json(directory/f'cleanup-attempt-{index:03}.json',proof)
    atomic_json(directory/'cleanup.json',proof)


def spent_budget_seconds(root, policy_sha256):
    """Sum all live cohorts in this registered release root; never reset cost per scenario."""
    total=0
    for path in Path(root).rglob('campaign.json'):
        if 'source' in path.relative_to(Path(root)).parts:continue
        campaign=read(path,{})
        if campaign.get('schema_version')!=3 or campaign.get('synthetic') or campaign.get('policy_sha256')!=policy_sha256:continue
        ledger=rows(path.parent/'attempts.jsonl')
        starts={(r['case_id'],r['attempt_id']):r for r in ledger if r['state']=='started'}
        ends={(r['case_id'],r['attempt_id']):r for r in ledger if r['state'] in ('finished','resumed_cleanup_only')}
        for key,start in starts.items():
            end=epoch(ends[key]['utc']) if key in ends else epoch(utc())
            duration=end-epoch(start['utc'])
            if duration<0:raise ValueError('attempt budget timestamps reversed')
            total+=duration
    return total


class FreshCampaign:
    def __init__(self, directory, backend):
        self.directory = Path(directory).resolve()
        self.data = check_frozen(self.directory, current=True)
        self.backend = backend
        self.profile = self.data['profile']

    def save(self):
        atomic_json(self.directory / 'campaign.json', self.data)

    def ledger(self, case, attempt, state, **fields):
        append(self.directory / 'attempts.jsonl', dict(campaign_id=self.data['id'],case_id=case['id'],
               block=case['block'],purpose=case['purpose'],attempt_id=attempt['id'],
               previous_attempt=attempt.get('previous'),actor='runner',utc=utc(),state=state,**fields))

    def run(self, limit=None, retry_case=None):
        with (self.directory / 'campaign.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.data=check_frozen(self.directory, current=True)
            for c in self.data['cases']:
                if c.get('attempts') and c['attempts'][-1]['state'] not in ('VERIFIED',):
                    raise RuntimeError('unfinished/cleanup-failed attempt; use resume-cleanup: ' + c['id'])
            if limit is not None and limit<1:
                raise ValueError('--limit must be positive')
            if retry_case and retry_case not in {c['id'] for c in self.data['cases']}:
                raise ValueError('unknown retry case')
            if retry_case:
                c = next(c for c in self.data['cases'] if c['id'] == retry_case)
                if c.get('judgement', {}).get('trial_valid'):
                    raise ValueError('valid recovery/non-recovery cannot be replaced by retry')
            count = 0
            for case in self.data['cases']:
                if retry_case and case['id'] != retry_case or not retry_case and case['status'] != 'pending':
                    continue
                if not self.data['synthetic']:
                    consumed=sum(spent_budget_seconds(self.profile['operations'][k],self.data['policy_sha256']) for k in ('artifact_root','development_artifact_root'))
                    ops=self.profile['operations']
                    if not time_targets_only(self.profile) and consumed+self.profile['max_case_seconds']+ops['cleanup_seconds']>ops['budget_seconds']:
                        raise RuntimeError('remaining registered budget cannot cover another bounded case and cleanup')
                    case_time_gate(self.profile)
                    # No attempt or case-specific mutation exists until admission succeeds.
                    self.backend.admit(case,self.profile)
                    clock_failures=[]
                    for saved in [p for k in ('artifact_root','development_artifact_root') for p in Path(ops[k]).rglob('judgement.json')]:
                        identity=read(saved.parent/'identity.json',{})
                        contract=read(saved.parent/'case-contract.json',{})
                        if identity.get('synthetic') is False and contract.get('scenario')==case['scenario']:
                            result=read(saved,{})
                            clock_failures.append((saved.stat().st_mtime,any('clock' in error for error in result.get('missing',[]))))
                    clock_failures.sort()
                    if len(clock_failures)>=2 and all(v for _,v in clock_failures[-2:]):
                        raise RuntimeError('two consecutive clock-invalid attempts; investigate before further injection')
                for dependency in case.get('depends_on',[]):
                    prior=next((c for c in self.data['cases'] if c['id']==dependency),None)
                    if not prior or prior['status']!='finished' or not prior.get('judgement',{}).get('trial_valid') or not prior['judgement'].get('safety'):
                        raise RuntimeError('case dependency not verified: '+dependency)
                previous = case.get('attempts', [])
                cap = 1 if self.data['stage'] == 'supplemental' else self.profile['max_attempts']
                if len(previous) >= cap:
                    raise ValueError('registered retry cap exhausted')
                attempt = {'id': f'attempt-{len(previous)+1:02}', 'state':'PREPARED',
                           'previous':previous[-1]['id'] if previous else None}
                case.setdefault('attempts', []).append(attempt)
                path = self.directory / 'cases' / case['id'] / attempt['id']
                path.mkdir(parents=True, exist_ok=False)
                attempt['path'] = str(path.relative_to(self.directory))
                case['status'] = 'running'; self.data['status']='running'; self.save()
                ev = Evidence(path)
                self.ledger(case, attempt, 'started')
                atomic_json(path / 'identity.json', dict(campaign_id=self.data['id'],case_id=case['id'],
                            attempt_id=attempt['id'],purpose=case['purpose'],synthetic=self.data['synthetic'],
                            policy_sha256=self.data['policy_sha256']))
                interrupted=None
                try:
                    self.backend.execute(case, self.profile, ev)
                except BaseException as exc:
                    ev.event('execution_error', detail=f'{type(exc).__name__}: {exc}')
                    attempt['error'] = f'{type(exc).__name__}: {exc}'
                    if isinstance(exc,(KeyboardInterrupt,SystemExit)):interrupted=exc
                finally:
                    attempt['state'] = 'CLEANUP'; self.save()
                    ev.state('CLEANUP')
                    try:
                        if self.data['synthetic']:
                            cleanup = self.backend.cleanup(case, self.profile, ev)
                        else:
                            with phase('cleanup',ops['cleanup_seconds'],path/'phases.jsonl',None if time_targets_only(self.profile) else epoch(ops['hard_stop_utc'])-ops['host_shutdown_timeout_seconds']):
                                cleanup = self.backend.cleanup(case, self.profile, ev)
                        save_cleanup(path,cleanup)
                        if not cleanup.get('checks') or not all(v is True for v in cleanup['checks'].values()):
                            raise RuntimeError('cleanup readback failed')
                    except BaseException as exc:
                        atomic_json(path/('cleanup-error-'+uuid.uuid4().hex+'.json'),{'utc':utc(),'error':str(exc)})
                        attempt.update(state='CLEANUP_FAILED',cleanup_error=str(exc))
                        self.ledger(case, attempt, 'cleanup_failed',error=str(exc)); self.save()
                        raise RuntimeError('cleanup failed; next case blocked') from exc
                ev.state('VERIFIED')
                attempt['state'] = 'VERIFIED'
                result = judge(path, case, self.profile)
                atomic_json(path / 'judgement.json', {k:v for k,v in result.items() if k!='metrics'})
                atomic_json(path / 'metrics.json', result['metrics'])
                try:
                    normalized = __import__('fresh_analysis').normalize(path)
                    atomic_json(path / 'normalized-requests.json', normalized)
                except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:
                    # Malformed input is already an invalid independent judgement.
                    # Retain it and close/seal the attempt rather than strand running state.
                    atomic_json(path / 'normalization-error.json', {'error':f'{type(exc).__name__}: {exc}'})
                attempt['evidence_sha256'] = evidence_hashes(path)
                case.update(status='finished',judgement={k:v for k,v in result.items() if k!='metrics'})
                self.ledger(case, attempt, 'finished',trial_valid=result['trial_valid'],recovered=result['recovered'])
                self.save()
                try:check_frozen(self.directory, current=True)
                except BaseException:
                    self.data['status']='source-changed';self.save();raise
                if interrupted is not None:
                    self.data['status']='interrupted';self.save()
                    raise interrupted
                count += 1
                if limit and count >= limit:
                    break
            self.data['status'] = 'measured' if all(c['status']=='finished' for c in self.data['cases']) else 'batch-complete'
            self.save()

    def resume_cleanup(self, case_id):
        # Never repeat an uncertain mutation. Resume is cleanup and closure only; a new attempt is explicit.
        with (self.directory / 'campaign.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.data=check_frozen(self.directory, current=True)
            case = next(c for c in self.data['cases'] if c['id']==case_id)
            attempt = case['attempts'][-1]
            if attempt['state'] == 'VERIFIED':
                raise ValueError('attempt already closed')
            ev = Evidence(self.directory / attempt['path'], 'resume-cleanup')
            ev.event('execution_error',detail='resumed with observation gap; no side effect replay')
            if not any(e.get('phase')=='CLEANUP' for e in rows(ev.directory/'events.jsonl')):ev.state('CLEANUP')
            attempt['state']='CLEANUP';self.save()
            self.ledger(case,attempt,'cleanup_resuming')
            try:
                if self.data['synthetic']:
                    cleanup = self.backend.cleanup(case,self.profile,ev)
                else:
                    ops=self.profile['operations']
                    with phase('cleanup',ops['cleanup_seconds'],ev.directory/'phases.jsonl',None if time_targets_only(self.profile) else epoch(ops['hard_stop_utc'])-ops['host_shutdown_timeout_seconds']):
                        cleanup = self.backend.cleanup(case,self.profile,ev)
                save_cleanup(ev.directory,cleanup)
                if not cleanup.get('checks') or not all(value is True for value in cleanup['checks'].values()):
                    raise RuntimeError('cleanup still incomplete')
            except BaseException as exc:
                attempt.update(state='CLEANUP_FAILED',cleanup_error=str(exc))
                atomic_json(ev.directory/('cleanup-error-'+uuid.uuid4().hex+'.json'),{'utc':utc(),'error':str(exc)})
                self.ledger(case,attempt,'cleanup_failed',error=str(exc));self.save()
                raise
            attempt.update(state='VERIFIED',resumed_with_gap=True,evidence_sha256=evidence_hashes(ev.directory))
            ev.state('VERIFIED')
            judged=judge(ev.directory,case,self.profile)
            atomic_json(ev.directory/'judgement.json',{k:v for k,v in judged.items() if k!='metrics'})
            atomic_json(ev.directory/'metrics.json',judged['metrics'])
            attempt['evidence_sha256']=evidence_hashes(ev.directory)
            case.update(status='finished',judgement={k:v for k,v in judged.items() if k!='metrics'})
            self.data['status']='batch-complete'
            self.ledger(case,attempt,'resumed_cleanup_only');self.save()


def evidence_hashes(path):
    return {str(p.relative_to(path)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(path.rglob('*')) if p.is_file()}


def report(directory, allow_synthetic=False):
    directory = Path(directory)
    data = check_frozen(directory)
    if source_hashes()!=data['source_sha256']:
        raise ValueError('report source changed; use the frozen checkout or register tool changes in a new cohort')
    if data['synthetic'] and not allow_synthetic:
        raise ValueError('synthetic evidence cannot enter primary report; use --synthetic-report')
    results, missing, ledger = [], [], rows(directory / 'attempts.jsonl')
    images={}
    for case in data['cases']:
        if not case.get('attempts'):
            missing.append(case['id']); continue
        for a in case['attempts']:
            path = directory / a['path']
            if not path.resolve().is_relative_to(directory.resolve()):
                raise ValueError('external/historical attempt path')
            identity = read(path / 'identity.json', {})
            if identity != dict(campaign_id=data['id'],case_id=case['id'],attempt_id=a['id'],purpose=case['purpose'],synthetic=data['synthetic'],policy_sha256=data['policy_sha256']):
                raise ValueError('foreign/historical/purpose evidence contamination')
            if a.get('evidence_sha256') is not None and a['evidence_sha256'] != evidence_hashes(path):
                raise ValueError('attempt raw hash mismatch: ' + case['id'])
            raw=read(path/'observations/contract.json',{})
            if raw.get('application_image_ids'):
                images.setdefault(case['scenario'],set()).add(digest(raw['application_image_ids']))
            judged = judge(path,case,data['profile'])
            judged['evidence_sealed']=bool(a.get('evidence_sha256'))
            if not judged['evidence_sealed']:
                judged['trial_valid']=False
                judged['missing'].append('attempt_evidence_unsealed')
            results.append(dict(case_id=case['id'],scenario=case['scenario'],mode=case['mode'],block=case['block'],
                                purpose=case['purpose'],attempt=a['id'],**judged))
    if any(len(values)>1 for values in images.values()):
        raise ValueError('application runtime image digests changed within scenario')
    # First attempts remain primary even when a later retry is usable; all attempts remain visible.
    primary = [r for r in results if r['purpose']=='main' and r['attempt']=='attempt-01']
    contrasts = []
    for scenario, left, right in data['profile']['analysis']['contrasts']:
        if not any(c['scenario']==scenario for c in data['cases']):continue
        for block in ('b01','b02','b03'):
            pair = [next((r for r in primary if (r['scenario'],r['block'],r['mode'])==(scenario,block,m)),None) for m in (left,right)]
            contrasts.append(dict(scenario=scenario,block=block,arms=[left,right],complete=all(pair),
                     trial_valid=all(r and r['trial_valid'] for r in pair),
                     fault_realized=all(r and r['fault_realized'] for r in pair),safety=all(r and r['safety'] for r in pair),
                     failure_rate_difference=(pair[0]['metrics']['failure_rate']-pair[1]['metrics']['failure_rate']) if all(r and r['trial_valid'] and r['fault_realized'] and r['metrics'].get('failure_rate') is not None for r in pair) else None,
                     recovery_seconds_difference=(pair[0]['metrics']['recovery_seconds']-pair[1]['metrics']['recovery_seconds']) if all(r and r['trial_valid'] and r['fault_realized'] and r['safety'] and r['metrics'].get('recovery_seconds') is not None for r in pair) else None))
            contrast=contrasts[-1]
            metric_names=('safe_recovered','service_recovered','intervention_delivered','capacity_recovered',
                          'violation_seconds_lower_bound','unobserved_seconds','failure_rate',
                          'service_slo_violation_fraction','scheduled_latency_p95_ms','recovery_seconds',
                          'upload_goodput_Bps','upload_edge_unobserved_seconds')
            contrast['arm_results']=[dict(mode=mode,observed=r is not None,
                trial_valid=r['trial_valid'] if r else None,recovered=r['recovered'] if r else None,
                safety=r['safety'] if r else None,
                **{name:r['metrics'].get(name) if r else None for name in metric_names}) for mode,r in zip((left,right),pair)]
            for metric in ('violation_seconds_lower_bound','service_slo_violation_fraction','upload_goodput_Bps'):
                contrast[metric+'_difference']=(pair[0]['metrics'][metric]-pair[1]['metrics'][metric]) if all(r and r['trial_valid'] and r['fault_realized'] and r['metrics'].get(metric) is not None for r in pair) else None
            if scenario in ('s1','s2'):
                metric='scheduled_latency_p95_ms'
                contrast[metric+'_difference']=(pair[0]['metrics'][metric]-pair[1]['metrics'][metric]) if all(r and r['trial_valid'] and r['fault_realized'] and r['metrics'].get(metric) is not None for r in pair) else None
                contrast['secondary_latency_interpretation']='conditional on successful, correct, within-deadline requests; alongside failure, SLO violation and missingness; not co-primary'
            contrast['claim_limitations']=[]
            if right=='A' and pair[1] and pair[1]['metrics'].get('intervention_delivered') is not True:
                contrast['claim_limitations'].append('A intervention not delivered: assignment-policy comparison only, not the effect of an actual restart')
            if not contrast['trial_valid'] or not contrast['fault_realized']:
                contrast['claim_limitations'].append('Incomplete primary contrast; retries do not replace first attempts')
    coverage = {s:dict(scheduled=sum(c['scenario']==s and c['purpose']=='main' for c in data['cases']),
                     observed=sum(r['scenario']==s for r in primary),fault_realized=sum(r['scenario']==s and r['fault_realized'] is True for r in primary),valid=sum(r['scenario']==s and r['trial_valid'] for r in primary),
                     recovered=sum(r['scenario']==s and r['recovered'] is True for r in primary),
                     safe_recovered=sum(r['scenario']==s and r['recovered'] is True and r['safety'] for r in primary)) for s in ('s1','s2','s3','s4')}
    output=dict(campaign_id=data['id'],synthetic=data['synthetic'],stage=data['stage'],schedule_counts=data['schedule_counts'],
                run_results=results,attempt_ledger=ledger,paired_contrasts=contrasts,missingness=missing,
                missingness_details=[dict(case_id=r['case_id'],attempt=r['attempt'],missing=r['missing']) for r in results if r['missing']],claim_coverage=coverage,
                claims=data['profile']['analysis']['claims'],primary_sample_count=0 if data['synthetic'] else len(primary))
    prefix='synthetic-' if data['synthetic'] else ''
    atomic_json(directory / ('synthetic-report.json' if data['synthetic'] else 'fresh-report.json'),output)
    for name,key in [('run-results','run_results'),('attempt-ledger','attempt_ledger'),('paired-contrasts','paired_contrasts'),('missingness','missingness'),('claim-coverage','claim_coverage')]:
        atomic_json(directory/(prefix+name+'.json'),output[key])
    lines=['# '+('SYNTHETIC VALIDATION ONLY' if data['synthetic'] else 'Fresh evaluation record'),'',
           'Campaign: '+data['id'], 'Stage: '+data['stage'],
           'Registered full schedule: main 29; preparation 8; development smoke separate.', '',
           '| Case | Purpose | Attempt | Valid | Recovered within H | Cleanup |',
           '|---|---|---|---|---|---|']
    for r in results:
        lines.append('| '+ ' | '.join(str(r[k]) for k in ('case_id','purpose','attempt','trial_valid','recovered','cleanup'))+' |')
    lines+=['','All failed, invalid and unrecovered attempts are retained. Recovery times remain null when unrecovered.',
            'Latency is conditional on successful requests; failure rate uses scheduled arrivals. Missing observations remain unknown.',
            '',*data['profile']['analysis']['claims']]
    (directory/(prefix+'report.md')).write_text('\n'.join(lines)+'\n')
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('schedule','validate','freeze','freeze-transport','run','status','report','resume-cleanup','environment-ensure','environment-down','environment-rotate'))
    parser.add_argument('--profile',type=Path,default=ROOT/'config/graduation-evaluation-fresh.json')
    parser.add_argument('--campaign',type=Path)
    parser.add_argument('--stage',choices=('main','preparation','development','supplemental'),default='preparation')
    parser.add_argument('--scenario',choices=('s1','s2','s3','s4'))
    parser.add_argument('--policy-manifest',type=Path)
    parser.add_argument('--pilot-campaign',type=Path)
    parser.add_argument('--previous-campaign',type=Path)
    parser.add_argument('--transport-authorization',type=Path)
    parser.add_argument('--synthetic',action='store_true',help='offline fake backend; never primary evidence')
    parser.add_argument('--synthetic-report',action='store_true')
    parser.add_argument('--limit',type=int)
    parser.add_argument('--case')
    args=parser.parse_args()
    try:
        if args.action in ('schedule','validate'):
            p=load(args.profile,live=args.action=='validate')
            validate_controller_policy(p,live=args.action=='validate')
            import math
            bins={}
            for name,cfg in [(s,p[s]) for s in ('s1','s2','s3','s4')]+[('v1',{**p['s1'],**p['v1_condition']})]:
                count=cfg['bin_seconds']*cfg['rate'] if cfg.get('bin_seconds') else None
                allowed=math.floor(count*cfg['bin_max_bad_fraction']) if count is not None and cfg.get('bin_max_bad_fraction') is not None else None
                bins[name]=dict(arrivals=count,allowed_bad_count=allowed,zero_bad_allowed=allowed==0 if allowed is not None else None)
            print(json.dumps(dict(counts=validate(p),cases=schedule(p),bin_contracts=bins),indent=2));return
        if not args.campaign:
            parser.error('--campaign required')
        if args.action.startswith('environment-'):
            # Explicit operational work may precede final observed-identity confirmation.
            p=load(args.profile)
            validate_controller_policy(p,live=True)
            from fresh_live import LiveBackend
            args.campaign.mkdir(parents=True,exist_ok=True)
            backend=LiveBackend(args.campaign)
            print(backend.environment_action(p,args.action.split('-')[1]));return
        if args.action=='freeze-transport':
            if not args.transport_authorization or args.synthetic:
                raise ValueError('explicit live transport authorization required')
            from fresh_transport_release import freeze_transport
            print(freeze_transport(args.profile,args.campaign,args.transport_authorization,scenario=args.scenario,stage=args.stage));return
        if args.action=='freeze':
            print(freeze(args.profile,args.campaign,args.stage,args.scenario,args.policy_manifest,args.synthetic,args.pilot_campaign,args.previous_campaign));return
        if args.action=='report':
            result=report(args.campaign,args.synthetic_report)
            print(json.dumps({k:result[k] for k in ('campaign_id','synthetic','schedule_counts','missingness','claim_coverage','primary_sample_count')},indent=2));return
        if args.action=='status':
            print(json.dumps(check_frozen(args.campaign),indent=2));return
        frozen=check_frozen(args.campaign,current=True)
        if frozen['synthetic'] != args.synthetic:
            raise ValueError('backend must match frozen synthetic/live manifest')
        if args.synthetic:
            from fresh_fake import FakeBackend
            backend=FakeBackend()
        else:
            validate(frozen['profile'],live=True)
            validate_controller_policy(frozen['profile'],live=True)
            from fresh_live import LiveBackend
            backend=LiveBackend(args.campaign)
        campaign=FreshCampaign(args.campaign,backend)
        if args.action=='run':campaign.run(args.limit,args.case)
        else:
            if not args.case:parser.error('--case required')
            campaign.resume_cleanup(args.case)
    except (ValueError,RuntimeError,OSError,KeyError) as exc:
        parser.exit(2,str(exc)+'\n')


if __name__=='__main__':
    main()
