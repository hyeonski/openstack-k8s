"""Reviewed continuation for CRI JSON polluted by successful iptables checks."""
import ast,copy,difflib,json
from pathlib import Path
from fresh_stability_release import artifact,sha

KIND='user-authorized-s3-capture-continuation-v7'
ORIGINS=['s3-b03-m3600','s3-b03-p3600','s4-b01-off','s4-b02-on','s4-b02-off','s1-b02-a','s3-b02-m3600']
PLAN=[dict(origin=x,id=x+('-supplement02' if x in ('s1-b02-a','s3-b02-m3600') else '-supplement01'),order=41+i) for i,x in enumerate(ORIGINS)]
FILES={'evaluation/fresh_s3_capture.py','evaluation/fresh_scenarios.py','evaluation/fresh_s3_capture_release.py',
       'evaluation/fresh_read_registry.py','evaluation/fresh_transport_release.py','evaluation/fresh_release_driver.py',
       'config/fresh-read-registry.json','tests/test_fresh_s3_capture.py','tests/test_fresh_s3_capture_release.py'}

def validate_scope(a):
    if (a.get('kind')!=KIND or a.get('remaining_main_ids')!=[] or a.get('supplemental_origins')!=ORIGINS or
        a.get('supplemental_plan')!=PLAN or a.get('supplemental_limit')!=7 or
        a.get('boundary_case')!='s3-b02-m3600-supplement01' or not a.get('human_instruction')):
        raise ValueError('six pending supplements then separate S3 supplement02 required')

def validate_delta(base,source,declared):
    changed={n for n in base.keys()|source.keys() if base.get(n)!=source.get(n)}
    if changed!=set(declared) or not changed.issubset(FILES):raise ValueError('outside S3 capture operational envelope')
    return changed

def validate_scenario_change(before,after):
    old=ast.parse(before);new=ast.parse(after)
    imported=ast.parse('from fresh_s3_capture import read_s3_capture').body[0]
    selected=[n for n in new.body if ast.dump(n)==ast.dump(imported)]
    if len(selected)!=1:raise ValueError('exact S3 capture import required')
    new.body.remove(selected[0])
    call=ast.parse('running = read_s3_capture(self,source)').body[0]
    original=ast.parse('''process = self.read_guest(source,'test "$(cat /run/osk8s-s3-owner)" = '+shlex.quote(self.record['run_id'])+' && iptables -C OUTPUT -j OSK8S_S3_OUT && iptables -C FORWARD -j OSK8S_S3_DB && cat '+shlex.quote('/run/osk8s-s3-capture-'+self.record['run_id']+'.json'))
running = json.loads(process)''').body
    class Restore(ast.NodeTransformer):
        count=0
        def visit_Assign(self,node):
            if ast.dump(node)==ast.dump(call):self.count+=1;return original
            return self.generic_visit(node)
    restore=Restore();new=restore.visit(new)
    if restore.count!=1 or ast.dump(old)!=ast.dump(new):raise ValueError('S3 policy, fault, observation or judgement changed')

