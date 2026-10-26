"""Independent fresh evidence adapter and judgement; runner success flags are ignored."""
from __future__ import annotations

from collections import Counter
import json
import hashlib
import math
from pathlib import Path

from fresh_contract import expected_requests, digest
from fresh_evidence import epoch


def read(path, default=None):
    return json.loads(Path(path).read_text()) if Path(path).is_file() else default


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line] if Path(path).exists() else []


def quantile(values, q=.95):
    if not values:
        return None
    v = sorted(values); rank = (len(v) - 1) * q
    lo = math.floor(rank); hi = math.ceil(rank)
    return v[lo] + (v[hi] - v[lo]) * (rank - lo)


def normalize(directory):
    """Never modify raw. Each normalized row identifies its raw file, index and rule."""
    directory = Path(directory)
    result = []
    for i, row in enumerate(rows(directory / 'requests.jsonl')):
        result.append({**row, 'provenance': {'file': 'requests.jsonl', 'row': i + 1,
                       'fields': list(row), 'transform': 'fresh-request-v1 identity; UTC parsed only during analysis'}})
    return result


def request_metrics(requests, cfg, start, end, expected=None):
    errors = []
    indexed = {}
    for row in requests:
        key = row.get('request_id')
        if key is None or key in indexed:
            errors.append('missing_or_duplicate_request_id')
        indexed[key] = row
    indexed_arrivals = sorted((r for r in requests if type(r.get('index')) is int), key=lambda r:r['index'])
    indexes=[r['index'] for r in indexed_arrivals]
    if len(indexes)!=len(set(indexes)):
        errors.append('duplicate_arrival_index')
    for a,b in zip(indexed_arrivals,indexed_arrivals[1:]):
        if a.get('clock_id')==b.get('clock_id') and a.get('started_monotonic') is not None and b.get('started_monotonic') is not None and a.get('started_utc') and b.get('started_utc') and abs((epoch(b['started_utc'])-epoch(a['started_utc']))-(b['started_monotonic']-a['started_monotonic']))>.1:
            errors.append('clock_step_between_requests')
        if a.get('clock_id')==b.get('clock_id') and abs(epoch(b['scheduled_utc'])-epoch(a['scheduled_utc'])-(b['index']-a['index'])/cfg['rate'])>.01:
            errors.append('arrival_schedule_mismatch')
    expected = expected if expected is not None else int(round((end - start) * cfg['rate']))
    arrivals = [r for r in requests if start <= epoch(r['scheduled_utc']) < end]
    missing = max(0, expected - len(arrivals))
    if missing or len(arrivals) != expected:
        errors.append('request_arrivals_incomplete')
    latencies, execution_latencies, queue = [], [], []
    failures = missing
    incomplete = rejected = 0
    timed = []
    for row in arrivals:
        scheduled = epoch(row['scheduled_utc'])
        begin = epoch(row['started_utc']) if row.get('started_utc') else None
        finish = epoch(row['completed_utc']) if row.get('completed_utc') else None
        if begin is not None and begin < scheduled - .001 or finish is not None and (begin is None or finish < begin):
            errors.append('request_time_reversed')
        if row.get('started_monotonic') is not None and row.get('completed_monotonic') is not None:
            if row.get('completed_clock_id', row.get('clock_id')) != row.get('clock_id') or row['completed_monotonic'] < row['started_monotonic']:
                errors.append('request_monotonic_invalid')
            elif begin is not None and finish is not None and abs((finish-begin)-(row['completed_monotonic']-row['started_monotonic']))>.1:
                errors.append('wall_monotonic_duration_disagreement')
        rejection = row.get('generator_rejection', False)
        rejected += bool(rejection)
        incomplete += finish is None and not rejection
        total_ms = (finish - scheduled) * 1000 if finish is not None else None
        ordered=begin is not None and finish is not None and scheduled-.001<=begin<=finish
        good = bool(ordered and row.get('ok') and row.get('correct') and begin is not None and finish is not None
                    and not rejection and total_ms <= cfg['deadline_seconds'] * 1000)
        failures += not good
        if begin is not None:
            queue.append((begin - scheduled) * 1000)
        if good:
            latencies.append(total_ms)
            execution_latencies.append((finish - begin) * 1000)
        timed.append((scheduled, good, total_ms))
    bins = []
    bin_seconds = cfg['bin_seconds']
    for i in range(math.ceil((end - start) / bin_seconds)):
        a, b = start + i * bin_seconds, min(end, start + (i + 1) * bin_seconds)
        samples = [r for r in timed if a <= r[0] < b]
        complete = len(samples) >= max(cfg['min_samples'], int(round((b - a) * cfg['rate'])))
        healthy = complete and all(ok and latency <= cfg['slo_ms'] for _, ok, latency in samples)
        bins.append(dict(start=a, end=b, samples=len(samples), complete=complete, healthy=healthy))
    # Recovery is the final contiguous healthy tail; an earlier healthy interval followed by relapse is not final recovery.
    tail = []
    for b in bins:
        if b['healthy']:
            tail.append(b)
        else:
            tail = []
    stable_start = tail[0]['start'] if tail and tail[-1]['end'] - tail[0]['start'] >= cfg['stable_seconds'] else None
    confirmed = next((b['end'] for b in tail if stable_start is not None and b['end'] - stable_start >= cfg['stable_seconds']), None)
    return dict(expected_arrivals=expected, observed_arrivals=len(arrivals), failures=failures,
                failure_rate=failures / expected if expected else None, missing=missing, incomplete=incomplete,
                generator_rejections=rejected, scheduled_latency_p95_ms=quantile(latencies),
                execution_latency_p95_ms=quantile(execution_latencies), queue_p95_ms=quantile(queue),
                violation_seconds_lower_bound=sum(b['end'] - b['start'] for b in bins if b['complete'] and not b['healthy']),
                unobserved_seconds=sum(b['end'] - b['start'] for b in bins if not b['complete']),
                impact_start=min((at for at,ok,latency in timed if not ok or latency>cfg['slo_ms']),default=None),
                recovery_start=stable_start, stable_confirmed=confirmed,
                recovery_seconds=stable_start - start if stable_start is not None else None,
                recovered=stable_start is not None, bins=bins, errors=sorted(set(errors)),
                units={'latency':'ms', 'recovery':'seconds', 'violation':'seconds'},
                interval=[start, end], limitation='success latency conditional on successful, correct requests before deadline')


