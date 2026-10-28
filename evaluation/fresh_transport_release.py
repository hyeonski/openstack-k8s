"""Explicit, hash-bound transport-only continuation; never rewrite a prior freeze.

Existing preparation is reviewed against its own source and raw judgement.
New execution gets a complete new source freeze and only unattempted main IDs.
One separately labelled supplementary case cannot replace a primary first try.
"""
import copy
import ast
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from fresh_contract import digest, load, validate
from fresh_evidence import utc
from fresh_analysis import judge
from lib.state import atomic_json

REVIEWED_FILES = frozenset({
    'evaluation/fresh_transport.py', 'evaluation/fresh_transport_release.py',
    'evaluation/fresh_scenarios.py', 'evaluation/fresh_calibration.py',
    'evaluation/fresh_campaign.py', 'evaluation/fresh_release_driver.py',
    'tests/test_fresh_transport.py', 'tests/test_fresh_transport_release.py',
    'tests/test_fresh_collection.py',
})


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_scenario_transport_diff(previous, current):
    """All scenario/policy AST stays identical after removing the read wrapper."""
    old, new = ast.parse(previous), ast.parse(current)
    changed = next(n for n in new.body if isinstance(n, ast.ClassDef) and n.name == 'FreshS1')
    wrapper = next(n for n in changed.body if isinstance(n, ast.FunctionDef) and n.name == 'finish')
    expected = ast.parse('def finish(self):\n with self.transport_reads():\n  return self.finish_once()').body[0]
    if ast.dump(wrapper) != ast.dump(expected):
        raise ValueError('S1 finish wrapper changes execution semantics')
    changed.body = [n for n in changed.body if not (isinstance(n, ast.FunctionDef) and n.name in ('finish', 'transport_reads'))]
    finish = next(n for n in changed.body if isinstance(n, ast.FunctionDef) and n.name == 'finish_once')
    finish.name = 'finish'
    new.body = [n for n in new.body if not (
        isinstance(n, ast.ImportFrom) and n.module == 'contextlib' or
        isinstance(n, ast.Import) and [a.name for a in n.names] == ['os'])]
    if ast.dump(old) != ast.dump(new):
        raise ValueError('scenario change extends beyond the transport read wrapper')


def historical_campaign(path, expected_manifest):
    from fresh_campaign import check_frozen, evidence_hashes
    path = Path(path)
    if sha(path/'frozen-manifest.json') != expected_manifest:
        raise ValueError('historical freeze does not match authorised transition')
    manifest = check_frozen(path)
    if manifest.get('synthetic'):
        raise ValueError('synthetic preparation cannot authorise a live transition')
    for case in manifest['cases']:
        for attempt in case.get('attempts', []):
            if attempt['state'] != 'VERIFIED' or evidence_hashes(path/attempt['path']) != attempt.get('evidence_sha256'):
                raise ValueError('historical attempt is active, unsealed, or changed')
        if case.get('attempts'):
            latest = path/case['attempts'][-1]['path']/'judgement.json'
            if not latest.is_file() or case.get('judgement') != json.loads(latest.read_text()):
                raise ValueError('historical case judgement differs from sealed evidence')
    return manifest


