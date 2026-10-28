"""Explicit stability continuation gate; preserves every historical first attempt."""
import ast
import copy
import difflib
import hashlib
import json
from pathlib import Path

KIND='user-authorized-stability-continuation-v4'
MAIN=['s4-b02-off','s4-b03-off','s4-b03-on']
SUPPLEMENTS=['s1-b02-a','s2-b03-p','s3-b02-m3600','s3-b03-m3600']
# Scientific methods outside this reviewed operational envelope must be byte/AST identical.
SCIENTIFIC_METHODS={
 'evaluation/fresh_analysis.py':{'_judge','scenario_checks'},
 'evaluation/fresh_baseline.py':{'baseline_gate'},
 'evaluation/fresh_scenarios.py':{'FreshOwnedLab.create_owned','FreshS2.finish','FreshS3.finish','main','run_s4'},
 'experiments/graduation_recovery.py':{'RecoveryLab.operational_remote'},
 'experiments/graduation_s1.py':{'S1.cpu_stat'},
 'experiments/graduation_s1_contention.py':{'S1Contention.run_locked'},
 'experiments/graduation_s2.py':{'S2.set_rate'},
 'experiments/graduation_s3.py':{'S3.cleanup','S3.clear_fault','S3.controller_policy','S3.fence','S3.mark_out_of_service','S3.read_guest','S3.read_sql','S3.run'},
}
STABILITY_FILES={
 'evaluation/fresh_analysis.py','evaluation/fresh_baseline.py','evaluation/fresh_calibration.py','evaluation/fresh_clock_guard.py',
 'evaluation/fresh_credit.py','evaluation/fresh_evidence.py','evaluation/fresh_mutation.py',
 'evaluation/fresh_operations.py','evaluation/fresh_qualification.py','evaluation/fresh_read_budget.py',
 'evaluation/fresh_read_registry.py','evaluation/fresh_seal.py','evaluation/fresh_stability_release.py',
 'experiments/graduation_recovery.py','experiments/graduation_s1.py',
 'experiments/graduation_s1_contention.py','experiments/graduation_s2.py','experiments/graduation_s3.py',
 'scripts/lib/runtime.py','scripts/lib/fresh_reads.py','scripts/workload_state.py',
 'scripts/install-fresh-clock-guard.sh','config/fresh-read-registry.json',
 'tests/test_fresh_execution.py','tests/test_fresh_identity.py','tests/test_fresh_clock_guard.py','tests/test_fresh_stability.py',
 'tests/test_fresh_stability_release.py','tests/test_fresh_credit.py',
}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def artifact(reference):
    path=Path(reference['path'])
    if sha(path)!=reference['sha256']:raise ValueError('stability proof changed: '+str(path))
    return json.loads(path.read_text())


def protected_ast(text,allowed):
    tree=ast.parse(text)
    class Strip(ast.NodeTransformer):
        def __init__(self):self.scope=[]
        def visit_Import(self,node):return None
        def visit_ImportFrom(self,node):return None
        def visit_ClassDef(self,node):
            self.scope.append(node.name);node=self.generic_visit(node);self.scope.pop();return node
        def visit_FunctionDef(self,node):
            name='.'.join(self.scope+[node.name])
            if name in allowed:return None
            self.scope.append(node.name);node=self.generic_visit(node);self.scope.pop();return node
        def visit_Assign(self,node):
            if self.scope==['FreshS1'] and any(isinstance(n,ast.Name) and n.id=='defer_owned_cleanup' for n in node.targets):
                if not isinstance(node.value,ast.Constant) or node.value.value is not True:raise ValueError('owned cleanup defer differs')
                return None
            return node
    return ast.dump(Strip().visit(tree),include_attributes=False)


def validate_scientific_boundary(predecessor,root):
    for name,allowed in SCIENTIFIC_METHODS.items():
        if protected_ast((Path(predecessor)/'source'/name).read_text(),allowed)!=protected_ast((Path(root)/name).read_text(),allowed):
            raise ValueError('scientific function/constants changed outside reviewed operational envelope: '+name)