def audit_s3_capture_transition(profile,a,root):
    from fresh_campaign import source_hashes,pilot_contract
    from fresh_contract import digest
    from fresh_transport_release import historical_campaign
    from fresh_analysis import judge
    from fresh_read_registry import audit
    from fresh_credit import forward_credit
    root=Path(root);validate_scope(a);source=source_hashes(root)
    if source!=a['approved_source_sha256']:raise ValueError('source differs from S3 review')
    previous=artifact(a['previous_authorization']);go=artifact(a['previous_go_review'])
    if previous['kind']!='user-authorized-s1-read-continuation-v6' or not go['passed'] or go['authorization']!=a['previous_authorization']:
        raise ValueError('verified S1-read-v9 predecessor required')
    added=a['closed_v9_campaigns']
    if set(added)!={'bed-s1-read-v9--s2-supplement-transport-v2','bed-s1-read-v9--s3-b02-m3600-supplement-transport-v2'}:
        raise ValueError('exact two closed v9 campaigns required')
    expected={**previous['prior_campaigns'],**added}
    if a['prior_campaigns']!=expected:raise ValueError('historical cohort set changed')
    prior={k:historical_campaign(v['path'],v['frozen_manifest_sha256']) for k,v in expected.items()}
    key='bed-s1-read-v9--s3-b02-m3600-supplement-transport-v2';old=prior[key];oldroot=Path(added[key]['path'])/'source'
    for k in added:
        if prior[k]['git_head']!='ccd8cb85a65e0c7d32ffc6407ac83094f3870744' or prior[k]['source_sha256']!=previous['approved_source_sha256']:
            raise ValueError('actual source255 v9 predecessor required')
    changed=validate_delta(old['source_sha256'],source,a['changed_files'])
    validate_scenario_change((oldroot/'evaluation/fresh_scenarios.py').read_text(),(root/'evaluation/fresh_scenarios.py').read_text())
    before_registry=(oldroot/'evaluation/fresh_read_registry.py').read_text()
    after_registry=(root/'evaluation/fresh_read_registry.py').read_text().replace(" 'evaluation/fresh_s3_capture.py',\n",'')
    if ast.dump(ast.parse(before_registry))!=ast.dump(ast.parse(after_registry)):raise ValueError('registry policy changed beyond added helper inventory')
    diffs={}
    for n in sorted(changed):
        p=oldroot/n;q=root/n
        diffs[n]=''.join(difflib.unified_diff(p.read_text().splitlines(True) if p.exists() else [],q.read_text().splitlines(True) if q.exists() else [],fromfile='previous/'+n,tofile='current/'+n))
    if digest(diffs)!=a['reviewed_diff_sha256']:raise ValueError('S3 reviewed diff changed')
    before,after=copy.deepcopy(old['profile']),copy.deepcopy(profile)
    if before['operations'].pop('artifact_root')==after['operations'].pop('artifact_root'):raise ValueError('new artifact cohort required')
    old_stability=before['operations']['stability'];new_stability=after['operations']['stability']
    old_stability.pop('credit_reference');new_credit=new_stability.pop('credit_reference')
    old_run=old_stability['read_identity'].pop('environment_run_id');new_run=new_stability['read_identity'].pop('environment_run_id')
    if old_run==new_run or before!=after:raise ValueError('only refreshed credit/environment run and artifact cohort permitted')
    if new_credit!=a['credit_reference']:raise ValueError('credit reference differs')
    credit=artifact(new_credit)
    if credit['latest_credit']['displayed_remaining_krw']!=120972 or credit['latest_credit']['used_krw']!=314551 or credit['latest_credit']['total_krw']!=435523:
        raise ValueError('latest human balance arithmetic changed')
    for k in ('tests','qualification'):
        if not artifact(previous[k])['passed']:raise ValueError('prior verification failed')
    for k in ('tests','qualification'):
        proof=artifact(a[k])
        if not proof.get('passed') or proof.get('source_sha256')!=source:raise ValueError('current-source '+k+' missing')
    proof=artifact(a['qualification'])
    for k in ('no_experiment_attempt','no_traffic_drop','real_rule_stdout_reproduced','fixed_read_json_valid','same_container_and_pod_uid','owned_cleanup_verified','identity_verified','source_unchanged'):
        if proof.get(k) is not True:raise ValueError('actual S3 capture path not verified: '+k)
    if proof['environment_run_id']!=new_run or sha(a['qualification_runner']['path'])!=a['qualification_runner']['sha256'] or proof['runner_sha256']!=a['qualification_runner']['sha256']:
        raise ValueError('qualification environment/runner changed')
    stopped=artifact(a['shutdown'])
    if not stopped['passed'] or not stopped['all_ledger_sessions_closed'] or not stopped['source_unchanged'] or not stopped['closed_invalid_attempt_unchanged']:
        raise ValueError('invalid preservation and safe stop not proven')
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
    expected_supp={'s1-b02-a-supplement01':False,'s2-b03-p-supplement01':True,'s3-b02-m3600-supplement01':False}
    if len(supp)!=3 or {c['id']:c['judgement']['trial_valid'] for c in supp}!=expected_supp or any(c['judgement']['cleanup'] is not True for c in supp):raise ValueError('prior supplemental outcomes changed')
    invalid={c['id'] for c in main if c['judgement']['trial_valid'] is False}
    if invalid!=set(ORIGINS)|{'s2-b03-p'}:raise ValueError('pending supplement origins differ')
    if reusable!={c['id'] for c in profile['cases'] if c['purpose']!='main'}:raise ValueError('eight preparations must remain reusable')
    audit(root);budget=artifact(a['remaining_budget']);estimates=budget['case_seconds']
    if budget['remaining_case_ids']!=[p['id'] for p in PLAN] or set(estimates)!={p['id'] for p in PLAN} or any(estimates[p['id']]<{'s1':44,'s2':37,'s3':32,'s4':37}[p['origin'][:2]]*72 for p in PLAN) or budget['future_seconds']!=sum(estimates.values())+1500:
        raise ValueError('all seven pending cases and cleanup must be reserved')
    completed=set()
    for path in Path(profile['operations']['artifact_root']).glob('*/campaign.json'):
        saved=json.loads(path.read_text())
        if any(c.get('status')=='finished' for c in saved['cases']):
            checked=historical_campaign(path.parent,sha(path.parent/'frozen-manifest.json'))
            if checked['source_sha256']!=source:raise ValueError('current cohort source differs')
            completed.update(c['id'] for c in checked['cases'] if c.get('status')=='finished')
    if forward_credit(profile,sum(v for k,v in estimates.items() if k not in completed)+1500)['margin_krw']<=0:raise ValueError('insufficient forward credit')
    return dict(authorization=a,source_transition=sorted(changed),reviewed_diff=diffs,preparation_reused=sorted(reusable),predecessor_observed_main=sorted(required),no_primary_replacement=True,stability_qualified=True,old_valid_unchanged=21,old_invalid_preserved=8,valid_supplement_preserved=1,invalid_supplements_preserved=2)
