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
    'evaluation/fresh_scenarios.py', 'evaluation/fresh_live.py',
    'evaluation/fresh_campaign.py', 'evaluation/fresh_release_driver.py',
    'tests/test_fresh_transport.py', 'tests/test_fresh_transport_release.py',
    'tests/test_fresh_collection.py', 'evaluation/fresh_collection.py', 'tests/test_fresh_evaluation_review.py',
})


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalize_ssh_read_boundaries(tree):
    """Erase only the reviewed explicit read adapters for an AST comparison."""
    expected_helpers = ast.parse("""class FreshOwnedLab:
 def stop_probe(self, stop_path):
  from fresh_transport import stop_probe_once
  return stop_probe_once(self, stop_path)
 def read_remote(self, script, *, timeout=120, host=None):
  from fresh_transport import SSHReadBoundary
  return SSHReadBoundary(self).remote(script, timeout=timeout, host=host)
 def read_admin_json(self, *args, timeout=60):
  from fresh_transport import SSHReadBoundary
  return SSHReadBoundary(self).admin_json(args, timeout=timeout)
 def read_host_stat(self, host):
  from fresh_transport import SSHReadBoundary
  return SSHReadBoundary(self).host_stat(host)
""").body[0].body
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == 'FreshOwnedLab':
            for expected in expected_helpers:
                found = next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name==expected.name), None)
                if found is not None:
                    if ast.dump(found)!=ast.dump(expected):raise ValueError('SSH helper changes more than explicit reads')
                    cls.body.remove(found)
    expressions = ["'curl -fsS http://198.18.0.2:8090/progress'",
                   "'sudo tc -s -j qdisc show dev s2-egress'",
                   repr("python3 -c 'import time; print(time.time())'"),
                   "'sudo cat '+shlex.quote(raw_path)",
                   "'sudo docker exec nova_libvirt virsh domstate '+shlex.quote(source['instance_name'])",
                   "'if sudo test -s '+shlex.quote(self.raw_path)+'; then echo ready; fi'"]
    allowed = {ast.dump(ast.parse(x,mode='eval').body) for x in expressions}
    ready_assignment=ast.parse('ready_deadline=time.monotonic()+60').body[0]
    timeout_expression=ast.parse('max(.001,ready_deadline-time.monotonic())',mode='eval').body
    class Reads(ast.NodeTransformer):
        def visit_FunctionDef(self,node):
            if node.name=='__enter__':
                node.body=[n for n in node.body if ast.dump(n)!=ast.dump(ready_assignment)]
            return self.generic_visit(node)
        def visit_Call(self,node):
            if isinstance(node.func,ast.Attribute) and node.func.attr=='stop_probe':
                if ast.dump(node)!=ast.dump(ast.parse('self.runner.stop_probe(self.stop_path)',mode='eval').body):raise ValueError('probe stop boundary changed')
                return ast.parse("self.runner.remote('sudo touch '+shlex.quote(self.stop_path))",mode='eval').body
            if isinstance(node.func,ast.Attribute) and node.func.attr=='read_remote':
                if len(node.args)!=1 or ast.dump(node.args[0]) not in allowed:
                    raise ValueError('SSH retry crossed an explicit read boundary')
                if node.keywords:
                    if len(node.keywords)==1 and node.keywords[0].arg=='host' and ast.dump(node.keywords[0].value)==ast.dump(ast.parse("source['host']",mode='eval').body):pass
                    elif len(node.keywords)==1 and node.keywords[0].arg=='timeout' and ast.dump(node.keywords[0].value)==ast.dump(timeout_expression):node.keywords=[]
                    else:raise ValueError('SSH readiness deadline/target changed')
                node.func.attr='remote'
            if isinstance(node.func,ast.Attribute) and node.func.attr=='read_admin_json':
                node.func.attr='admin_json'
            if isinstance(node.func,ast.Attribute) and node.func.attr=='read_host_stat':
                node.func=ast.parse('self.runtime.host_stat',mode='eval').body
            if isinstance(node.func,ast.Name) and node.func.id=='remote_file' and len(node.args)>1:
                fn=node.args[1]
                if isinstance(fn,ast.Attribute) and fn.attr=='read_remote':
                    if len(node.keywords)!=1 or node.keywords[0].arg!='bounded' or not isinstance(node.keywords[0].value,ast.Constant) or node.keywords[0].value.value is not True:
                        raise ValueError('remote evidence must have one shared bounded budget')
                    fn.attr='remote';node.keywords=[]
            return self.generic_visit(node)
    return Reads().visit(tree)


def validate_collection_read_diff(previous,current):
    old,new=ast.parse(previous),ast.parse(current)
    method=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name=='remote_file')
    if method.args.kwonlyargs[-1].arg!='bounded' or ast.dump(method.args.kw_defaults[-1])!=ast.dump(ast.Constant(False)):
        raise ValueError('bounded file collection must remain opt-in')
    method.args.kwonlyargs.pop();method.args.kw_defaults.pop()
    call=next(n.value for n in method.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='result' for t in n.targets))
    expected=ast.parse("read_evidence(ev,source,lambda timeout:remote('sudo cat '+shlex.quote(source),timeout=timeout),attempts=1 if bounded else 3,per_attempt=90 if bounded else 30)",mode='eval').body
    if ast.dump(call)!=ast.dump(expected):raise ValueError('collection retry budget changed')
    call.keywords=[]
    if ast.dump(old)!=ast.dump(new):raise ValueError('collection change exceeds bounded read adapter')


