"""One reviewed continuation after S1 supplemental operational failure.

Every original main result and the closed invalid supplement remain immutable.
The final S1 supplement02 is a separate observation, never a replacement.
"""
import ast
import copy
import difflib
import json
from pathlib import Path

from fresh_stability_release import artifact,sha

KIND='user-authorized-s1-read-continuation-v6'
ORIGINS=['s2-b03-p','s3-b02-m3600','s3-b03-m3600','s3-b03-p3600','s4-b01-off','s4-b02-on','s4-b02-off','s1-b02-a']
PLAN=[dict(origin=x,id=x+('-supplement02' if x=='s1-b02-a' else '-supplement01'),order=39+i) for i,x in enumerate(ORIGINS)]
FILES={'evaluation/fresh_read_budget.py','evaluation/fresh_collection.py','evaluation/fresh_live.py',
       'evaluation/fresh_s1_read_release.py','evaluation/fresh_transport_release.py','evaluation/fresh_release_driver.py',
       'config/fresh-read-registry.json','tests/test_fresh_stability.py','tests/test_fresh_collection.py',
       'tests/test_fresh_s1_read_release.py'}
PREFLIGHT="""        if profile['operations'].get('stability'):
            # Restore a missing local tunnel before the first cleanup command;
            # the background watcher alone may react after that command fails.
            h.call([Path(__file__).resolve().parents[1]/'scripts/gcp-workload-api-tunnel.sh','ensure'],
                   'cleanup-transport-preflight.log',timeout=60)
"""


def validate_scope(a):
    if (a.get('kind')!=KIND or a.get('remaining_main_ids')!=[] or
        a.get('supplemental_origins')!=ORIGINS or a.get('supplemental_plan')!=PLAN or
        a.get('supplemental_limit')!=8 or a.get('boundary_case')!='s1-b02-a-supplement01' or not a.get('human_instruction')):
        raise ValueError('seven pending supplements then separate S1 supplement02 required')


def validate_delta(base,source,declared):
    changed={n for n in base.keys()|source.keys() if base.get(n)!=source.get(n)}
    if changed!=set(declared) or not changed.issubset(FILES):
        raise ValueError('change outside reviewed S1 operational continuation')
    return changed


def validate_operational_changes(oldroot,newroot):
    """Reject policy/metric changes even inside mixed operational modules."""
    for name in ('evaluation/fresh_collection.py','evaluation/fresh_live.py','evaluation/fresh_read_budget.py'):
        before=(Path(oldroot)/name).read_text();after=(Path(newroot)/name).read_text()
        if name.endswith('fresh_collection.py'):
            after=after.replace("source='/dev/shm/fresh-cpu-'","source='/tmp/fresh-cpu-'")
        elif name.endswith('fresh_live.py'):
            if after.count(PREFLIGHT)!=1:raise ValueError('exact cleanup transport preflight required')
            after=after.replace(PREFLIGHT,'')
        else:
            after=after.replace('import re\n','').replace(
                "    return (bool(re.search(r'the connection to the server [^\\n]+ was refused', text)) or\n        isinstance(error, (subprocess.TimeoutExpired, ConnectionError))) or any(",
                '    return isinstance(error, (subprocess.TimeoutExpired, ConnectionError)) or any(')
        if ast.dump(ast.parse(before))!=ast.dump(ast.parse(after)):
            raise ValueError('unreviewed operational or scientific change: '+name)