def uploader_metrics(samples,start,end,max_gap=3):
    """Unique receiver byte growth inside H, with explicit edge censoring."""
    errors=[]
    observed=[r for r in samples if 'progress' in r and start<=epoch(r['utc'])<end]
    times=[epoch(r['utc']) for r in observed]
    if len(times)<2 or times!=sorted(set(times)):
        errors.append('uploader_samples_missing_or_reversed')
    windows=[{'start':a['utc'],'end':b['utc'],'before':a['progress'],'after':b['progress']} for a,b in zip(observed,observed[1:])]
    if not times or times[0]-start>max_gap or end-times[-1]>max_gap or any(b-a>max_gap for a,b in zip(times,times[1:])):
        errors.append('uploader_observation_gap')
    if any(w['after']['bytes']<w['before']['bytes'] or w['after']['next']<w['before']['next'] for w in windows):
        errors.append('uploader_progress_reversed')
    unique_bytes=observed[-1]['progress']['bytes']-observed[0]['progress']['bytes'] if len(observed)>1 else None
    return {'windows':windows,'errors':errors,'unique_bytes_lower_bound':unique_bytes,
            'edge_unobserved_seconds':(times[0]-start+end-times[-1]) if times else end-start,
            'goodput_lower_bound_Bps':unique_bytes/(end-start) if unique_bytes is not None else None}


