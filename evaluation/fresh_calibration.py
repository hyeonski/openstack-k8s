"""Registered S1 normal-load calibration. No scenario/fault/policy runner is called."""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / d) for d in ('scripts', 'experiments')]
from lib.state import atomic_json
from lib.runtime import LabRuntime
from fresh_baseline import baseline_metrics
from fresh_analysis import quantile, request_metrics, rows
from fresh_evidence import Evidence, append, clock_check, epoch, utc
from fresh_operations import BedLedger, phase
from fresh_campaign import source_hashes

PROTOCOL = 'docs/graduation/s1-baseline-calibration-protocol-2026-10-26.md'
RULE = dict(multiplier=1.20, round_up_ms=10, minimum_ms=200, maximum_ms=500,
            statistic='maximum of 45 linear-interpolated per-bin successful scheduled-latency p95 values',
            calibration_runs=3, validation_runs=2, seconds=300, diagnostic_runs=0,
            budget_seconds=7200, cleanup_seconds=1800, down_seconds=1800,
            per_run_overhead_reservation_seconds=120, freeze_reservation_seconds=60)
# Read-only bounded samplers. No files are written on hosts/guest.
SAMPLER = r'''
import datetime,json,pathlib,time,uuid
clock=uuid.uuid4().hex
start=time.monotonic()
for i in range(SECONDS+1):
    time.sleep(max(0,start+i-time.monotonic()))
    row={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'monotonic':time.monotonic(),'clock_id':clock,'index':i}
    for name,path in {'stat':'/proc/stat','cpu_pressure':'/proc/pressure/cpu','io_pressure':'/proc/pressure/io','memory_pressure':'/proc/pressure/memory','net':'/proc/net/dev','cgroup_cpu':'/sys/fs/cgroup/cpu.stat'}.items():
        try: row[name]=pathlib.Path(path).read_text()
        except OSError as e: row[name]={'error':str(e)}
    print(json.dumps(row),flush=True)
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def exclusive_json(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def check_root(directory, profile):
    directory = Path(directory).resolve()
    base = ROOT / 'artifacts/baseline-calibration-2026-10-26'
    if not directory.is_relative_to(base) or directory == base:
        raise ValueError('unique directory below calibration artifact root required')
    for key in ('artifact_root', 'development_artifact_root'):
        other = Path(profile['operations'][key]).resolve()
        if directory.is_relative_to(other) or other.is_relative_to(directory):
            raise ValueError('calibration must stay outside primary and DEV inputs')
    return directory


def register(directory, profile_path):
    profile_path = Path(profile_path).resolve()
    profile = json.loads(profile_path.read_text())
    if any(profile['s1'].get(k) != v for k,v in dict(rate=5,rounds=100000,warmup_seconds=0,
            deadline_seconds=5,bin_seconds=20,stable_seconds=120,bin_max_bad_fraction=.05).items()):
        raise ValueError('calibration requires the registered fixed S1 workload and judgement')
    directory = check_root(directory, profile)
    directory.mkdir(parents=True, exist_ok=False)
    source = source_hashes()
    for name in source:
        dest = directory/'source'/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, dest)
    shutil.copyfile(ROOT/PROTOCOL, directory/'protocol.md')
    shutil.copyfile(profile_path, directory/'registered-profile.json')
    manifest = dict(schema='s1-normal-calibration-v1', purpose='calibration/validation',
                    created_utc=utc(), primary_sample_count=0, injection_allowed=False,
                    rule=RULE, source_sha256=source, profile_path=str(profile_path),
                    profile_sha256=sha(profile_path), protocol_path=PROTOCOL,
                    protocol_sha256=sha(ROOT/PROTOCOL),
                    override_sha256=sha(profile['operations']['environment_override']))
    exclusive_json(directory/'registration.json', manifest)
    (directory/'registration.sha256').write_text(sha(directory/'registration.json')+'\n')
    return directory


def check_registration(directory):
    directory = Path(directory)
    if sha(directory/'registration.json') != (directory/'registration.sha256').read_text().strip():
        raise ValueError('registration changed')
    reg = json.loads((directory/'registration.json').read_text())
    if reg['rule'] != RULE or reg['source_sha256'] != source_hashes():
        raise ValueError('registered rule/source changed; new snapshot required')
    for name, expected in reg['source_sha256'].items():
        if sha(directory/'source'/name) != expected:
            raise ValueError('source snapshot changed: '+name)
    if sha(ROOT/reg['protocol_path']) != reg['protocol_sha256'] or sha(directory/'protocol.md') != reg['protocol_sha256']:
        raise ValueError('registered document changed')
    if sha(directory/'registered-profile.json') != reg['profile_sha256'] or sha(reg['profile_path']) != reg['profile_sha256']:
        raise ValueError('registered profile changed')
    profile = json.loads((directory/'registered-profile.json').read_text())
    check_root(directory, profile)
    if Path(os.environ.get('ENV_OVERRIDE_FILE','')).resolve() != Path(profile['operations']['environment_override']).resolve() or sha(profile['operations']['environment_override']) != reg['override_sha256']:
        raise ValueError('override differs')
    return profile, reg


def assess(requests, cfg, seconds=300):
    """Use the baseline validator on every fixed bin, without changing raw indexes."""
    expected = int(seconds*cfg['rate'])
    errors = []
    indexes = sorted(r.get('index', -1) for r in requests)
    if indexes != list(range(expected)):
        errors.append('full_arrival_indexes_incomplete_or_duplicate')
    if len({r.get('clock_id') for r in requests}) != 1:
        errors.append('full_clock_origin_mismatch')
    if len({r.get('request_id') for r in requests}) != len(requests):
        errors.append('full_duplicate_request_id')
    baseline = baseline_metrics(requests, cfg)
    # Full-window metrics retain the actual times; strict fixed indexes are checked
    # independently above. Baseline validator checks every row's schedule/clock.
    zero = next((r for r in requests if r.get('index') == 0), None)
    bins = []
    if zero:
        for start in range(0, expected, int(20*cfg['rate'])):
            chunk = [r for r in requests if start <= r.get('index', -1) < start+int(20*cfg['rate'])]
            # Duplicate this 20s bin into a 60s validation container by translating
            # time and index; only the first result bin is consumed. Original rows
            # are never changed, and global schedule checks reference real index0.
            translated = []
            for r in chunk:
                rr = {**r, 'index':r['index']-start}
                translated.append(rr)
                if abs(epoch(r['scheduled_utc'])-epoch(zero['scheduled_utc'])-r['index']/cfg['rate']) > .001 or abs(r['scheduled_monotonic']-zero['scheduled_monotonic']-r['index']/cfg['rate']) > .001:
                    errors.append('full_arrival_schedule_mismatch')
            local = baseline_metrics(translated, cfg)
            errors.extend(e for e in local['errors'] if e not in ('baseline_unhealthy','baseline_first_arrivals_incomplete_or_duplicate'))
            b = local['bins'][0]
            bins.append({**b, 'index_start':start, 'index_end':start+int(20*cfg['rate']), 'bad_fraction':b['bad']/(20*cfg['rate'])})
        start = epoch(zero['scheduled_utc'])
        metrics = request_metrics(requests, cfg, start, start+seconds, expected)
        errors.extend(metrics['errors'])
    else:
        errors.append('missing_index_zero')
        metrics = {}
    valid = not errors and len(bins) == seconds//20 and all(b['complete'] for b in bins)
    no_failures = all(metrics.get(k) == 0 for k in ('failures','missing','incomplete','generator_rejections'))
    return dict(baseline=baseline, bins=bins, full=metrics, errors=sorted(set(errors)),
                data_valid=valid, no_failures=no_failures,
                baseline_accepted=valid and baseline['passed'],
                sustained_accepted=valid and no_failures and all(b['healthy'] for b in bins),
                relapse_bins=[b['index_start'] for i,b in enumerate(bins) if i and not b['healthy'] and bins[i-1]['healthy']])


def choose(calibrations):
    if len(calibrations) != RULE['calibration_runs'] or any(not a['data_valid'] or not a['no_failures'] for a in calibrations):
        raise ValueError('three complete failure-free calibration runs required')
    bins = [b for a in calibrations for b in a['bins']]
    if len(bins) != 45 or any(b['successful_p95_ms'] is None for b in bins):
        raise ValueError('45 valid bin p95 values required')
    maximum = max(b['successful_p95_ms'] for b in bins)
    candidate = max(200, 10*math.ceil(1.20*maximum/10))
    if candidate > 500:
        raise ValueError(f'candidate {candidate}ms exceeds registered 500ms ceiling')
    return dict(slo_ms=candidate, maximum_calibration_bin_p95_ms=maximum, rule=RULE,
                calibration_bins=bins, retained_200_ms=candidate == 200)


def admission(started, runs_left, now=None):
    now = time.time() if now is None else now
    work_end = min(started+3600, epoch('2026-10-28T14:00:00Z'))
    required = runs_left*(300+120)+60
    if now+required >= work_end:
        raise RuntimeError('remaining full measurement set does not fit work deadline and cleanup/down reserve')
    return work_end


def validate_binding(profile):
    """A later live freeze must consume exactly the accepted held-out contract."""
    binding = profile['analysis']['s1_calibration']
    directory = Path(binding['directory'])
    check_root(directory, profile)
    for name, expected in binding['evidence_sha256'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or sha(directory/path) != expected:
            raise ValueError('calibration proof changed: '+name)
    summary = json.loads((directory/'summary.json').read_text())
    frozen = json.loads((directory/'candidate-freeze.json').read_text())
    candidate = json.loads((directory/'candidate-profile.json').read_text())
    if not summary['accepted'] or not summary['validation_baseline_passed'] or not summary['validation_sustained_passed']:
        raise ValueError('held-out validation did not pass')
    if profile['s1'] != candidate['s1'] or profile['s1']['slo_ms'] != frozen['slo_ms']:
        raise ValueError('S1 measurement differs from validated candidate')
    for name in ('kubernetes/graduation-s1/app.py','kubernetes/graduation-s1/loadgen.py',
                 'evaluation/fresh_baseline.py','evaluation/fresh_analysis.py',
                 'evaluation/fresh_contract.py','evaluation/fresh_calibration.py'):
        if sha(ROOT/name) != frozen['source_sha256'][name]:
            raise ValueError('validated measurement source changed: '+name)
    amendment = binding['amendment_path']
    if amendment not in profile['operations']['preregistered_documents'] or PROTOCOL not in profile['operations']['preregistered_documents'] or sha(ROOT/amendment) != binding['amendment_sha256']:
        raise ValueError('calibration amendment/document binding differs')
    for key in ('s2','s3','s4','v1_condition'):
        if profile[key] != candidate[key]:raise ValueError('unrelated workload changed during S1 calibration')
    required = {'summary.json','candidate-freeze.json','candidate-profile.json','registration.json',
                'validation-01/requests.jsonl','validation-02/requests.jsonl',
                'validation-01/metrics.json','validation-02/metrics.json'}
    if not required.issubset(binding['evidence_sha256']):raise ValueError('calibration proof incomplete')
    for i in (1,2):
        result = assess(rows(directory/f'validation-{i:02}'/'requests.jsonl'), profile['s1'])
        if not result['baseline_accepted'] or not result['sustained_accepted']:
            raise ValueError('validation raw does not satisfy S1 contract')


class Samplers:
    def __init__(self, s1, ev, pod, seconds=330):
        self.threads = []
        self.errors = []
        code = SAMPLER.replace('SECONDS',str(seconds))
        def run(name, callback):
            try:
                raw = callback()
                (ev.directory/(name+'.jsonl')).write_text(raw)
            except BaseException as exc:
                self.errors.append(name+': '+str(exc))
        for host in ('osk8s-compute01','osk8s-compute02'):
            callback = lambda host=host: LabRuntime(s1.client).remote('python3 -u -c '+shlex.quote(code), host=host, timeout=seconds+90)
            self.threads.append(threading.Thread(target=run, args=(host,callback), daemon=True))
        callback = lambda: s1.k('-n','graduation-s1','exec',pod,'--','python','-u','-c',code,timeout=seconds+90)
        self.threads.append(threading.Thread(target=run, args=('service-guest',callback), daemon=True))
    def start(self):
        for thread in self.threads: thread.start()
    def finish(self):
        for thread in self.threads: thread.join(420)
        if any(thread.is_alive() for thread in self.threads): self.errors.append('sampler did not finish')
        return self.errors


def normal_job(name, node):
    # This factory is shared with the main sampler. No S1Contention instance or
    # FreshS1/DEV adapter is constructed; no injection/action method is dispatched.
    from graduation_s1_contention import load_job
    job = load_job(name, node, 5, 100000, 300)
    job['metadata']['annotations'] = {'openstack-k8s.dev/purpose':'calibration-validation'}
    return job


def measure(s1, case, profile, ev):
    from graduation_s1 import NAMESPACE
    from workload_state import condition
    with s1.lock_path.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = s1.verify()
        nodes = s1.client.get('w','nodes')['items']
        control = [n for n in nodes if 'node-role.kubernetes.io/control-plane' in n['metadata'].get('labels',{}) and condition(n,'Ready')]
        if len(control) != 1: raise RuntimeError('one Ready control-plane required')
        source = next(w for w in case['placement']['workers'] if w['host'] == profile['source_compute'])
        dep = s1.obj('deployment','http')
        patch = [{'op':'test','path':'/metadata/uid','value':dep['metadata']['uid']},
                 {'op':'test','path':'/metadata/resourceVersion','value':dep['metadata']['resourceVersion']},
                 {'op':'add','path':'/spec/template/spec/nodeSelector','value':{'kubernetes.io/hostname':source['node']}}]
        s1.k('-n',NAMESPACE,'patch','deployment','http','--type=json','-p',json.dumps(patch))
        s1.k('-n',NAMESPACE,'rollout','status','deployment/http','--timeout=3m',timeout=200)
        before = s1.verify()
        if before['node'] != source['node'] or s1.placement(before['nova_id'])['compute_host'] != profile['source_compute']:
            raise RuntimeError('service source placement differs')
        atomic_json(ev.directory/'environment.json',dict(service=before, placement=case['placement'],
                    environment=s1.environment(), preparation=s1.read()))
        clock_check(ev,'before-stream',lambda:float(s1.k('-n',NAMESPACE,'exec',before['pod'],'--','python','-c','import time;print(time.time())').strip()),5,'service guest wall clock')
        sampler = Samplers(s1,ev,before['pod'])
        sampler.start()
        name = 's1-cal-'+uuid.uuid4().hex[:10]
        job = normal_job(name,control[0]['metadata']['name'])
        atomic_json(ev.directory/'job.json',job)
        # Persist intent before apply; label/name+namespace ownership recover a lost response.
        ev.event('normal_job_create_intent',target=name)
        uid = None
        try:
            s1.k('apply','-f','-',data=json.dumps(job))
            uid = s1.obj('job',name)['metadata']['uid']
            atomic_json(ev.directory/'job-identity.json',dict(name=name,uid=uid))
            s1.k('-n',NAMESPACE,'wait','--for=condition=ready','pod','-l','job-name='+name,'--timeout=45s',timeout=60)
            pods = s1.client.get('w','pods','-n',NAMESPACE,'-l','job-name='+name)['items']
            if len(pods) != 1 or pods[0]['spec']['nodeName'] != control[0]['metadata']['name']:
                raise RuntimeError('generator placement ambiguous')
            pod = pods[0]['metadata']['name']
            clock_check(ev,'stream-start',lambda:float(s1.k('-n',NAMESPACE,'exec',pod,'--','python','-c','import time;print(time.time())').strip()),5,'generator Pod wall clock')
            ev.event('normal_load_started',target=uid)
            s1.k('-n',NAMESPACE,'wait','--for=condition=complete','job/'+name,'--timeout=320s',timeout=335)
            clock_check(ev,'stream-end',lambda:float(s1.k('-n',NAMESPACE,'exec',before['pod'],'--','python','-c','import time;print(time.time())').strip()),5,'service guest wall clock')
            atomic_json(ev.directory/'probe-pods.json',s1.client.get('w','pods','-n',NAMESPACE,'-l','job-name='+name))
            after = s1.verify()
            atomic_json(ev.directory/'service-after.json',after)
            if any(before[k] != after[k] for k in ('pod_uid','node','nova_id','image_id','container_id','restart_count','service_uid')):
                raise RuntimeError('service identity changed during normal stream')
            if s1.placement(after['nova_id'])['compute_host'] != profile['source_compute']:
                raise RuntimeError('service compute changed')
        finally:
            try:
                (ev.directory/'requests.jsonl').write_text(s1.k('-n',NAMESPACE,'logs','job/'+name,timeout=30))
            finally:
                obj = s1.obj('job',name)
                if obj:
                    if obj['metadata'].get('annotations',{}).get('openstack-k8s.dev/purpose') != 'calibration-validation' or (uid and obj['metadata']['uid'] != uid):
                        raise RuntimeError('normal Job ownership changed')
                    s1.k('-n',NAMESPACE,'delete','job',name,'--wait=true','--timeout=60s',timeout=75)
                errors = sampler.finish()
                atomic_json(ev.directory/'sampler-status.json',dict(errors=errors))
        if errors: raise RuntimeError('normal observers incomplete: '+str(errors))
        ev.event('normal_load_completed')
        return rows(ev.directory/'requests.jsonl')


def run(directory):
    from fresh_live import LiveBackend
    from graduation_s1 import S1
    from workload_state import command
    profile, reg = check_registration(directory)
    directory = Path(directory)
    # Refuse automatic reruns. All partial/failed attempts remain in this directory.
    exclusive_json(directory/'execution.json',dict(started_utc=utc(),status='started',primary_sample_count=0))
    backend = LiveBackend(directory)
    backend.require_clean_state()
    with (backend.state/'graduation-environment.lock').open('a+') as env_lock:
        fcntl.flock(env_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    before = json.loads(command(['gcloud','compute','instances','list','--project='+profile['project'],'--format=json(name,id,status,machineType)']))
    selected = {h['name']:h for h in before if h['name'] in profile['hosts']}
    atomic_json(directory/'hosts-before.json',selected)
    if set(selected) != set(profile['hosts']) or any(h['status'] != 'TERMINATED' or h['machineType'].split('/')[-1] != profile['hosts'][n] for n,h in selected.items()):
        raise RuntimeError('cold calibration requires exact registered stopped hosts')
    BedLedger(profile).gate(7200)
    started = time.time()
    work_end = admission(started,5)
    atomic_json(directory/'budget.json',dict(started_utc=utc(started),work_end_utc=utc(work_end),
                cleanup_end_utc=utc(started+5400),hard_end_utc=utc(started+7200),rule=RULE))
    ev = Evidence(directory/'fixture')
    helper = backend.helper(profile,ev)
    case = dict(id='s1-normal-fixture',scenario='s1',purpose='calibration',mode='normal-only')
    helper.data['cases'] = [case]
    error = None
    candidate = None
    measurements = []
    ensure_started = False
    try:
        ensure_started = True
        with phase('calibration cold ensure',900,directory/'phases.jsonl',work_end-2160):
            backend.environment_action(profile,'ensure')
        with phase('calibration initial workers',600,directory/'phases.jsonl',work_end-2160):
            record = json.loads((backend.state/'graduation-environment.json').read_text())
            helper.verify_ready_environment(record)
            case['environment_run_id'] = record['run_id']
            helper.prepare_workers(case)
            # Persist placement/worker ownership before any app preparation.
            helper.save()
        for number in range(5):
            check_registration(directory)
            admission(started,5-number)
            purpose = 'calibration' if number < 3 else 'validation'
            if purpose == 'validation':
                frozen = json.loads((directory/'candidate-freeze.json').read_text())
                if sha(directory/'candidate-profile.json') != frozen['profile_sha256'] or sha(directory/'candidate-freeze.json') != (directory/'candidate-freeze.sha256').read_text().strip():
                    raise ValueError('candidate freeze changed')
                if frozen['source_sha256'] != source_hashes():raise ValueError('candidate source changed')
            runid = f'{purpose}-{number+1 if number<3 else number-2:02}'
            sample_ev = Evidence(directory/runid)
            append(directory/'attempts.jsonl',dict(run=runid,purpose=purpose,state='started',utc=utc(),injection=False,primary_sample_count=0))
            print(utc()+' '+runid+' preparing normal stream',flush=True)
            with phase(runid,420,directory/'phases.jsonl',work_end):
                s1 = S1()
                if s1.read() and s1.read().get('phase') != 'restored':s1.cleanup()
                s1.prepare()
                requests = measure(s1,case,profile,sample_ev)
                check_registration(directory)
                cfg = {**profile['s1'],'slo_ms':candidate['slo_ms'] if candidate else 200}
                result = assess(requests,cfg)
                result['old_200ms'] = assess(requests,{**cfg,'slo_ms':200})
                atomic_json(sample_ev.directory/'metrics.json',result)
                if not result['data_valid'] or not result['no_failures']:
                    raise RuntimeError(runid+' invalid or request failures; no automatic retries')
                measurements.append(result)
                append(directory/'attempts.jsonl',dict(run=runid,purpose=purpose,state='completed',utc=utc(),baseline=result['baseline_accepted'],sustained=result['sustained_accepted'],raw_sha256=sha(sample_ev.directory/'requests.jsonl')))
            print(utc()+' '+runid+' completed',flush=True)
            if number == 2:
                candidate = choose(measurements)
                for n in range(3):
                    trial = assess(rows(directory/f'calibration-{n+1:02}'/'requests.jsonl'),{**profile['s1'],'slo_ms':candidate['slo_ms']})
                    if not trial['sustained_accepted']:raise RuntimeError('candidate does not satisfy calibration bins')
                new_profile = copy.deepcopy(profile)
                new_profile['s1']['slo_ms'] = candidate['slo_ms']
                new_profile['observed_environment'].update(observed_utc=utc(),
                    evidence_directory=str(ev.directory),host_identity=helper.data['host_identity'],
                    flavors=helper.data['flavors'])
                exclusive_json(directory/'candidate-profile.json',new_profile)
                exclusive_json(directory/'candidate-freeze.json',dict(**candidate,frozen_utc=utc(),profile_sha256=sha(directory/'candidate-profile.json'),source_sha256=reg['source_sha256'],protocol_sha256=reg['protocol_sha256'],calibration_raw_sha256=[sha(directory/f'calibration-{n+1:02}'/'requests.jsonl') for n in range(3)]))
                (directory/'candidate-freeze.sha256').write_text(sha(directory/'candidate-freeze.json')+'\n')
                print(utc()+f" candidate frozen {candidate['slo_ms']} ms",flush=True)
    except BaseException as exc:
        error = type(exc).__name__+': '+str(exc)
        append(directory/'attempts.jsonl',dict(state='interrupted',utc=utc(),error=error))
        print(error,flush=True)
    finally:
        cleanup_error = None
        try:
            # Safety cleanup continues after work budget; never abandon resources
            # merely to satisfy an elapsed-time target.
            with phase('normal fixture cleanup',1800,directory/'phases.jsonl'):
                helper.cleanup_case(case)
                atomic_json(directory/'cleanup.json',json.loads((ev.directory/'cases'/case['id']/'cleanup-verification.json').read_text()))
        except BaseException as exc:
            cleanup_error = str(exc)
            atomic_json(directory/'cleanup-error.json',dict(error=cleanup_error,utc=utc()))
        if ensure_started:
            try:
                with phase('normal host down',1800,directory/'phases.jsonl'):
                    backend.environment_action(profile,'down')
                hosts = json.loads(command(['gcloud','compute','instances','list','--project='+profile['project'],'--format=json(name,id,status,machineType)']))
                atomic_json(directory/'hosts-final.json',{h['name']:h for h in hosts if h['name'] in profile['hosts']})
            except BaseException as exc:
                atomic_json(directory/'down-error.json',dict(error=str(exc),utc=utc()))
                cleanup_error = (cleanup_error or '')+'; down: '+str(exc)
        passed = len(measurements)==5 and all(a['baseline_accepted'] and a['sustained_accepted'] for a in measurements[3:]) and not error and not cleanup_error
        summary = dict(completed_utc=utc(),accepted=passed,error=error,cleanup_error=cleanup_error,
                       normal_runs_completed=len(measurements),candidate=candidate,primary_sample_count=0,
                       validation_baseline_passed=len(measurements)==5 and all(a['baseline_accepted'] for a in measurements[3:]),
                       validation_sustained_passed=len(measurements)==5 and all(a['sustained_accepted'] for a in measurements[3:]),
                       elapsed_seconds=time.time()-started,bed_usage=BedLedger(profile).usage())
        atomic_json(directory/'summary.json',summary)
        print(json.dumps({k:v for k,v in summary.items() if k!='candidate'},ensure_ascii=False),flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['register','run'])
    parser.add_argument('--directory',required=True)
    parser.add_argument('--profile')
    args = parser.parse_args()
    if args.action == 'register':print(register(args.directory,args.profile))
    else:run(args.directory)


if __name__ == '__main__':main()
