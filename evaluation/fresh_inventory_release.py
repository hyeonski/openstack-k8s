"""Narrow continuation after the closed, pre-injection inventory failure.

The prior clock qualification remains evidence about its recorded source.
Current-source preparation/cleanup and regression proofs are required separately.
"""
import copy
import difflib
from pathlib import Path

from fresh_stability_release import artifact,sha,qualification_source_match

KIND='user-authorized-inventory-continuation-v5'
MAIN=['s4-b03-off','s4-b03-on']
SUPPLEMENTS=['s1-b02-a','s2-b03-p','s3-b02-m3600','s3-b03-m3600','s3-b03-p3600','s4-b01-off','s4-b02-on','s4-b02-off']
FILES={
    'evaluation/fresh_read_budget.py','scripts/lib/fresh_reads.py',
    'scripts/workload-inventory.sh','evaluation/fresh_worker_quiescence.py',
    'evaluation/fresh_live.py','evaluation/fresh_inventory_release.py',
    'evaluation/fresh_transport_release.py','evaluation/fresh_release_driver.py',
    'config/fresh-read-registry.json','tests/test_fresh_inventory.py',
    'tests/test_fresh_inventory_release.py',
}


def validate_scope(a):
    if (a.get('kind')!=KIND or a.get('remaining_main_ids')!=MAIN or
        a.get('supplemental_origins')!=SUPPLEMENTS or a.get('supplemental_limit')!=8 or
        a.get('boundary_case')!='s4-b02-off' or not a.get('human_instruction')):
        raise ValueError('exact remaining two main/eight separate supplements required; no primary replay')


def validate_delta(base,source,declared):
    changed={n for n in source.keys()|base.keys() if source.get(n)!=base.get(n)}
    if changed!=set(declared) or not changed.issubset(FILES):
        raise ValueError('change outside inventory/cleanup continuation envelope')
    return changed