CALIBRATION_GATE_OLD="""        if sha(ROOT/name) != frozen['source_sha256'][name]:
            raise ValueError('validated measurement source changed: '+name)
"""
CALIBRATION_GATE_NEW="""        if sha(ROOT/name) != frozen['source_sha256'][name]:
            if profile['operations'].get('stability'):
                from fresh_stability_release import validate_calibration_source
                validate_calibration_source(name,ROOT,frozen['source_sha256'][name])
            else:raise ValueError('validated measurement source changed: '+name)
"""


def validate_calibration_source(name,root,expected):
    text=(Path(root)/name).read_text()
    if name=='evaluation/fresh_baseline.py':
        text=text.replace('        from fresh_read_budget import phase_deadline\n        with phase_deadline(deadline):\n            requests = collect()', '        requests = collect()')
    elif name=='evaluation/fresh_calibration.py':
        text=text.replace(CALIBRATION_GATE_NEW,CALIBRATION_GATE_OLD)
    elif name=='evaluation/fresh_analysis.py':
        text=text.replace('def scenario_checks(case, raw, events, *, include_cleanup=True):','def scenario_checks(case, raw, events):')
        text=text.replace('def _judge(directory, case, profile, *, include_cleanup=True):','def _judge(directory, case, profile):')
        text=text.replace('    start = end = None\n','',1)
        text=text.replace('scenario_checks(case, raw, events, include_cleanup=include_cleanup)','scenario_checks(case, raw, events)')
        text=text.replace("if case['scenario']=='s2' and start is not None and end is not None:","if case['scenario']=='s2' and injected:")
        text=text.replace("if case['scenario']=='s4' and start is not None and end is not None and raw.get('capacity_snapshot'):","if case['scenario']=='s4' and raw.get('capacity_snapshot'):")
        text=text.replace("""        before, during = raw['mhc_before'], raw['mhc_during']
        if include_cleanup:
            restored = raw['mhc_restored']
            checks['mhc_restored'] = before['spec'] == restored['spec'] and before['metadata']['uid'] == restored['metadata']['uid'] and before['metadata'].get('annotations',{}) == restored['metadata'].get('annotations',{})
""", """        before, during, restored = raw['mhc_before'], raw['mhc_during'], raw['mhc_restored']
        checks['mhc_restored'] = before['spec'] == restored['spec'] and before['metadata']['uid'] == restored['metadata']['uid'] and before['metadata'].get('annotations',{}) == restored['metadata'].get('annotations',{})
""")
    else:raise ValueError('unreviewed calibrated source change: '+name)
    if hashlib.sha256(text.encode()).hexdigest()!=expected:raise ValueError('calibrated semantics changed outside exact stability patch: '+name)
    return True


def qualification_source_match(root,qualification,reference=None):
    root=Path(root)
    changed={n for n,v in qualification['source_sha256'].items() if sha(root/n)!=v}
    if not changed:return True
    allowed={'evaluation/fresh_read_budget.py','evaluation/fresh_evidence.py','evaluation/fresh_calibration.py'}
    if changed!=allowed or reference is None:raise ValueError('qualified runtime source changed')
    proof=artifact(reference)
    if proof.get('kind')!='exact-horizon-and-calibration-operational-compatibility' or not proof.get('offline_passed'):
        raise ValueError('H boundary compatibility proof missing')
    # The qualification never establishes a scientific H. The exact added H-only
    # branch is covered by final-source offline tests; its active path is not
    # misrepresented as having been exercised by the live clock qualification.
    if 'operational_horizon_seconds' in (root/'evaluation/fresh_qualification.py').read_text():
        raise ValueError('qualification began exercising H; compatibility no longer applies')
    for name in sorted(changed):
        old=Path(proof['before_root'])/name
        if sha(old)!=qualification['source_sha256'][name] or proof['after_sha256'][name]!=sha(root/name):
            raise ValueError('H boundary before/after source proof differs')
        new=(root/name).read_text()
        if name.endswith('fresh_calibration.py'):
            restored=new.replace(CALIBRATION_GATE_NEW,CALIBRATION_GATE_OLD)
        elif name.endswith('fresh_evidence.py'):
            restored=new.replace('set_horizon_deadline','set_phase_deadline')
        else:
            restored=new.replace('_PHASE_END = None\n_HORIZON_END = None','_PHASE_END = None',1)
            restored=restored.replace('def set_horizon_deadline(end):\n    global _HORIZON_END\n    _HORIZON_END=end\n\n','',1)
            addition="""                # Keep the original successful read contract. A read already in
                # progress may finish after H as before; a retry must fit in H.
                # Baseline's hard phase deadline still applies to every attempt.
                if _HORIZON_END is not None:
                    end=min(end,_HORIZON_END)
                    remaining()
"""
            if addition not in restored:raise ValueError('unexpected H budget implementation')
            restored=restored.replace(addition,'',1)
        if restored!=old.read_text():raise ValueError('qualification path changed outside exact inactive H branch')
    return True