def validate_scenario_transport_diff(previous, current):
    """All scenario/policy AST stays identical after removing the read wrapper."""
    old, new = ast.parse(previous), normalize_ssh_read_boundaries(ast.parse(current))
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


def validate_live_transport_diff(previous,current):
    old,new=ast.parse(previous),ast.parse(current)
    cls=next(n for n in new.body if isinstance(n,ast.ClassDef) and n.name=='LiveBackend')
    helper=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='helper')
    expected=ast.parse('from fresh_transport import coordinate_reconnect\nh.call=coordinate_reconnect(h.call,h.state,Path(__file__).resolve().parents[1])').body
    if [ast.dump(n) for n in helper.body[-3:-1]] != [ast.dump(n) for n in expected]:
        raise ValueError('live helper must only coordinate exact reconnect calls')
    del helper.body[-3:-1]
    if ast.dump(old)!=ast.dump(new):raise ValueError('live scenario or mutation semantics changed')


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
    if not (authorization.get('kind') == 'user-authorized-transport-continuation-v1' and authorization.get('supplemental_limit') == 1 or authorization.get('kind') == 'user-authorized-ssh-read-two-supplement-continuation-v2' and authorization.get('supplemental_limit') == 2 and authorization.get('supplemental_origins') == ['s1-b02-a','s2-b03-p']):
        raise ValueError('explicit transport continuation and exactly one supplement required')
    if authorization.get('kind')=='user-authorized-transport-continuation-v1' and authorization.get('supplemental_origins', [authorization.get('supplemental_origin')]) != [authorization.get('supplemental_origin')]:
        raise ValueError('one-supplement authorisation cannot add another origin')
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
    if authorization.get('kind') == 'user-authorized-ssh-read-two-supplement-continuation-v2':
        validate_collection_read_diff((anchor_path/'source/evaluation/fresh_collection.py').read_text(),
                                      (root/'evaluation/fresh_collection.py').read_text())
    validate_live_transport_diff((anchor_path/'source/evaluation/fresh_live.py').read_text(),
                                (root/'evaluation/fresh_live.py').read_text())
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
    boundaries=[case for manifest in prior.values() for case in manifest['cases'] if case['id']==authorization['boundary_case'] and case.get('attempts')]
    if len(boundaries)!=1:raise ValueError('one actual sealed boundary case required')
    boundary=boundaries[0]
    if boundary['status'] != 'finished' or len(boundary.get('attempts', [])) != 1:
        raise ValueError('active case has not naturally closed and sealed')
    for origin_id in supplemental_origins(authorization):
        origins=[case for manifest in prior.values() for case in manifest['cases'] if case['id']==origin_id and case.get('attempts')]
        if len(origins)!=1 or len(origins[0]['attempts'])!=1 or origins[0]['judgement']['trial_valid'] is not False or origins[0]['judgement']['cleanup'] is not True:
            raise ValueError('supplement origin must remain one cleanly closed invalid first try')
    return dict(authorization=authorization, source_transition=sorted(changed),
                reviewed_diff=diffs, preparation_reused=sorted(reusable),
                predecessor_observed_main=sorted(observed), no_primary_replacement=True)


def supplemental_origins(authorization):
    if 'supplemental_origins' in authorization:return authorization['supplemental_origins']
    return [authorization['supplemental_origin']]


def select_cases(profile, authorization, scenario, stage):
    if stage == 'main':
        return [dict(case, status='pending', negative=False) for case in profile['cases']
                if case['id'] in authorization['remaining_main_ids'] and case['scenario'] == scenario]
    if stage == 'supplemental':
        origins=supplemental_origins(authorization)
        for index,origin in enumerate(origins):
            original=next(case for case in profile['cases'] if case['id']==origin)
            if original['scenario']==scenario:
                return [dict(original,id=origin+'-supplement01',purpose='supplemental',
                    block='supplement-'+original['block']+'-'+original['mode'].lower(),
                    order=38+index,status='pending',negative=False,depends_on=[])]
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
                if case['purpose'] == 'supplemental' and case.get('attempts') and case['id'] in {c['id'] for c in selected}:
                    raise ValueError('one supplementary measurement already attempted')
                if case['purpose'] == 'main' and case.get('attempts'):
                    if case['attempts'][0]['state'] != 'VERIFIED': raise ValueError('main still active')
                    actual.add(case['id'])
        if actual != {case['id'] for case in profile['cases'] if case['purpose'] == 'main'}:
            raise ValueError('original main29 must finish before supplement')
        origins=supplemental_origins(authorization)
        origin=selected[0]['id'].removesuffix('-supplement01')
        required={value+'-supplement01' for value in origins[:origins.index(origin)]}
        completed=set()
        for saved in Path(ops['artifact_root']).glob('*/campaign.json'):
            for case in json.loads(saved.read_text())['cases']:
                if case['purpose']=='supplemental' and len(case.get('attempts',[]))==1 and case['attempts'][0]['state']=='VERIFIED' and case.get('status')=='finished':completed.add(case['id'])
        if not required.issubset(completed):raise ValueError('earlier supplementary measurement must be sealed first')
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
        supplemental_origin=selected[0]['id'].removesuffix('-supplement01') if stage == 'supplemental' else None,
        primary_rule='original main29 first attempts only; supplement excluded')
    if source_hashes(root) != source: raise ValueError('source changed during continuation freeze')
    atomic_json(destination/'campaign.json', manifest)
    atomic_json(destination/'frozen-manifest.json', manifest)
    (destination/'manifest.sha256').write_text(digest(manifest)+'\n')
    return destination