def audit_inventory_transition(profile,a,root):
    from fresh_campaign import source_hashes,pilot_contract
    from fresh_contract import digest
    from fresh_transport_release import historical_campaign
    from fresh_analysis import judge
    from fresh_read_registry import audit
    from fresh_credit import forward_credit
    import json
    root=Path(root);validate_scope(a)
    source=source_hashes(root)
    if source!=a['approved_source_sha256']:raise ValueError('current source differs from inventory review')
    previous=artifact(a['previous_authorization'])
    predecessor=a['inventory_predecessor'];directory=Path(predecessor['path'])
    old=historical_campaign(directory,predecessor['frozen_manifest_sha256'])
    if (old['git_head']!='3375f9069022055ceca3b09e789729704be956ec' or len(old['source_sha256'])!=249
        or previous['kind']!='user-authorized-stability-continuation-v4'
        or previous['approved_source_sha256']!=old['source_sha256']):
        raise ValueError('actual stability-v7 predecessor required')
    base=old['source_sha256'];changed=validate_delta(base,source,a['changed_files'])
    diffs={}
    for name in sorted(changed):
        before=directory/'source'/name;after=root/name
        diffs[name]=''.join(difflib.unified_diff(before.read_text().splitlines(True) if before.exists() else [],
            after.read_text().splitlines(True) if after.exists() else [],fromfile='previous/'+name,tofile='current/'+name))
    if digest(diffs)!=a['reviewed_diff_sha256']:raise ValueError('inventory diff changed')
    before,after=copy.deepcopy(old['profile']),copy.deepcopy(profile)
    if before['operations'].pop('artifact_root')==after['operations'].pop('artifact_root') or before!=after:
        raise ValueError('only a new artifact cohort is permitted; all scientific/budget settings stay fixed')
    # Verify the historical qualification on its frozen source, not on today's
    # runtime. Its clock module is required to be byte-identical today.
    for key in ('tests','minimal_readback','clock_restore','original_preservation'):
        if not artifact(previous[key]).get('passed'):raise ValueError('prior proof failed: '+key)
    qualification=artifact(previous['qualification'])
    if not qualification['passed'] or not qualification['cleanup_verified'] or not qualification['source_unchanged']:
        raise ValueError('prior qualification failed')
    if not 1800<=qualification['protected_observation_seconds']<=2700:
        raise ValueError('prior clock observation duration differs')
    qualification_source_match(directory/'source',qualification,previous.get('qualification_horizon_compatibility'))
    clock=artifact(previous['clock_restore'])
    if clock['service_sha256']!=source['evaluation/fresh_clock_guard.py'] or set(clock['verified'])!={'normal_release','owner_exit','lease_expired','service_restart','reboot_cycle'}:
        raise ValueError('clock source/real restore coverage changed')
    comparisons=artifact(previous['sidecar_comparison'])
    valid=[r for r in comparisons if r['original_valid']]
    if len(comparisons)!=26 or len(valid)!=19 or any(not r['new_valid'] or r['changed_keys'] or not r['metrics_equal'] for r in valid):
        raise ValueError('historical valid19 equivalence lost')
    if any(r['new_valid'] for r in comparisons if not r['original_valid']):raise ValueError('invalid resurrected')
    audit(root)
    for key in ('tests','readiness'):
        proof=artifact(a[key])
        if not proof.get('passed') or proof.get('source_sha256')!=source:raise ValueError('current-source '+key+' proof missing')
    ready=artifact(a['readiness'])
    if (not ready.get('no_experiment_attempt') or not ready.get('no_fault_injection') or
        ready.get('preparation_api')!='Campaign.verify_ready_environment + Campaign.prepare_workers' or
        ready.get('prepared_workers')!=2 or ready.get('restored_workers')!=1 or ready.get('restored_mode')!='auto' or
        not ready.get('cleanup_verified') or not ready.get('identity_verified') or
        not ready.get('clock_arm_restore_verified') or ready.get('inventory_successes',0)<2):
        raise ValueError('actual worker preparation/cleanup/clock path not proven')
    preserved=artifact(a['original_preservation'])
    if not preserved.get('passed') or preserved.get('changed') or preserved.get('files')!=10234 or not preserved.get('new_invalid_preserved'):
        raise ValueError('original/new invalid evidence changed')
    expected={**previous['prior_campaigns'],a['inventory_predecessor_key']:predecessor}
    if a['prior_campaigns']!=expected:raise ValueError('prior campaign set changed')
    prior={name:historical_campaign(row['path'],row['frozen_manifest_sha256']) for name,row in expected.items()}
    observed=[];all_cases=[];reusable=set()
    required={c['id'] for c in profile['cases'] if c['purpose']!='main'}
    for name,manifest in prior.items():
        directory=Path(expected[name]['path'])
        for case in manifest['cases']:
            if not case.get('attempts'):continue
            all_cases.append(case)
            if manifest['stage']=='main':observed.append(case['id']);continue
            if manifest['stage']!='preparation' or pilot_contract(profile,case['scenario'])!=pilot_contract(manifest['profile'],case['scenario']):
                raise ValueError('preparation contract changed')
            for attempt in case['attempts']:
                path=directory/attempt['path'];saved=json.loads((path/'judgement.json').read_text())
                if saved!={k:v for k,v in judge(path,case,manifest['profile']).items() if k!='metrics'}:raise ValueError('preparation strict judgement changed')
                if (saved['trial_valid'] and saved['safety'] is True and saved['cleanup'] is True and saved['fault_realized'] is True
                    and (case['mode'] not in ('P','P3600','on') or saved['recovered'] is True)
                    and (case['mode']!='V1' or saved['v1_outcome']=='held')):reusable.add(case['id'])
    if reusable!=required or len(observed)!=27 or len(set(observed))!=27:raise ValueError('exact 27 original attempts/8 reusable preparations required')
    if [c['id'] for c in profile['cases'] if c['purpose']=='main' and c['id'] not in observed]!=MAIN:raise ValueError('remaining main order changed')
    if sum(c['judgement']['trial_valid'] is True for c in all_cases if c['id'] in observed)!=19:raise ValueError('historical valid count changed')
    for ident in ['s4-b02-off',*SUPPLEMENTS]:
        matches=[c for c in all_cases if c['id']==ident]
        if len(matches)!=1 or matches[0]['status']!='finished' or len(matches[0]['attempts'])!=1 or matches[0]['judgement']['trial_valid'] is not False or matches[0]['judgement']['cleanup'] is not True:
            raise ValueError('boundary/origin not a closed invalid first attempt: '+ident)
    if forward_credit(profile)['margin_krw']<=0:raise ValueError('credit reserve unavailable')
    return dict(authorization=a,source_transition=sorted(changed),reviewed_diff=diffs,
        preparation_reused=sorted(reusable),predecessor_observed_main=sorted(observed),no_primary_replacement=True,
        stability_qualified=True,current_preparation_qualified=True,old_invalid_preserved=8,old_valid_unchanged=19)