def audit_transition(profile, authorization, root):
    from fresh_campaign import source_hashes, pilot_contract
    root = Path(root)
    if authorization.get('kind') != 'user-authorized-transport-continuation-v1' or authorization.get('supplemental_limit') != 1:
        raise ValueError('explicit transport continuation and exactly one supplement required')
    if not authorization.get('human_instruction') or not authorization.get('boundary_case'):
        raise ValueError('human instruction and safe boundary required')
    source = source_hashes(root)
    if source != authorization['approved_source_sha256']:
        raise ValueError('current source differs from reviewed transport patch')
    prior = {name: historical_campaign(row['path'], row['frozen_manifest_sha256'])
             for name, row in authorization['prior_campaigns'].items()}
    anchor = prior['s1-main-v1']
    base = anchor['source_sha256']
    changed = {name for name in source.keys() | base.keys() if source.get(name) != base.get(name)}
    if changed != set(authorization['changed_files']) or not changed or not changed.issubset(REVIEWED_FILES):
        raise ValueError('source changes cross reviewed transport transition boundary')
    diffs = {}
    anchor_path = Path(authorization['prior_campaigns']['s1-main-v1']['path'])
    for name in sorted(changed):
        old = anchor_path/'source'/name
        new = root/name
        diffs[name] = ''.join(difflib.unified_diff(
            old.read_text().splitlines(True) if old.exists() else [],
            new.read_text().splitlines(True) if new.exists() else [],
            fromfile='previous/'+name, tofile='current/'+name))
    if digest(diffs) != authorization['reviewed_diff_sha256']:
        raise ValueError('reviewed diff changed')
    validate_scenario_transport_diff((anchor_path/'source/evaluation/fresh_scenarios.py').read_text(),
                                    (root/'evaluation/fresh_scenarios.py').read_text())
    before, after = copy.deepcopy(anchor['profile']), copy.deepcopy(profile)
    before['operations'].pop('artifact_root');after['operations'].pop('artifact_root')
    if before != after:
        raise ValueError('transport continuation cannot alter workload/policy/analysis/budgets/profile')
    if Path(profile['operations']['artifact_root']) == Path(anchor['profile']['operations']['artifact_root']):
        raise ValueError('new source requires a separate cohort root')
    for key in ('tests', 'minimal_readback'):
        artifact = authorization[key]
        evidence = json.loads(Path(artifact['path']).read_text())
        if sha(artifact['path']) != artifact['sha256'] or not evidence.get('passed') or evidence.get('source_sha256') != source:
            raise ValueError(key+' evidence missing, changed, or failed')
    impact = authorization['impact_analysis']
    if any(impact.get(key) is not False for key in ('policy_changed', 'judgement_semantics_changed', 'workload_changed')):
        raise ValueError('transport reuse requires unchanged scientific semantics')
    required = {case['id'] for case in profile['cases'] if case['purpose'] != 'main'}
    reusable = set()
    for name, manifest in prior.items():
        if manifest['stage'] != 'preparation': continue
        directory = Path(authorization['prior_campaigns'][name]['path'])
        if manifest['source_sha256'] != base:
            raise ValueError('preparation source was not the reviewed predecessor')
        for case in manifest['cases']:
            if pilot_contract(profile, case['scenario']) != pilot_contract(manifest['profile'], case['scenario']):
                raise ValueError('validated preparation contract changed')
            for attempt in case.get('attempts', []):
                path = directory/attempt['path']
                saved = json.loads((path/'judgement.json').read_text())
                recomputed = {k: v for k, v in judge(path, case, manifest['profile']).items() if k != 'metrics'}
                if saved != recomputed:
                    raise ValueError('historical judgement changed during reuse review')
                if (saved['trial_valid'] and saved['safety'] is True and saved['cleanup'] is True
                    and saved['fault_realized'] is True
                    and (case['mode'] not in ('P', 'P3600', 'on') or saved['recovered'] is True)
                    and (case['mode'] != 'V1' or saved['v1_outcome'] == 'held')):
                    reusable.add(case['id'])
    if reusable != required:
        raise ValueError('complete registered preparation evidence required')
    observed = {case['id'] for manifest in prior.values() if manifest['stage'] == 'main'
                for case in manifest['cases'] if case.get('attempts')}
    remaining = [case['id'] for case in profile['cases'] if case['purpose'] == 'main' and case['id'] not in observed]
    if remaining != authorization['remaining_main_ids']:
        raise ValueError('remaining original main order differs; cannot copy completed work')
    boundary = next(case for case in anchor['cases'] if case['id'] == authorization['boundary_case'])
    if boundary['status'] != 'finished' or len(boundary.get('attempts', [])) != 1:
        raise ValueError('active case has not naturally closed and sealed')
    origin = next(case for case in anchor['cases'] if case['id'] == authorization['supplemental_origin'])
    if len(origin.get('attempts', [])) != 1 or origin['judgement']['trial_valid'] is not False or origin['judgement']['cleanup'] is not True:
        raise ValueError('supplement origin must remain one cleanly closed invalid first try')
    return dict(authorization=authorization, source_transition=sorted(changed),
                reviewed_diff=diffs, preparation_reused=sorted(reusable),
                predecessor_observed_main=sorted(observed), no_primary_replacement=True)


def select_cases(profile, authorization, scenario, stage):
    if stage == 'main':
        return [dict(case, status='pending', negative=False) for case in profile['cases']
                if case['id'] in authorization['remaining_main_ids'] and case['scenario'] == scenario]
    if stage == 'supplemental' and scenario == 's1':
        original = next(case for case in profile['cases'] if case['id'] == authorization['supplemental_origin'])
        return [dict(original, id=original['id']+'-supplement01', purpose='supplemental',
            block='supplement-b02-a', order=38, status='pending', negative=False, depends_on=[])]
    raise ValueError('unsupported transport continuation stage')


