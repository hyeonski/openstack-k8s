"""Versioned fresh-cohort contracts. No cloud imports or side effects."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path

MODES = {'s1': {'P', 'M', 'A', 'V1'}, 's2': {'P', 'M'},
         's3': {'P3600', 'M3600'}, 's4': {'on', 'off'}}
SUPPORTED_FAULTS = {
    's1': {'cpu_workers': 4, 'flavor_vcpus': 4, 'workload': 'pbkdf2-100000'},
    's2': {'egress_mbps': 20, 'chunk_bytes': 1048576, 'max_chunks': 4096},
    's3': {'blocked_tcp_ports': [6443, 5432], 'old_database_running': True},
    's4': {'action': 'exact-worker-vm-stop'},
}
SUPPORTED_FIXTURE = {
    's2_port_qos_workload_progress': {'qos': 'unattached', 'upload_bytes': 0, 'upload_next': 0, 'shared_port': True, 'response_bytes': 262144},
    's3_volume_seed': {'records':1000,'volume':'new-cinder-pvc','seed':'profile-seed-and-block'},
    's4_capacity': {'workers':2,'http_replicas':1},
}
BASELINE_CONTRACT = {'duration_seconds': 60, 'bin_seconds': 20, 'required_complete_healthy_bins': 3, 'slo_and_bad_fraction': 'same as scenario (V1 uses v1_condition)', 'scope': 'pre-injection; preserve arrival/start/completion raw and await final request deadlines', 'implementation_status_at_registration': 'executor must implement and verify before first pilot freeze', 'start_rule': 'index 0 of the registered probe stream after probe readiness; never first observed row', 'first_arrival_index': 0, 'bin_assignment': 'arrival index ranges of 20 * scenario rate; validate UTC/monotonic schedule consistency separately', 'window_selection': 'first 60 * rate scheduled arrivals; no sliding or success-based window selection', 'completion_grace_seconds': 5, 'policy_baseline': 'preserve existing policy window and record both windows; S1 policy last 60 seconds after its existing 90-second wait'}

STATES = ('PREPARED', 'BASELINE', 'INJECTED', 'OBSERVING', 'HORIZON_END', 'CLEANUP', 'VERIFIED')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def expected_requests(config):
    """S1 seconds includes warmup; loadgen measure excludes warmup."""
    return int(config['rate'] * config['seconds'])


def schedule(profile):
    validate(profile)
    return [dict(c, status='pending', negative=False) for c in profile['cases']]


def validate(p, live=False):
    if not isinstance(p,dict) or not isinstance(p.get('cases'),list) or not all(isinstance(c,dict) for c in p['cases']):
        raise ValueError('profile must be an object with explicit case objects')
    if any(not isinstance(p.get(s),dict) for s in MODES):
        raise ValueError('scenario configuration objects required')
    for key in ('operations','timers','analysis','fault','initial_fixture'):
        if not isinstance(p.get(key),dict):raise ValueError(key+': configuration object required')
    if p.get('v1_selected') is not None and not isinstance(p['v1_selected'],dict):raise ValueError('V1 selected candidate must be an object')
    if p['s2'].get('uploader_seconds') is not None and (type(p['s2']['uploader_seconds']) is not int or p['s2']['uploader_seconds']<=0):raise ValueError('S2 uploader duration must be positive integer seconds')
    if not isinstance(p.get('v1_candidates'),list):raise ValueError('V1 candidates list required')
    v1=p.get('v1_condition')
    if not isinstance(v1,dict):raise ValueError('v1_condition object required')
    for name,value in [('v1_condition.slo_ms',v1.get('slo_ms')),
                       ('s3.evidence_timeout_seconds',p['s3'].get('evidence_timeout_seconds'))]:
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<=0):
            raise ValueError(name+': finite positive number or draft null required')
    fraction=v1.get('bin_max_bad_fraction')
    if fraction is not None and (type(fraction) not in (int,float) or not math.isfinite(fraction) or not 0<=fraction<1):
        raise ValueError('v1_condition.bin_max_bad_fraction: finite fraction in [0,1) required')
    for c in p['cases']:
        if set(c)-{'id','scenario','mode','purpose','block','seed','session','order','depends_on'}:
            raise ValueError('unsupported case contract field')
        if not all(isinstance(c.get(k),str) for k in ('id','scenario','mode','purpose','block','session')):
            raise ValueError('case identifiers, scenario, mode, purpose, block and session must be strings')
        if not isinstance(c.get('depends_on',[]),list) or not all(isinstance(d,str) for d in c.get('depends_on',[])):
            raise ValueError('depends_on must contain case IDs')
    for scenario in MODES:
        fraction=p[scenario].get('bin_max_bad_fraction')
        if fraction is not None and (type(fraction) not in (int,float) or not math.isfinite(fraction) or not 0<=fraction<1):
            raise ValueError(scenario+'.bin_max_bad_fraction: finite fraction in [0,1) required')
        for key in ('horizon_seconds','stable_seconds','bin_seconds','min_samples','deadline_seconds','slo_ms','rate',*(['max_clock_offset_seconds'] if scenario in ('s1','s2') else [])):
            value=p[scenario].get(key)
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<=0):
                raise ValueError(scenario+'.'+key+': finite positive number or draft null required')
            if value is not None and key in ('horizon_seconds','stable_seconds','bin_seconds','min_samples') and type(value) is not int:
                raise ValueError(scenario+'.'+key+': integer required')
    for key in ('max_case_seconds','host_headroom_seconds','max_attempts'):
        if type(p.get(key)) is not int or p[key]<=0:raise ValueError(key+': positive integer required')
    errors = []
    def require(ok, message):
        if not ok:
            errors.append(message)
    require(p.get('schema_version') == 3, 'schema_version must be 3')
    require(p.get('scope') == 'F-repeated', 'scope must be F-repeated')
    require(type(p.get('seed')) is int, 'seed must be an integer')
    require(p.get('historical_results') == 'excluded', 'historical results must be excluded')
    cases = p.get('cases', [])
    require(len(cases) == 37, 'F-repeated requires 29 main + 8 preparation cases')
    ids = [c.get('id') for c in cases]
    require(len(ids) == len(set(ids)), 'duplicate case ID')
    counts = Counter(c.get('purpose') for c in cases)
    require(counts == {'main': 29, 'pilot': 7, 'smoke': 1}, 'purpose counts must be main=29 pilot=7 smoke=1')
    for c in cases:
        cid = c.get('id', '')
        require(isinstance(cid, str) and bool(cid) and all(x.isalnum() or x == '-' for x in cid), 'unsafe case ID')
        require(c.get('mode') in MODES.get(c.get('scenario'), set()), f'{cid}: unknown scenario/mode')
        require(type(c.get('seed')) is int and c.get('seed') == p.get('seed'), f'{cid}: seed mismatch')
        require(isinstance(c.get('block'), str) and bool(c['block']), f'{cid}: block required')
        require(c.get('session') in ('SESSION-A', 'SESSION-B', 'SESSION-C', 'SESSION-D', 'SESSION-E'), f'{cid}: session required')
        require(type(c.get('order')) is int, f'{cid}: order required')
        for dep in c.get('depends_on', []):
            require(dep in ids[:ids.index(cid)], f'{cid}: dependency must precede case: {dep}')
    require([c.get('order') for c in cases] == list(range(1, len(cases) + 1)), 'order must match explicit list')
    for scenario, modes in MODES.items():
        for mode in modes:
            n = sum(c.get('purpose') == 'main' and c.get('scenario') == scenario and c.get('mode') == mode for c in cases)
            require(n == (2 if mode == 'V1' else 3), f'{scenario}/{mode}: incorrect main repetition count')
        for b in ('b01', 'b02', 'b03'):
            rows = [c for c in cases if c.get('scenario') == scenario and c.get('block') == b and c.get('purpose') == 'main']
            require({c.get('mode') for c in rows} == modes - {'V1'}, f'{scenario}/{b}: incomplete paired block')
    expected_preparation={('s1','P','smoke'):1,('s1','V1','pilot'):1,('s2','P','pilot'):1,('s2','M','pilot'):1,('s3','P3600','pilot'):1,('s3','M3600','pilot'):1,('s4','on','pilot'):1,('s4','off','pilot'):1}
    require(Counter((c['scenario'],c['mode'],c['purpose']) for c in cases if c['purpose']!='main')==expected_preparation,'preparation must contain the registered smoke and all four pilot arms/pairs')
    if cases:
        s4=[i for i,c in enumerate(cases) if c['scenario']=='s4']
        require(not s4 or all(c['scenario']=='s4' for c in cases[min(s4):]),'S4 must remain last')
    for s in MODES:
        cfg = p.get(s, {})
        for key in ('horizon_seconds', 'stable_seconds', 'bin_seconds', 'min_samples', 'deadline_seconds', 'slo_ms', 'rate'):
            value = cfg.get(key)
            require(value is None or (type(value) in (int, float) and math.isfinite(value) and value > 0), f'{s}.{key}: positive number or draft null required')
            if live:
                require(value is not None, f'{s}.{key}: unresolved live parameter')
        if cfg.get('horizon_seconds') and cfg.get('bin_seconds'):
            require(cfg['horizon_seconds'] % cfg['bin_seconds'] == 0, f'{s}: H must contain whole bins')
        if cfg.get('bin_seconds') and cfg.get('rate') and cfg.get('min_samples'):
            require(cfg['min_samples']<=cfg['bin_seconds']*cfg['rate'], f'{s}: min_samples exceeds registered bin arrivals')
        if cfg.get('bin_seconds') and cfg.get('rate'):
            require(float(cfg['bin_seconds']*cfg['rate']).is_integer(),f'{s}: register whole scheduled arrivals per bin')
        if cfg.get('stable_seconds') and cfg.get('horizon_seconds'):
            require(cfg['stable_seconds'] <= cfg['horizon_seconds'], f'{s}: stability exceeds H')
    require(p.get('s1', {}).get('seconds') == 1800, 'S1 total load duration must be 1800')
    require(p.get('s1', {}).get('warmup_seconds') == 0, 'S1 current semantics requires warmup=0')
    require(p.get('s1', {}).get('rate') == 5, 'registered S1 rate must be 5')
    for key in ('fault', 'v1_candidates', 'v1_selected', 'initial_fixture', 'timers', 'environment', 'operations'):
        require(key in p, key + ' required')
        if live and key not in ('operations','timers'):
            require(not unresolved(p.get(key)), key + ': unresolved live input')
    if live:
        for s in MODES:
            require(p[s].get('bin_max_bad_fraction') is not None,s+'.bin_max_bad_fraction: unresolved live parameter')
        v1=p.get('v1_condition',{})
        require(isinstance(v1,dict) and type(v1.get('slo_ms')) in (int,float) and math.isfinite(v1['slo_ms']) and v1['slo_ms']>0,'v1_condition.slo_ms: unresolved/invalid live parameter')
        require(isinstance(v1,dict) and type(v1.get('bin_max_bad_fraction')) in (int,float) and math.isfinite(v1['bin_max_bad_fraction']) and 0<=v1['bin_max_bad_fraction']<1,'v1_condition.bin_max_bad_fraction: unresolved/invalid live parameter')
        require(isinstance(v1,dict) and v1.get('baseline_p95_ratio')==1.5,'V1 baseline ratio must match fixed S1 policy (1.5)')
        require(type(p['s3'].get('evidence_timeout_seconds')) in (int,float) and math.isfinite(p['s3']['evidence_timeout_seconds']) and p['s3']['evidence_timeout_seconds']>0,'s3.evidence_timeout_seconds: unresolved/invalid live parameter')
        for scenario in ('s1','s2'):
            require(p[scenario].get('max_clock_offset_seconds') is not None,f'{scenario}.max_clock_offset_seconds: unresolved live clock bound')
        ops=p.get('operations',{})
        require(all(type(ops.get(k)) in (int,float) and math.isfinite(ops[k]) and ops[k]>0 for k in ('budget_seconds','cleanup_seconds')), 'operations budget/cleanup must be positive seconds')
        require(isinstance(ops,dict) and all(not unresolved(ops.get(k)) for k in ('operator','budget_seconds','last_injection_utc','cleanup_seconds','environment_override','execution_checkout','artifact_root')), 'operations: unresolved live input')
        if type(ops.get('cleanup_seconds')) in (int,float):
            require(p['host_headroom_seconds']>=p['max_case_seconds']+ops['cleanup_seconds'],'host headroom must cover maximum case and cleanup')
        require(all(p.get(k)==v for k,v in [('source_compute','osk8s-compute02'),('target_compute','osk8s-compute01'),('control_plane_compute','osk8s-compute01')]), 'current adapters require registered fixed compute roles')
        for s in MODES:
            cfg=p[s]
            if cfg.get('horizon_seconds') and cfg.get('stable_seconds'):
                require(cfg['horizon_seconds']+cfg['stable_seconds'] < p.get('max_case_seconds',0), f'{s}: max_case_seconds must cover H plus preparation')
        require((p['s1'].get('horizon_seconds') or 0)>=900, 'S1 H must cover bounded diagnosis and action (>=900s)')
        require((p['s2'].get('horizon_seconds') or 0)>=600, 'S2 H must cover diagnosis and split/QoS (>=600s)')
        require(p['initial_fixture']==SUPPORTED_FIXTURE,'initial fixture must match the supported workload/reset contract')
        require(p['s2']['rate']==2,'S2 existing baseline and policy require rate=2')
        require(type(p['s1'].get('rounds')) is int and 10000<=p['s1']['rounds']<=1000000,'S1 workload rounds outside supported range')
        require(p.get('fault') == SUPPORTED_FAULTS, 'fault values differ from supported fixed injectors')
        require(all((p[s].get('deadline_seconds') or 0)>=1 for s in MODES),'deadline must be >=1 second for bounded probe subprocesses')
        for s in ('s1','s2'):
            require(p.get(s,{}).get('deadline_seconds') == 5, f'{s}: current sampler timeout/deadline must be 5s')
        require(p.get('timers',{}).get('disable_force_detach') is True, 'force detach must be disabled in both S3 arms')
        require(p.get('v1_selected') in p.get('v1_candidates',[]), 'V1 selected candidate must be preregistered')
        require(p.get('v1_selected',{}) is not None and (p.get('v1_selected') or {}).get('cpu_workers') == 4, 'V1 current injector requires 4 CPU workers')
        require(all(isinstance(c,dict) and set(c)=={'cpu_workers','workload_rounds'} and c['cpu_workers']==4 and type(c['workload_rounds']) is int and 10000<=c['workload_rounds']<=1000000 for c in p['v1_candidates']),'V1 candidates outside supported injector/workload range')
        mhc=p['timers'].get('mhc_policy')
        require(isinstance(mhc,dict) and isinstance(mhc.get('s3_specs'),list) and all(isinstance(spec,dict) for spec in mhc.get('s3_specs',[])),'timers.mhc_policy.s3_specs: register actual MHC specs (empty list if absent)')
        require(p.get('readiness') == 'confirmed', 'readiness must be confirmed after calibration')
        try:
            from fresh_evidence import epoch
            epoch(ops['last_injection_utc'])
        except (KeyError,TypeError,ValueError,AttributeError):
            errors.append('operations.last_injection_utc: timezone-aware timestamp required')
        from fresh_operations import PHASE_LIMITS, TIME_KEYS
        extended = (*PHASE_LIMITS, 'bed_uptime_limit_seconds', 'bed_uptime_soft_limit_seconds',
                    'credit_budget_krw', 'new_work_budget_krw', 'cleanup_reserve_krw', 'clock_failure_stop_after_attempts')
        require(all(type(ops.get(k)) is int and ops[k]>0 for k in extended), 'operations: positive integer phase/budget limits required')
        require(all(isinstance(ops.get(k),str) and ops[k] for k in (*TIME_KEYS,'bed_ledger_path','development_artifact_root')), 'operations: deadline and ledger/DEV paths required')
        try:
            times=[epoch(ops[k]) for k in TIME_KEYS]
            require(times==sorted(set(times)), 'operational deadlines must be strictly ordered')
            require(ops['environment_ensure_timeout_seconds']<=3600 and ops['fixture_prepare_timeout_seconds']<=1800 and ops['cleanup_seconds']<=1800 and ops['host_shutdown_timeout_seconds']<=1800 and p['max_case_seconds']<=5400, 'phase limits exceed approved bounds')
            require(p['host_headroom_seconds']>=ops['fixture_prepare_timeout_seconds']+p['max_case_seconds']+ops['cleanup_seconds']+ops['host_shutdown_timeout_seconds'], 'host headroom must cover fixture, adapter, cleanup and shutdown')
            require(ops['bed_uptime_soft_limit_seconds']<=158400 and ops['bed_uptime_limit_seconds']<=172800 and ops['bed_uptime_soft_limit_seconds']<ops['bed_uptime_limit_seconds'], 'bed uptime limits exceed approved 44/48 hours')
            require(ops['new_work_budget_krw']<=160000 and ops['cleanup_reserve_krw']>=40000 and ops['new_work_budget_krw']+ops['cleanup_reserve_krw']<=ops['credit_budget_krw'], 'cost gate/reserve invalid')
            credit=ops['credit_evidence']
            require(credit['remaining_krw']>=ops['credit_budget_krw'] and epoch(credit['expires_utc'])>times[-1] and credit['source'] in ('user-reported','billing-console') and bool(credit['confirmed_utc']), 'credit evidence does not cover registered work')
            basis=ops['cost_estimate']
            require(all(type(basis[k]) in (int,float) and math.isfinite(basis[k]) and basis[k]>0 for k in ('bed_hour_krw','calendar_day_krw','other_usage_reserve_krw')), 'cost estimate must cover compute, retained resources and other usage')
            require(ops['clock_failure_stop_after_attempts']==2, 'clock failures must stop after two consecutive attempts')
            for key in ('artifact_root','development_artifact_root','bed_ledger_path'):
                require(Path(ops[key]).is_absolute(), key+': absolute path required')
            require(not Path(ops['development_artifact_root']).is_relative_to(Path(ops['artifact_root'])) and not Path(ops['artifact_root']).is_relative_to(Path(ops['development_artifact_root'])), 'DEV must be outside campaign artifact root')
        except (KeyError,TypeError,ValueError,AttributeError):
            errors.append('operations: incomplete/invalid deadline, credit or phase contract')
        documents=ops.get('preregistered_documents')
        require(isinstance(documents,list) and len(documents)>=2 and len(documents)==len(set(documents)) and all(isinstance(n,str) and not Path(n).is_absolute() and '..' not in Path(n).parts for n in documents), 'operations.preregistered_documents: explicit safe relative documents required')
        require(p['analysis'].get('baseline_contract')==BASELINE_CONTRACT, 'analysis.baseline_contract: unsupported or missing fixed first-arrival contract')
        secondary=p['analysis'].get('secondary_metrics',{}).get('scheduled_latency_p95_ms_difference',{})
        require(secondary.get('scenarios')==['s1','s2'] and bool(secondary.get('interpretation')), 'analysis.secondary_metrics: registered S1/S2 conditional p95 difference required')
        require(p.get('max_attempts') == 2, 'register one additional retry at most')
        require(p.get('analysis', {}).get('contrasts') == [['s1', 'P', 'M'], ['s1', 'P', 'A'], ['s2', 'P', 'M'], ['s3', 'P3600', 'M3600'], ['s4', 'on', 'off']], 'primary contrasts changed')
        require((p.get('s2', {}).get('uploader_seconds') or 0) >= (p.get('s2', {}).get('horizon_seconds') or math.inf) + 600,
                'S2 uploader must stay active through H including relocation')
        require((p.get('s2', {}).get('horizon_seconds') or math.inf) * 20_000_000 / 8 < 4096 * 1024**2,
                'S2 registered upload size cannot saturate before H')
        require(p.get('timers', {}).get('toleration_seconds') == 3600, 'S3 both arms require 3600s toleration')
    if errors:
        raise ValueError('; '.join(errors))
    if live and 's1_calibration' in p.get('analysis', {}):
        from fresh_calibration import validate_binding
        validate_binding(p)
    return {'main': counts['main'], 'preparation': counts['pilot'] + counts['smoke'], 'development': 'separate'}


def unresolved(value):
    if value is None or value == '' or value == [] or value == {}:
        return True
    if isinstance(value, dict):
        return any(unresolved(v) for v in value.values())
    if isinstance(value, list):
        return any(unresolved(v) for v in value)
    return False


def load(path, live=False):
    profile = json.loads(Path(path).read_text())
    validate(profile, live)
    return profile