def scenario_checks(case, raw, events):
    """Read identity/configuration snapshots, never summary booleans."""
    s, mode = case['scenario'], case['mode']
    checks, outcomes = {}, {}
    actions = [e for e in events if e['kind'] == 'action_applied' and e.get('actor') == 'policy']
    if s == 's1':
        before, after = raw['service_before'], raw['service_after']
        contender = raw['contender_after']
        checks['contention_persists'] = contender['status'] == 'ACTIVE' and contender['OS-EXT-SRV-ATTR:host'] == raw['source_compute']
        if mode in ('M', 'V1') or not actions:
            checks['no_action'] = len(actions) == 0 and all(before[k] == after[k] for k in ('pod_uid', 'node', 'nova_id', 'container_id', 'restart_count'))
        elif mode == 'A':
            checks['same_worker_restart'] = len(actions) == 1 and before['pod_uid'] != after['pod_uid'] and all(before[k] == after[k] for k in ('node', 'nova_id', 'image_id')) and raw['compute_before'] == raw['compute_after']
        else:
            checks['relocation'] = len(actions) == 1 and before['pod_uid'] != after['pod_uid'] and before['node'] != after['node'] and raw['compute_before'] != raw['compute_after']
        checks['action_target'] = all(e.get('target_uid') == before['pod_uid'] for e in actions)
        checks['contention_at_completion']=raw['completion_host_metrics']['cpu_utilization']>=.7 and raw['completion_host_metrics']['cpu_pressure_some']>=.02
        checks['image_unchanged']=before['image_id']==after['image_id']
        checks['node_vm_identity'] = raw['node_before']['metadata']['uid'] == raw['node_after']['metadata']['uid'] and raw['vm_before']['id'] == raw['vm_after']['id']
    elif s == 's2':
        initial, final = raw['initial'], raw['final']
        qdisc=raw['network_qdisc']
        checks['registered_bottleneck']=qdisc.get('kind')=='tbf' and qdisc.get('options',{}).get('rate')==20_000_000/8
        checks['source_port_initial'] = not initial.get('source_port',{}).get('qos_policy_id')
        checks['fresh_initial'] = initial['progress']['bytes'] == 0 and initial['progress']['next'] == 0 and not initial['port'].get('qos_policy_id') and initial['api_node'] == initial['upload_node']
        checks['uploader_progress_observed'] = bool(raw['upload_windows']) and all(w['after']['bytes'] > w['before']['bytes'] for w in raw['upload_windows'])
        checks['uploader_offered_through_H'] = raw.get('offered_seconds',raw.get('upload_elapsed_seconds',0)) >= raw.get('horizon_seconds',raw.get('upload_elapsed_seconds',0)) and raw['upload_windows'][-1]['after'].get('next',0) < raw.get('max_chunks',4096)
        outcomes['upload_progress_each_window']=checks['uploader_progress_observed']
        # A stalled uploader is a performance outcome, not grounds to discard an otherwise valid P run.
        checks.pop('uploader_progress_observed')
        checks['api_identity'] = initial['api_uid'] == final['api_uid']
        if mode == 'M':
            checks['no_policy'] = not actions and initial['upload_node'] == final['upload_node'] and not final['port'].get('qos_policy_id')
        elif not actions:
            checks['policy_held']=initial['upload_node']==final['upload_node'] and not final['port'].get('qos_policy_id')
        else:
            checks['split_and_qos'] = bool(actions) and final['upload_node'] != initial['api_node'] and final['port'].get('qos_policy_id') == raw['policy_id']
        byte_delta = raw['upload_windows'][-1]['after']['bytes'] - raw['upload_windows'][0]['before']['bytes']
        outcomes['upload_unique_bytes'] = byte_delta
        outcomes['upload_goodput_Bps'] = byte_delta / raw['upload_elapsed_seconds']
        manifest=raw['upload_integrity']['rows'];files=raw['upload_integrity']['files']
        checks['upload_unique_integrity']=len({r[0] for r in manifest})==len(manifest) and len(files)==len(manifest) and all(f['index']==r[0] and f['size']==r[1] and f['sha256']==r[2] for f,r in zip(files,manifest))
    elif s == 's3':
        tolerations = raw.get('pod_before',{}).get('spec',{}).get('tolerations',raw['statefulset']['spec']['template']['spec']['tolerations'])
        checks['matched_timers'] = all(any(t.get('key') == k and t.get('tolerationSeconds') == 3600 for t in tolerations) for k in ('node.kubernetes.io/not-ready','node.kubernetes.io/unreachable')) and '--disable-force-detach-on-timeout=true' in raw['controller_manifest'] and bool(raw['mhc_snapshot'])
        if mode == 'M3600' or not actions:
            checks['no_fence_or_oos'] = not raw.get('fence') and not actions and not any(e['kind'] in ('fence_confirmed','out_of_service_applied') and e.get('actor') == 'policy' for e in events)
        else:
            fence = next((e for e in events if e['kind'] == 'fence_confirmed'), None)
            oos = next((e for e in events if e['kind'] == 'out_of_service_applied'), None)
            server = raw.get('fence', {}).get('server', {})
            checks['fence_before_oos'] = bool(fence and oos and epoch(fence['utc']) <= epoch(oos['utc']) and server.get('status') == 'SHUTOFF' and server.get('id') == raw['source_vm'] and raw.get('fence', {}).get('hypervisor_state') == 'shut off')
        pvc,pv,volume=raw['pvc_after'],raw['pv_after'],raw['volume_after']
        checks['volume_identity'] = pvc['metadata']['uid']==raw['pvc_uid'] and pv['spec']['claimRef']['uid']==raw['pvc_uid'] and pv['spec']['csi']['volumeHandle']==volume['id']==raw['volume_id'] and len(volume.get('attachments',[]))<=1 and (not volume.get('attachments') or volume['attachments'][0]['server_id'] in (raw['source_vm'],raw['target_vm']))
        machine=raw['admitted_machine']
        checks['remediation_excluded']=machine['metadata']['uid']==raw['source_machine_uid'] and machine['metadata'].get('annotations',{}).get('cluster.x-k8s.io/skip-remediation')==raw['run_id']
        if mode=='M3600':
            checks['source_vm_still_running'] = raw['source_final']['id']==raw['source_vm'] and raw['source_final']['status']=='ACTIVE' and not any(t['key']=='node.kubernetes.io/out-of-service' for t in raw['db_final']['node']['spec'].get('taints',[]))
        expected_seed=digest({'seed':case['seed'],'block':case['block'],'scenario':'s3','purpose':case['purpose']})
        expected_rows=[{'id':i,'value':hashlib.md5((str(i)+expected_seed).encode()).hexdigest()} for i in range(1,1001)]
        checks['registered_seed']=raw['seed']==expected_seed and raw['seed_before']==expected_rows
        if mode=='P3600' and actions:
            server=raw['fence']['server'];final=raw['source_final']
            checks['fence_power_identity']=server.get('OS-EXT-STS:power_state')==4 and server.get('OS-EXT-STS:task_state') is None and server.get('OS-EXT-SRV-ATTR:host')==raw['source_host']
            checks['fence_persists']=final['id']==raw['source_vm'] and final['status']=='SHUTOFF' and final.get('OS-EXT-STS:power_state')==4 and final.get('OS-EXT-STS:task_state') is None and final.get('OS-EXT-SRV-ATTR:host')==raw['source_host'] and raw['source_final_hypervisor']=='shut off'
        outcomes['seed_preserved'] = raw.get('seed_after') == raw['seed_before'] if raw.get('seed_after') is not None else None
        if raw.get('seed_after') is not None and raw.get('volume_after') and actions:
            checks['recovered_volume_target']=len(raw['volume_after']['attachments'])==1 and raw['volume_after']['attachments'][0]['server_id']==raw['target_vm'] and raw['db_final']['pod']['spec']['nodeName']==raw['target_node'] and raw['db_final']['pod']['metadata']['uid']!=raw['pod_before']['metadata']['uid']
        process_id=raw['pod_before']['status']['containerStatuses'][0]['containerID'].split('://',1)[-1]
        checks['old_database_identity']=sum(c.get('id')==process_id and c.get('state')=='CONTAINER_RUNNING' and c.get('labels',{}).get('io.kubernetes.pod.uid')==raw['pod_before']['metadata']['uid'] for c in raw['old_database_processes']['containers'])==1
        checks['seed_not_corrupted'] = outcomes['seed_preserved'] is not False
    else:
        before, during, restored = raw['mhc_before'], raw['mhc_during'], raw['mhc_restored']
        checks['mhc_restored'] = before['spec'] == restored['spec'] and before['metadata']['uid'] == restored['metadata']['uid'] and before['metadata'].get('annotations',{}) == restored['metadata'].get('annotations',{})
        checks['mhc_arm'] = ('cluster.x-k8s.io/paused' in during['metadata'].get('annotations', {})) == (mode == 'off')
        checks['mhc_identity'] = before['metadata']['uid'] == during['metadata']['uid']
        capacity = raw['capacity']
        from graduation_s4_run import summarize_capacity
        capacity = summarize_capacity(raw['capacity_snapshot'],raw['target'],raw['original_workers'],raw['probe_name'])
        checks['stop_identity'] = raw['stopped_vm']['id'] == raw['target']['nova_id'] and raw['stopped_vm']['status'] == 'SHUTOFF'
        outcomes['capacity_recovered'] = capacity.get('state') == 'recovered'
        if outcomes['capacity_recovered']:
            replacement = capacity['replacement']; binding = raw['replacement_binding']
            checks['replacement_identity_placement'] = all(replacement[k] == binding[k] for k in ('machine_uid','node','nova_id')) and binding['host'] in raw['allowed_computes'] and replacement['machine_uid'] != raw['target']['machine_uid'] and binding['node_uid'] != raw['target']['node_uid'] and binding['nova_id'] != raw['target']['nova_id']
            node=next(n for n in raw['capacity_snapshot']['nodes']['items'] if n['metadata']['name']==replacement['node'])
            checks['node_schedulable']=not node['spec'].get('unschedulable') and not any(t['effect'] in ('NoSchedule','NoExecute') for t in node['spec'].get('taints',[]))
            checks['usable_capacity'] = raw['capacity_probe']['spec'].get('nodeName') == replacement['node'] and raw['capacity_probe']['spec'].get('nodeSelector',{}).get('kubernetes.io/hostname') == replacement['node'] and raw['capacity_probe']['status']['phase'] == 'Running' and any(c['type'] == 'Ready' and c['status'] == 'True' for c in raw['capacity_probe']['status']['conditions'])
    return checks, outcomes


