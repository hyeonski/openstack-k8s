"""Reviewed final supplement after Neutron remote-SG cache reconciliation."""
import copy,difflib,json
from pathlib import Path
from fresh_stability_release import artifact,sha

KIND='user-authorized-dns-readiness-continuation-v8'
ORIGINS=['s3-b02-m3600']
PLAN=[dict(origin=ORIGINS[0],id=ORIGINS[0]+'-supplement03',order=48)]
FILES={'evaluation/fresh_dns_release.py','evaluation/fresh_transport_release.py','evaluation/fresh_release_driver.py','tests/test_fresh_dns_release.py'}

def validate_scope(a):
    if (a.get('kind')!=KIND or a.get('remaining_main_ids')!=[] or a.get('supplemental_origins')!=ORIGINS or
        a.get('supplemental_plan')!=PLAN or a.get('supplemental_limit')!=1 or
        a.get('boundary_case')!='s3-b02-m3600-supplement02' or not a.get('human_instruction')):
        raise ValueError('only separate final S3 supplement03 permitted')

def validate_delta(base,source,declared):
    changed={n for n in base.keys()|source.keys() if base.get(n)!=source.get(n)}
    if changed!=set(declared) or not changed.issubset(FILES):raise ValueError('outside DNS continuation gate envelope')
    return changed