def audit_stability_transition(profile,a,root):
    from fresh_campaign import source_hashes,pilot_contract
    from fresh_contract import digest
    from fresh_analysis import judge
    from fresh_transport_release import historical_campaign,REVIEWED_FILES
    from fresh_read_registry import audit
    root=Path(root)
    if a.get('kind')!=KIND or a.get('supplemental_limit')!=4 or a.get('supplemental_origins')!=SUPPLEMENTS or a.get('remaining_main_ids')!=MAIN:
        raise ValueError('exact authorised remaining scope required')
    if not a.get('human_instruction') or a.get('boundary_case')!='s4-b02-on':raise ValueError('actual reboot boundary required')
    source=source_hashes(root)
    if source!=a['approved_source_sha256']:raise ValueError('current source differs from reviewed stability release')
    prior={name:historical_campaign(row['path'],row['frozen_manifest_sha256']) for name,row in a['prior_campaigns'].items()}
    predecessor=Path(a['stability_predecessor']['path'])
    old=historical_campaign(predecessor,a['stability_predecessor']['frozen_manifest_sha256'])
    if old['git_head']!='7b72f6780df391a662c5f39233c17506ae252f77' or len(old['source_sha256'])!=234:
        raise ValueError('stability must review the actual source234 predecessor')
    base=old['source_sha256'];changed={n for n in source.keys()|base.keys() if source.get(n)!=base.get(n)}
    if changed!=set(a['changed_files']) or not changed.issubset(REVIEWED_FILES|STABILITY_FILES):raise ValueError('unreviewed stability source changes')
    diffs={}
    for name in sorted(changed):
        before=predecessor/'source'/name;after=root/name
        diffs[name]=''.join(difflib.unified_diff(before.read_text().splitlines(True) if before.exists() else [],
            after.read_text().splitlines(True) if after.exists() else [],fromfile='previous/'+name,tofile='current/'+name))
    if digest(diffs)!=a['reviewed_diff_sha256']:raise ValueError('stability diff changed')
    validate_scientific_boundary(predecessor,root)
    before,after=copy.deepcopy(old['profile']),copy.deepcopy(profile)
    before['operations'].pop('artifact_root');after['operations'].pop('artifact_root')
    policy=after['operations'].pop('stability',None)
    if before!=after or not policy:raise ValueError('scientific/profile budgets changed beyond registered stability operations')
    if Path(profile['operations']['artifact_root'])==Path(old['profile']['operations']['artifact_root']):raise ValueError('separate cohort required')
    if any(a['impact_analysis'].get(k) is not False for k in ('policy_changed','judgement_semantics_changed','workload_changed')):
        raise ValueError('scientific semantics cannot change')
    audit(root)
    for key in ('tests','minimal_readback'):
        proof=artifact(a[key])
        if not proof.get('passed') or proof.get('source_sha256')!=source:raise ValueError(key+' not bound to current source')
    qualification=artifact(a['qualification'])
    if not qualification.get('passed') or not qualification.get('cleanup_verified') or not qualification.get('source_unchanged'):
        raise ValueError('qualification failed/incomplete')
    if not 1800<=qualification['protected_observation_seconds']<=2700 or qualification['elapsed_seconds']>2700:
        raise ValueError('qualification duration differs')
    if not qualification.get('no_experiment_attempt') or not qualification.get('no_service_or_vm_fault'):
        raise ValueError('qualification crossed experiment boundary')
    outage=qualification['read_outage']
    if outage['simulated_seconds']!=20 or outage['recovered_seconds']>90 or len(outage['attempt_seconds'])>3 or outage['observations_filled']:
        raise ValueError('qualification read budget differs')
    qualification_source_match(root,qualification,a.get('qualification_horizon_compatibility'))
    clock=artifact(a['clock_restore'])
    if not clock.get('passed') or clock.get('service_sha256')!=source['evaluation/fresh_clock_guard.py']:
        raise ValueError('installed clock service proof differs')
    if set(clock.get('verified',[]))!={'normal_release','owner_exit','lease_expired','service_restart','reboot_cycle'}:
        raise ValueError('all real restore paths, including reboot, required')
    if clock.get('boot_before')==clock.get('boot_after') or clock.get('restored_network_time')!=clock.get('original_network_time'):
        raise ValueError('real reboot restoration not proven')
    comparisons=artifact(a['sidecar_comparison'])
    valid=[r for r in comparisons if r['original_valid']]
    if len(comparisons)!=26 or len(valid)!=19 or any(not r['new_valid'] or r['changed_keys'] or not r['metrics_equal'] for r in valid):
        raise ValueError('valid19 strict verdict/metrics changed')
    if any(r['new_valid'] for r in comparisons if not r['original_valid']):raise ValueError('original invalid was resurrected')
    if any(r['case']!='s2-b03-p' and (r['changed_keys'] or not r['metrics_equal']) for r in comparisons):
        raise ValueError('sidecar changed outside the disclosed missing-H bug')
    preserved=artifact(a['original_preservation'])
    if not preserved.get('passed') or preserved.get('changed') or preserved.get('files')!=10234:raise ValueError('original sealed bytes changed')
    required={c['id'] for c in profile['cases'] if c['purpose']!='main'};reusable=set();observed=[];all_cases=[]
    for name,manifest in prior.items():
        directory=Path(a['prior_campaigns'][name]['path'])
        for case in manifest['cases']:
            if not case.get('attempts'):continue
            all_cases.append(case)
            if manifest['stage']=='main':observed.append(case['id']);continue
            if manifest['stage']!='preparation':raise ValueError('unexpected historical stage')
            if pilot_contract(profile,case['scenario'])!=pilot_contract(manifest['profile'],case['scenario']):raise ValueError('preparation contract changed')
            for attempt in case['attempts']:
                path=directory/attempt['path'];saved=json.loads((path/'judgement.json').read_text())
                if saved!={k:v for k,v in judge(path,case,manifest['profile']).items() if k!='metrics'}:raise ValueError('preparation strict judgement changed')
                if (saved['trial_valid'] and saved['safety'] is True and saved['cleanup'] is True and saved['fault_realized'] is True
                    and (case['mode'] not in ('P','P3600','on') or saved['recovered'] is True)
                    and (case['mode']!='V1' or saved['v1_outcome']=='held')):reusable.add(case['id'])
    if reusable!=required or len(observed)!=26 or len(set(observed))!=26:raise ValueError('preparation/main history incomplete or duplicated')
    if [c['id'] for c in profile['cases'] if c['purpose']=='main' and c['id'] not in observed]!=MAIN:raise ValueError('remaining main order changed')
    if sum(c['judgement']['trial_valid'] is True for c in all_cases if c['id'] in observed)!=19:raise ValueError('primary historical valid count changed')
    for ident in ['s4-b02-on',*SUPPLEMENTS]:
        matches=[c for c in all_cases if c['id']==ident]
        if len(matches)!=1 or matches[0]['status']!='finished' or len(matches[0]['attempts'])!=1 or matches[0]['judgement']['trial_valid'] is not False or matches[0]['judgement']['cleanup'] is not True:
            raise ValueError('boundary/supplement origin not cleanly closed invalid first attempt: '+ident)
    from fresh_credit import forward_credit
    if forward_credit(profile)['margin_krw']<=0:raise ValueError('latest credit reserve unavailable')
    return dict(authorization=a,source_transition=sorted(changed),reviewed_diff=diffs,
        preparation_reused=sorted(reusable),predecessor_observed_main=sorted(observed),no_primary_replacement=True,
        stability_qualified=True,old_invalid_preserved=7,old_valid_unchanged=19)