def _judge(directory, case, profile):
    directory = Path(directory)
    events, requests = rows(directory / 'events.jsonl'), normalize(directory)
    errors = []
    ids = [e.get('event_id') for e in events]
    if len(ids) != len(set(ids)) or None in ids:
        errors.append('duplicate_or_missing_event_id')
    by_clock = {}
    for e in events:
        if not all(k in e for k in ('utc','monotonic_ns','clock_id','observer','target_uid')):
            errors.append('incomplete_event_clock'); continue
        epoch(e['utc'])
        if type(e['monotonic_ns']) is not int or e['monotonic_ns']<0 or not isinstance(e['clock_id'],str):
            errors.append('invalid_event_clock');continue
        if e['clock_id'] in by_clock and (e['monotonic_ns'] < by_clock[e['clock_id']][0] or epoch(e['utc']) < by_clock[e['clock_id']][1]):
            errors.append('event_time_reversed')
        by_clock[e['clock_id']] = (e['monotonic_ns'], epoch(e['utc']))
    phases = [e.get('phase') for e in events if e['kind'] == 'phase']
    from fresh_contract import STATES
    if phases != list(STATES):
        errors.append('phase_sequence_incomplete')
    injected = next((e for e in events if e['kind'] == 'injection_applied'), None)
    ended = next((e for e in events if e['kind'] == 'horizon_end'), None)
    cfg = profile[case['scenario']]
    if sum(e['kind']=='injection_applied' for e in events)!=1 or sum(e['kind']=='horizon_end' for e in events)!=1:
        errors.append('semantic_event_missing_or_duplicate')
    metrics = {}
    if not injected or not ended:
        errors.append('horizon_missing')
    else:
        start, end = epoch(injected['utc']), epoch(injected['utc']) + cfg['horizon_seconds']
        if epoch(ended['utc']) + .001 < end:
            errors.append('early_observation_end')
        if injected['clock_id']==ended['clock_id'] and (ended['monotonic_ns']-injected['monotonic_ns'])/1e9+.001<cfg['horizon_seconds']:
            errors.append('early_monotonic_horizon_end')
        if case['scenario'] in ('s1','s2'):
            clock_rows=rows(directory/'clock-checks.jsonl')
            if {r['phase'] for r in clock_rows}!={'before-injection','horizon-end'} or not all(math.isfinite(r['offset_lower_seconds']) and math.isfinite(r['offset_upper_seconds']) and r['offset_lower_seconds']<=r['offset_upper_seconds'] and max(abs(r['offset_lower_seconds']),abs(r['offset_upper_seconds']))<=cfg['max_clock_offset_seconds'] for r in clock_rows):
                errors.append('clock_alignment_unverified')
        metrics = request_metrics(requests, cfg, start, end)
        if case['scenario'] in ('s1','s2'):metrics['clock_alignment_bounds']=clock_rows
        errors.extend(metrics['errors'])
        last_request=None
        for event in events:
            if event.get('actor')=='policy' and event['kind']=='action_requested':last_request=event
            if event.get('actor')=='policy' and event['kind']=='action_applied':
                if not last_request or not start<=epoch(last_request['utc'])<=epoch(event['utc'])<=end:
                    errors.append('action_outside_horizon_or_without_request')
        if case['scenario']=='s3':
            actual_specs=sorted((m['spec'] for m in read(directory/'observations/contract.json',{})['mhc_snapshot']['items']),key=digest)
            if actual_specs!=sorted(profile['timers']['mhc_policy']['s3_specs'],key=digest):errors.append('mhc_policy_mismatch')
        if case['scenario'] == 's1':
            indexes = [r.get('index') for r in requests]
            if len(indexes) != expected_requests(cfg) or set(indexes) != set(range(expected_requests(cfg))):
                errors.append('s1_total_request_indexes')
    raw = read(directory / 'observations' / 'contract.json', {})
    checks, outcomes = {}, {}
    try:
        checks, outcomes = scenario_checks(case, raw, events)
    except (KeyError, TypeError, IndexError, ZeroDivisionError) as exc:
        errors.append('scenario_evidence_missing:' + str(exc))
    if case['scenario']=='s2' and injected:
        upload=uploader_metrics(rows(directory/'uploader-progress.jsonl'),start,end)
        errors.extend(upload['errors'])
        outcomes['upload_unique_bytes']=upload['unique_bytes_lower_bound']
        outcomes['upload_goodput_Bps']=upload['goodput_lower_bound_Bps']
        outcomes['upload_edge_unobserved_seconds']=upload['edge_unobserved_seconds']
        network_realized=False
        for decision in rows(directory/'decisions.jsonl'):
            a,b=decision.get('raw_before'),decision.get('raw_after')
            if not a or not b or not (start<=epoch(a['utc'])<epoch(b['utc'])<=end):continue
            if a.get('clock_id')!=b.get('clock_id') or not a.get('clock_id'):
                errors.append('network_counter_clock_mismatch');continue
            elapsed=b['monotonic']-a['monotonic']
            if elapsed<=0:errors.append('network_counter_time_reversed');continue
            network_realized|=(b['qdisc']['bytes']-a['qdisc']['bytes'])*8/elapsed>=16_000_000 and b['qdisc']['overlimits']>a['qdisc']['overlimits']
        outcomes['network_contention_observed']=network_realized
    if case['scenario']=='s4' and raw.get('capacity_snapshot'):
        from graduation_s4_run import summarize_capacity
        snapshots=[read(p) for p in sorted((directory/'observations').glob('capacity-*.json'))]
        streak=[]
        for snap in snapshots:
            if not injected or not start<=epoch(snap.get('collected_utc',snap['time']))<=end:continue
            if snap['mhc']['metadata']['uid']!=raw['mhc_before']['metadata']['uid'] or snap['mhc']['spec']!=raw['mhc_before']['spec'] or ('cluster.x-k8s.io/paused' in snap['mhc']['metadata'].get('annotations',{}))!=(case['mode']=='off'):
                errors.append('mhc_arm_changed_during_H')
            cap=summarize_capacity(snap,raw['target'],raw['original_workers'],raw['probe_name'])
            at=epoch(snap.get('collected_utc',snap['time']))
            if cap['state']!='recovered' or streak and not 0<at-streak[-1]<=15:
                streak=[]
            if cap['state']=='recovered':streak.append(at)
        capacity_recovered=bool(streak) and streak[-1]-streak[0]>=cfg['stable_seconds'] and end-streak[-1]<=15
        outcomes['capacity_recovered']=capacity_recovered
        outcomes['capacity_recovery_seconds']=(streak[0]-epoch(injected['utc'])) if capacity_recovered and injected else None
        outcomes['capacity_observation_limit']='5s polling plus API duration; gaps >15s break stability'
    cleanup = read(directory / 'cleanup.json', {})
    cleaned = bool(cleanup.get('checks')) and all(v is True for v in cleanup['checks'].values())
    if checks.get('mhc_restored') is False:
        cleaned=False
    if not cleaned:
        errors.append('cleanup_incomplete')
    execution_error = any(e['kind'] == 'execution_error' for e in events)
    if execution_error:
        errors.append('execution_interrupted')
    fault = False
    if injected and raw:
        if case['scenario']=='s1':
            host=raw.get('host_metrics',{})
            fault=checks.get('contention_persists',False) and checks.get('contention_at_completion',False) and host.get('cpu_utilization',0)>=.7 and host.get('cpu_pressure_some',0)>=.02
        elif case['scenario']=='s2':fault=checks.get('registered_bottleneck',False) and outcomes.get('network_contention_observed',False) and (outcomes.get('upload_unique_bytes') or 0)>0
        elif case['scenario']=='s3':
            fault=checks.get('old_database_identity',False) and any(e['kind']=='node_not_ready_observed' and e.get('target_uid')==raw['source_node_uid'] and e.get('observation',{}).get('metadata',{}).get('uid')==raw['source_node_uid'] and any(c.get('type')=='Ready' and c.get('status') in ('False','Unknown') for c in e.get('observation',{}).get('status',{}).get('conditions',[])) for e in events)
        else:fault=checks.get('stop_identity',False)
    impact = any(b['complete'] and not b['healthy'] for b in metrics.get('bins', []))
    safety = bool(checks) and all(checks.values())
    recovered = metrics.get('recovered') if metrics else None
    if case['scenario'] == 's3' and recovered and outcomes.get('seed_preserved') is not True:
        safety = False
    v1 = None
    if case['mode'] == 'V1':
        host = raw.get('host_metrics', {})
        host_busy = fault
        v1 = 'exception' if execution_error else 'condition_not_realized' if not host_busy or impact else 'held' if safety else 'misaction'
    if injected:
        requested=next((e for e in events if e['kind']=='injection_requested'),None)
        metrics['injection_application_bounds_utc']=[requested['utc'] if requested else None,injected['utc']]
        metrics['injection_clock_limit']='applied is first independent confirmation; exact transition lies within request/confirmation bounds'
    contract_keys={'fresh_initial','registered_bottleneck','source_port_initial','uploader_offered_through_H','matched_timers','registered_seed','remediation_excluded','mhc_arm','mhc_identity','no_action','no_policy','no_fence_or_oos'}
    contract_valid=all(value for key,value in checks.items() if key in contract_keys and not (case['mode']=='V1' and key=='no_action'))
    metrics['safe_recovered']=bool(recovered and safety) if recovered is not None else None
    metrics['service_recovered']=recovered
    if case['scenario']=='s4':
        recovered=bool(recovered and outcomes.get('capacity_recovered')) if recovered is not None else None
        metrics['safe_recovered']=bool(recovered and safety) if recovered is not None else None
    if errors:
        recovered=None
        metrics.update(recovered=None,service_recovered=None,recovery_start=None,stable_confirmed=None,recovery_seconds=None,safe_recovered=None,scheduled_latency_p95_ms=None,execution_latency_p95_ms=None)
    return dict(trial_valid=not errors and contract_valid, fault_realized=fault, impact_realized=impact,
                recovered=recovered, safety=safety, execution='interrupted' if execution_error else 'finished',
                cleanup=cleaned, missing=sorted(set(errors)), checks=checks, v1_outcome=v1,
                metrics={**metrics, **outcomes}, evidence=['events.jsonl','requests.jsonl','observations/contract.json','cleanup.json'],
                provenance={'requests':'fresh-request-v1','events':'fresh-event-v1','scenario':'fresh-raw-contract-v1'},
                runner_summary_used=False)


def judge(directory,case,profile):
    try:
        return _judge(directory,case,profile)
    except (OSError,KeyError,TypeError,ValueError,IndexError,ZeroDivisionError) as exc:
        # Broken raw is an auditable failed judgement, never a crash that loses the attempt.
        return dict(trial_valid=False,fault_realized=None,impact_realized=None,recovered=None,
                    safety=None,execution='evidence_incomplete',cleanup=False,
                    missing=['malformed_evidence:'+str(exc)],checks={},v1_outcome=None,metrics={},
                    evidence=['events.jsonl','requests.jsonl','observations/contract.json','cleanup.json'],runner_summary_used=False)