def audit_dns_transition(profile,a,root):
    from fresh_campaign import source_hashes,pilot_contract
    from fresh_contract import digest
    from fresh_transport_release import historical_campaign
    from fresh_analysis import judge
    from fresh_read_registry import audit
    from fresh_credit import forward_credit
    root=Path(root);validate_scope(a);source=source_hashes(root)
    if source!=a['approved_source_sha256']:raise ValueError('source differs from DNS review')
    previous=artifact(a['previous_authorization']);go=artifact(a['previous_go_review'])
    if previous['kind']!='user-authorized-s3-capture-continuation-v7' or not go['passed'] or go['authorization']!=a['previous_authorization']:
        raise ValueError('verified S3-capture-v10 predecessor required')
    added=a['closed_v10_campaigns']
    expected_names={'s3-b03-m3600-supplement-transport-v2','s3-b03-p3600-supplement-transport-v2','s4-b01-off-supplement-transport-v2','s4-b02-on-supplement-transport-v2','s4-b02-off-supplement-transport-v2','s1-supplement-transport-v2','s3-b02-m3600-supplement-transport-v2'}
    if set(added)!={'bed-s3-capture-v10--'+n for n in expected_names}:raise ValueError('all seven closed v10 campaigns required')
    expected={**previous['prior_campaigns'],**added}
    if a['prior_campaigns']!=expected:raise ValueError('historical cohort set changed')
    prior={k:historical_campaign(v['path'],v['frozen_manifest_sha256']) for k,v in expected.items()}
    key='bed-s3-capture-v10--s3-b02-m3600-supplement-transport-v2';old=prior[key];oldroot=Path(added[key]['path'])/'source'
    for k in added:
        if prior[k]['git_head']!='db82c5ba04a300ce177a09cd8869c13a7d34a589' or prior[k]['source_sha256']!=previous['approved_source_sha256']:
            raise ValueError('actual source259 v10 predecessor required')
    changed=validate_delta(old['source_sha256'],source,a['changed_files'])
    diffs={}
    for n in sorted(changed):
        p=oldroot/n;q=root/n
        diffs[n]=''.join(difflib.unified_diff(p.read_text().splitlines(True) if p.exists() else [],q.read_text().splitlines(True) if q.exists() else [],fromfile='previous/'+n,tofile='current/'+n))
    if digest(diffs)!=a['reviewed_diff_sha256']:raise ValueError('DNS reviewed diff changed')
    before,after=copy.deepcopy(old['profile']),copy.deepcopy(profile)
    if before['operations'].pop('artifact_root')==after['operations'].pop('artifact_root'):raise ValueError('new artifact cohort required')
    if before!=after:raise ValueError('only new artifact cohort permitted; scientific profile and infrastructure identity unchanged')
    if profile['operations']['stability']['credit_reference']!=a['credit_reference']:raise ValueError('latest credit reference changed')
    for k in ('tests','qualification'):
        if not artifact(previous[k])['passed']:raise ValueError('prior verification failed')
    for k in ('tests','qualification'):
        proof=artifact(a[k])
        if not proof.get('passed') or proof.get('source_sha256')!=source:raise ValueError('current-source '+k+' missing')
    proof=artifact(a['qualification'])
    for k in ('no_experiment_attempt','one_two_one_original_probe_passed','same_security_policy','owned_cleanup_verified','identity_verified','source_unchanged','members_match_authority_both_hosts'):
        if proof.get(k) is not True:raise ValueError('actual DNS readiness path not verified: '+k)
    if proof['environment_run_id']!=profile['operations']['stability']['read_identity']['environment_run_id'] or sha(a['qualification_runner']['path'])!=a['qualification_runner']['sha256'] or proof['runner_sha256']!=a['qualification_runner']['sha256']:
        raise ValueError('qualification environment/runner changed')
    repair=artifact(a['network_repair'])
    if not repair['passed'] or repair['source_sha256']!=previous['approved_source_sha256'] or not all(repair[k] for k in ('same_container_id','source_unchanged','security_policy_unchanged','exact_original_readiness_probe_passed','probe_owned_cleanup_passed','no_experiment_fault')):
        raise ValueError('same-policy Neutron reconciliation and actual failed readiness path not proven')
    closure=artifact(a['closure'])
    if not closure['passed'] or not closure['original_snapshot_unchanged'] or not closure['cleanup_verified'] or closure['trial_valid'] is not False or not closure['no_fault_injected']:
        raise ValueError('failed pre-injection attempt must remain invalid and fully cleaned')
    main=[];supp=[];reusable=set()
    for key,manifest in prior.items():
        for case in manifest['cases']:
            if not case.get('attempts'):continue
            for attempt in case['attempts']:
                path=Path(expected[key]['path'])/attempt['path'];saved=json.loads((path/'judgement.json').read_text())
                current={k:v for k,v in judge(path,case,manifest['profile']).items() if k!='metrics'}
                if saved!=current and (saved['trial_valid'] is True or current['trial_valid'] is True or manifest['stage']!='main'):
                    raise ValueError('historical strict judgement changed')
                if manifest['stage']=='preparation':
                    if pilot_contract(profile,case['scenario'])!=pilot_contract(manifest['profile'],case['scenario']):raise ValueError('preparation contract changed')
                    if (saved['trial_valid'] and saved['cleanup'] is True and saved['safety'] is True and saved['fault_realized'] is True and
                        (case['mode'] not in ('P','P3600','on') or saved['recovered'] is True) and (case['mode']!='V1' or saved['v1_outcome']=='held')):reusable.add(case['id'])
            if manifest['stage']=='main':main.append(case)
            if manifest['stage']=='supplemental':supp.append(case)
    required={c['id'] for c in profile['cases'] if c['purpose']=='main'}
    if len(main)!=29 or {c['id'] for c in main}!=required or sum(c['judgement']['trial_valid'] is True for c in main)!=21:raise ValueError('original main29 valid21 invalid8 changed')
    expected_supp={'s1-b02-a-supplement01':False,'s2-b03-p-supplement01':True,'s3-b02-m3600-supplement01':False,
                   's3-b03-m3600-supplement01':True,'s3-b03-p3600-supplement01':True,'s4-b01-off-supplement01':True,
                   's4-b02-on-supplement01':True,'s4-b02-off-supplement01':True,'s1-b02-a-supplement02':True,'s3-b02-m3600-supplement02':False}
    if len(supp)!=10 or {c['id']:c['judgement']['trial_valid'] for c in supp}!=expected_supp or any(c['judgement']['cleanup'] is not True for c in supp):raise ValueError('seven valid/three invalid supplemental outcomes must be preserved')
    if next(c for c in main if c['id']==ORIGINS[0])['judgement']['trial_valid'] is not False:raise ValueError('only original invalid origin can be supplemented')
    if reusable!={c['id'] for c in profile['cases'] if c['purpose']!='main'}:raise ValueError('eight preparations must remain reusable')
    audit(root);budget=artifact(a['remaining_budget']);estimates=budget['case_seconds']
    if budget['remaining_case_ids']!=[p['id'] for p in PLAN] or set(estimates)!={p['id'] for p in PLAN} or any(estimates[p['id']]<{'s1':44,'s2':37,'s3':32,'s4':37}[p['origin'][:2]]*72 for p in PLAN) or budget['future_seconds']!=sum(estimates.values())+1500:
        raise ValueError('final pending case and cleanup must be reserved')
    completed=set()
    for path in Path(profile['operations']['artifact_root']).glob('*/campaign.json'):
        saved=json.loads(path.read_text())
        if any(c.get('status')=='finished' for c in saved['cases']):
            checked=historical_campaign(path.parent,sha(path.parent/'frozen-manifest.json'))
            if checked['source_sha256']!=source:raise ValueError('current cohort source differs')
            completed.update(c['id'] for c in checked['cases'] if c.get('status')=='finished')
    if forward_credit(profile,sum(v for k,v in estimates.items() if k not in completed)+1500)['margin_krw']<=0:raise ValueError('insufficient forward credit')
    return dict(authorization=a,source_transition=sorted(changed),reviewed_diff=diffs,preparation_reused=sorted(reusable),predecessor_observed_main=sorted(required),no_primary_replacement=True,stability_qualified=True,old_valid_unchanged=21,old_invalid_preserved=8,valid_supplement_preserved=7,invalid_supplements_preserved=3)