def freeze_transport(profile_path, destination, authorization_path, *, scenario, stage='main', root=None):
    from fresh_campaign import ROOT, source_hashes, policy_manifest
    root = Path(root or ROOT).resolve()
    profile_path = Path(profile_path).resolve();destination = Path(destination).resolve()
    profile = load(profile_path, live=True)
    from fresh_identity import validate_controller_policy
    from fresh_operations import case_time_gate
    validate_controller_policy(profile, live=True)
    case_time_gate(profile)
    authorization = json.loads(Path(authorization_path).read_text())
    audit = audit_transition(profile, authorization, root)
    ops = profile['operations']
    if Path(ops['execution_checkout']).resolve() != root:
        raise ValueError('execution checkout mismatch')
    if not destination.is_relative_to(Path(ops['artifact_root']).resolve()) or destination.exists():
        raise ValueError('new dedicated campaign inside registered cohort root required')
    override = Path(os.environ.get('ENV_OVERRIDE_FILE', '')).resolve()
    if override != Path(ops['environment_override']).resolve() or not override.is_file():
        raise ValueError('explicit environment override mismatch')
    for key, field in [('ENVIRONMENT_NAME', 'environment'), ('GCP_PROJECT_ID', 'project'), ('GCP_ZONE', 'zone')]:
        if os.environ.get(key) != profile[field]: raise ValueError('explicit environment identity mismatch')
    selected = select_cases(profile, authorization, scenario, stage)
    if stage == 'supplemental':
        # Admission is after all original main IDs have one sealed first attempt.
        actual = set(audit['predecessor_observed_main'])
        for saved in Path(ops['artifact_root']).glob('*/campaign.json'):
            manifest = json.loads(saved.read_text())
            for case in manifest['cases']:
                if case['purpose'] == 'supplemental' and case.get('attempts'):
                    raise ValueError('one supplementary measurement already attempted')
                if case['purpose'] == 'main' and case.get('attempts'):
                    if case['attempts'][0]['state'] != 'VERIFIED': raise ValueError('main still active')
                    actual.add(case['id'])
        if actual != {case['id'] for case in profile['cases'] if case['purpose'] == 'main'}:
            raise ValueError('original main29 must finish before supplement')
    if not selected: raise ValueError('empty continuation selection')
    for saved in Path(ops['artifact_root']).glob('*/campaign.json'):
        existing = json.loads(saved.read_text())
        if any(case.get('status') == 'running' for case in existing['cases']):
            raise ValueError('active continuation case blocks another freeze')
        if {case['id'] for case in selected} & {case['id'] for case in existing['cases']}:
            raise ValueError('continuation case already registered')
    source = source_hashes(root);policy = policy_manifest(source)
    destination.mkdir(parents=True)
    for name in source:
        target = destination/'source'/name;target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root/name, target)
    documents = {}
    for name in ops['preregistered_documents']:
        target = destination/'preregistered-documents'/name;target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root/name, target);documents[name] = sha(target)
    (destination/'selected-profile.json').write_bytes(profile_path.read_bytes())
    atomic_json(destination/'policy-manifest.json', policy)
    atomic_json(destination/'transport-transition.json', audit)
    manifest = dict(git_head=subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD']).decode().strip(),
        schema_version=3, id='fresh-'+uuid.uuid4().hex, created=utc(), synthetic=False,
        stage=stage, scope=profile['scope'], profile=profile, profile_path=str(profile_path),
        profile_sha256=sha(profile_path), analysis_sha256=digest(profile['analysis']),
        policy_sha256=digest(policy), source_sha256=source,
        preregistered_documents_sha256=documents, cases=selected, status='frozen',
        schedule_counts=validate(profile), historical_results='excluded',
        override_path=str(override), override_sha256=sha(override),
        transport_transition_sha256=digest(audit),
        supplemental_origin=authorization['supplemental_origin'] if stage == 'supplemental' else None,
        primary_rule='original main29 first attempts only; supplement excluded')
    if source_hashes(root) != source: raise ValueError('source changed during continuation freeze')
    atomic_json(destination/'campaign.json', manifest)
    atomic_json(destination/'frozen-manifest.json', manifest)
    (destination/'manifest.sha256').write_text(digest(manifest)+'\n')
    return destination