def audit_s1_read_transition(profile,a,root):
    from fresh_campaign import source_hashes,pilot_contract
    from fresh_contract import digest
    from fresh_transport_release import historical_campaign
    from fresh_analysis import judge
    from fresh_read_registry import audit
    from fresh_credit import forward_credit
    root=Path(root);validate_scope(a);source=source_hashes(root)
    if source!=a['approved_source_sha256']:raise ValueError('source differs from S1 review')
    previous=artifact(a['previous_authorization']);go=artifact(a['previous_go_review'])
    if previous['kind']!='user-authorized-inventory-continuation-v5' or not go['passed'] or go['authorization']!=a['previous_authorization']:
        raise ValueError('verified inventory-v8 authorization required')
    added=a['closed_v8_campaigns']
    if set(added)!={'bed-inventory-v8--s4-main-transport-v2','bed-inventory-v8--s1-supplement-transport-v2'}:
        raise ValueError('exact two closed inventory-v8 campaigns required')
    expected={**previous['prior_campaigns'],**added}
    if a['prior_campaigns']!=expected:raise ValueError('historical campaign set changed')
    prior={k:historical_campaign(v['path'],v['frozen_manifest_sha256']) for k,v in expected.items()}
    old=prior['bed-inventory-v8--s1-supplement-transport-v2'];oldroot=Path(added['bed-inventory-v8--s1-supplement-transport-v2']['path'])/'source'
    for key in added:
        if prior[key]['git_head']!='b46b0f802c97da2135da485587407be831bab247' or prior[key]['source_sha256']!=previous['approved_source_sha256']:
            raise ValueError('actual source253 inventory-v8 predecessor required')
    base=old['source_sha256'];changed=validate_delta(base,source,a['changed_files'])
    validate_operational_changes(oldroot,root)
    diffs={}
    for n in sorted(changed):
        p=oldroot/n;q=root/n
        diffs[n]=''.join(difflib.unified_diff(p.read_text().splitlines(True) if p.exists() else [],q.read_text().splitlines(True) if q.exists() else [],fromfile='previous/'+n,tofile='current/'+n))
    if digest(diffs)!=a['reviewed_diff_sha256']:raise ValueError('reviewed S1 diff changed')
    before,after=copy.deepcopy(old['profile']),copy.deepcopy(profile)
    if before['operations'].pop('artifact_root')==after['operations'].pop('artifact_root') or before!=after:
        raise ValueError('only a new artifact cohort is permitted')
    for key in ('tests','readiness','original_preservation'):
        if not artifact(previous[key])['passed']:raise ValueError('inventory-v8 proof failed')
    for key in ('tests','qualification'):
        proof=artifact(a[key])
        if not proof.get('passed') or proof.get('source_sha256')!=source:raise ValueError('current-source '+key+' proof missing')
    proof=artifact(a['qualification'])
    for key in ('no_experiment_attempt','no_fault_injection','cpu_readonly_root_verified','cpu_capture_once',
                'reconnect_identity_same','fixture_cleanup_verified','cleanup_preflight_recovered','identity_verified','source_unchanged'):
        if proof.get(key) is not True:raise ValueError('actual failure path not verified: '+key)
    if proof['reconnect_elapsed_seconds']>60 or sha(a['qualification_runner']['path'])!=a['qualification_runner']['sha256'] or proof['runner_sha256']!=a['qualification_runner']['sha256']:
        raise ValueError('qualification runner/deadline changed')
    closure=artifact(a['closure'])
    if (not closure['cleanup_verified'] or not closure['source_unchanged'] or closure['strict_trial_valid'] is not False or
        closure['original_files_unchanged']!=10234 or closure['prior_invalid_files_unchanged']!=21 or not closure['main_two_unchanged']):
        raise ValueError('original or failed supplement preservation missing')
    main=[];supp=[];reusable=set()
    for key,manifest in prior.items():
        for case in manifest['cases']:
            if not case.get('attempts'):continue
            for attempt in case['attempts']:
                path=Path(expected[key]['path'])/attempt['path'];saved=json.loads((path/'judgement.json').read_text())
                current={k:v for k,v in judge(path,case,manifest['profile']).items() if k!='metrics'}
                # An older invalid S2 row has additional strict missingness in
                # the already-reviewed v4 analysis. Retain its original row;
                # it must remain invalid. Valid and preparation rows match exactly.
                if saved!=current and (saved['trial_valid'] is True or current['trial_valid'] is True or manifest['stage']!='main'):
                    raise ValueError('historical strict judgement changed')
            if manifest['stage']=='main':main.append(case)
            elif manifest['stage']=='supplemental':supp.append(case)
            elif manifest['stage']=='preparation':
                if pilot_contract(profile,case['scenario'])!=pilot_contract(manifest['profile'],case['scenario']):raise ValueError('preparation contract changed')
                if (saved['trial_valid'] and saved['cleanup'] is True and saved['safety'] is True and saved['fault_realized'] is True
                    and (case['mode'] not in ('P','P3600','on') or saved['recovered'] is True)
                    and (case['mode']!='V1' or saved['v1_outcome']=='held')):reusable.add(case['id'])
    required={c['id'] for c in profile['cases'] if c['purpose']=='main'}
    if len(main)!=29 or {c['id'] for c in main}!=required or sum(c['judgement']['trial_valid'] is True for c in main)!=21:
        raise ValueError('original main29 valid21/invalid8 changed')
    if {c['id'] for c in main if c['judgement']['trial_valid'] is False}!=set(ORIGINS):raise ValueError('supplement origins must remain invalid')
    if len(supp)!=1 or supp[0]['id']!='s1-b02-a-supplement01' or supp[0]['judgement']['trial_valid'] is not False or supp[0]['judgement']['cleanup'] is not True:
        raise ValueError('closed invalid first S1 supplement required')
    if reusable!={c['id'] for c in profile['cases'] if c['purpose']!='main'}:raise ValueError('eight preparations must remain reusable')
    audit(root)
    budget=artifact(a['remaining_budget'])
    estimates=budget['case_seconds']
    if (budget['remaining_case_ids']!=[p['id'] for p in PLAN] or set(estimates)!={p['id'] for p in PLAN} or
        any(estimates[p['id']]<{'s1':44,'s2':37,'s3':32,'s4':37}[p['origin'][:2]]*72 for p in PLAN) or
        budget['future_seconds']!=sum(estimates.values())+1500):
        raise ValueError('remaining work was omitted from credit planning')
    completed=set()
    for path in Path(profile['operations']['artifact_root']).glob('*/campaign.json'):
        saved=json.loads(path.read_text())
        if any(c.get('status')=='finished' for c in saved['cases']):
            checked=historical_campaign(path.parent,sha(path.parent/'frozen-manifest.json'))
            if checked['source_sha256']!=source:raise ValueError('current cohort source changed')
            completed.update(c['id'] for c in checked['cases'] if c.get('status')=='finished')
    remaining=sum(v for k,v in estimates.items() if k not in completed)+1500
    if forward_credit(profile,remaining)['margin_krw']<=0:raise ValueError('credit reserve unavailable for all remaining work')
    return dict(authorization=a,source_transition=sorted(changed),reviewed_diff=diffs,preparation_reused=sorted(reusable),
                predecessor_observed_main=sorted(required),no_primary_replacement=True,stability_qualified=True,
                old_valid_unchanged=21,old_invalid_preserved=8,invalid_supplement_preserved=1)
