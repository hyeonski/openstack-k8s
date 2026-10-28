"""Fresh scenario adapters: reuse fixed policies and owned fixture primitives."""
from __future__ import annotations

import argparse
import copy
import concurrent.futures
from contextlib import contextmanager
import os
import hashlib
import json
from pathlib import Path
import shlex
import sys
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/d) for d in ('scripts','experiments')]
from lib.state import atomic_json, utc_now
from graduation_evaluation_case import EvaluationS1, EvaluationS2, EvaluationS3, EvaluationS4Preparation
from graduation_s1_auto import interval
from graduation_s1_contention import epoch
from graduation_s1 import NAMESPACE as S1_NS
from graduation_s3 import SKIP, OUT
from graduation_s4 import MHC_NAME, HTTP_NAME, NAMESPACE as S4_NS, LABEL_KEY, EXPERIMENT
from graduation_s4_run import S4Run, nova, nova_status, summarize_capacity
from graduation_recovery import RecoveryLab, wait_for
from workload_state import condition
from fresh_evidence import Evidence, OpenLoopProbe, append, clock_check, utc
from fresh_contract import digest
from fresh_baseline import baseline_gate
from fresh_collection import durable_host_stat, remote_file, preserve_s1_partial, checkpoint_text


def fixture_ready(ev):
    """End the shared fixture deadline only when the probe fixture is ready."""
    import signal
    signal.setitimer(signal.ITIMER_REAL, 0)
    ev.state('PREPARED');ev.state('BASELINE')


def injection_guard(profile, needed, environment):
    ops=profile['operations']
    now = time.time()
    from fresh_host_lifetime import time_targets_only
    targets=time_targets_only(profile)
    if not targets and now >= epoch(ops['last_injection_utc']):
        raise RuntimeError('registered last injection time passed')
    if not targets and (now+needed >= epoch(ops['drain_utc']) or now+needed+ops['cleanup_seconds'] >= epoch(ops['shutdown_start_utc'])):
        raise RuntimeError('injection cannot complete H/evidence and cleanup before drain/down')
    hosts = environment.get('final_hosts', {})
    if not hosts:
        raise RuntimeError('host auto-stop evidence unavailable before injection')
    from fresh_host_lifetime import effective_host_deadline
    deadlines=[effective_host_deadline(profile,host) for host in hosts.values()]
    finite=[d for d in deadlines if d is not None]
    if finite and min(finite) - now < needed + ops['cleanup_seconds'] + ops['host_shutdown_timeout_seconds']:
        raise RuntimeError('host auto-stop headroom no longer covers H and cleanup')


def horizon(ev, start, seconds):
    # UTC may slew relative to monotonic time. Meet BOTH registered clocks;
    # never relax the analyser or repair an already recorded early end.
    events=[json.loads(line) for line in (ev.directory/'events.jsonl').read_text().splitlines()]
    injected=[e for e in events if e['kind']=='injection_applied']
    if len(injected)!=1:raise RuntimeError('one actual injection event required before horizon wait')
    wall_end=epoch(injected[0]['utc'])+seconds
    while True:
        remaining=max(start+seconds-time.monotonic(),wall_end-time.time())
        if remaining<=0:break
        time.sleep(remaining+.05)
    ev.event('horizon_end');ev.state('HORIZON_END')


def remote_tail_seconds(cfg):
    return cfg['max_clock_offset_seconds']+cfg['deadline_seconds']+3


class FreshS1(EvaluationS1):
    def __init__(self, case, profile, ev):
        self.case,self.profile,self.ev=case,profile,ev
        super().__init__('no-action' if case['mode']=='M' else 'automatic')
        self.raw={}

    def write(self,record,phase,**values):
        record['fresh_attempt']=str(self.ev.directory.resolve())
        return super().write(record,phase,**values)

    def run_locked(self,record,probe_node):
        original = self.s1.host_stat
        original_k = self.s1.k
        sequence = 0
        def collect(host):
            nonlocal sequence
            sequence += 1
            from lib.runtime import LabRuntime
            return durable_host_stat(self.ev, LabRuntime(self.client), host, sequence)
        self.s1.host_stat = collect
        def query(*args, **kwargs):
            result = original_k(*args, **kwargs)
            if 'logs' in args and 'job/'+record.get('job_name','') in args:
                checkpoint_text(self.ev.directory/'requests-checkpoint.jsonl', result)
            return result
        self.s1.k = query
        try:
            return super().run_locked(record,probe_node)
        finally:
            self.s1.host_stat = original
            self.s1.k = original_k

    def wait_probe_samples(self,job_name):
        result=super().wait_probe_samples(job_name)
        fixture_ready(self.ev)
        return result

    def event(self,record,item):
        result=super().event(record,item)
        if item.get('kind')=='diagnosis' and item.get('trigger') and not record.get('fresh_symptom_detected'):
            record['fresh_symptom_detected']=True
            self.ev.event('symptom_detected',target=record['service_before']['pod_uid'])
        return result

    def check_clock(self,record,phase):
        pods=self.client.get('w','pods','-n',S1_NS,'-l','job-name='+record['job_name'])['items']
        if len(pods)!=1:raise RuntimeError('ambiguous S1 generator clock origin')
        return clock_check(self.ev,phase,lambda:float(self.s1.k('-n',S1_NS,'exec',pods[0]['metadata']['name'],'--','python','-c','import time; print(time.time())').strip()),self.profile['s1']['max_clock_offset_seconds'],'loadgen Pod wall clock; diagnostic subprocess')

    def create_competitor(self, record):
        def collect():
            text=self.s1.k('-n',S1_NS,'logs','job/'+record['job_name'],timeout=10)
            return [json.loads(line) for line in text.splitlines() if line]
        end=epoch(record['baseline_end_at'])
        baseline_gate(self.ev,{**self.profile['s1'],**(self.profile['v1_condition'] if self.case['mode']=='V1' else {})},collect,source='loadgen job first registered arrivals',policy_window={'interval_utc':[utc(end-60),utc(end)],'existing_wait_seconds':90})
        self.check_clock(record,'before-injection')
        injection_guard(self.profile,self.profile['s1']['horizon_seconds'],self.s1.environment())
        before=self.s1.verify()
        self.raw.update(service_before=before,node_before=self.s1.obj('node',before['node'],None),
                        vm_before=self.server(before['nova_id']),compute_before=record['service_compute_host'],
                        source_compute=record['service_compute_host'])
        self.ev.event('injection_requested',target=record['service_compute_host'])
        result=super().create_competitor(record)
        self.ev.event('injection_applied',target=record['service_compute_host'],source_file='raw/run.json',source_field='stress_observed_at')
        self.start=time.monotonic()
        self.ev.state('INJECTED');self.ev.state('OBSERVING')
        if epoch(record['sampling_started_at']) + record['seconds'] < time.time()+self.profile['s1']['horizon_seconds']+30:
            raise RuntimeError('S1 load duration cannot cover registered H after injection provisioning')
        return result

    def observe_contention(self, record, *args):
        try:
            result=super().observe_contention(record,*args)
            self.ev.event('diagnosis_completed',target=record['service_before']['pod_uid'])
            return result
        except RuntimeError as exc:
            if record.get('phase')!='deferred' or record.get('defer_reason')!='sustained_service_and_host_evidence_missing':
                raise
            # An ordinary policy defer is an observed negative-control outcome; unexpected exceptions still abort.
            self.ev.event('policy_deferred',reason=record['defer_reason'])
            return self.s1.cpu_stat(record['service_before']['pod']),args[-1]('policy-deferred')

    def check_source_placement(self,record,place):
        if place['compute_host']!=record['service_compute_host']:
            raise RuntimeError('source placement changed')

    def move_service(self, record):
        if self.case['mode']=='M':
            return EvaluationS1.move_service(self,record)
        if not record.get('automatic_trigger'):
            self.write(record,'control-policy-deferred',action_count=0)
            self.ev.event('policy_held',reason=record.get('defer_reason'))
            return
        if getattr(self,'start',None) is not None and time.monotonic()>=self.start+self.profile['s1']['horizon_seconds']:
            self.write(record,'control-policy-deferred',action_count=0)
            self.ev.event('policy_held',reason='observation horizon ended')
            return
        self.ev.event('action_requested',target=record['service_before']['pod_uid'],actor='policy')
        if self.case['mode'] in ('P','V1'):
            result=super().move_service(record)
        else:
            before=self.s1.verify()
            identity=('pod_uid','node','nova_id','image_id','container_id','restart_count','machine_uid','service_uid')
            if any(before.get(k)!=record['service_before'].get(k) for k in identity):
                raise RuntimeError('same-worker restart source changed')
            dep=self.s1.obj('deployment','http')
            selector=dep['spec']['template']['spec'].get('nodeSelector',{})
            if selector.get('kubernetes.io/hostname')!=before['node']:
                raise RuntimeError('same-worker restart requires existing exact node selector')
            annotations=dep['spec']['template']['metadata'].get('annotations',{})
            patch=[{'op':'test','path':'/metadata/uid','value':dep['metadata']['uid']},
                   {'op':'test','path':'/metadata/resourceVersion','value':dep['metadata']['resourceVersion']},
                   {'op':'add','path':'/spec/template/metadata/annotations','value':{**annotations,'openstack-k8s.dev/evaluation-restart':record['run_id']}}]
            self.write(record,'same-worker-restart-intent',action_count=1)
            result=self.s1.k('-n',S1_NS,'patch','deployment','http','--type=json','-p',json.dumps(patch))
        # Read back the owned template after an acknowledged mutation. A lost response aborts to cleanup without replay.
        observed=self.s1.obj('deployment','http')
        atomic_json(self.ev.directory/'observations/action-deployment.json',observed)
        self.ev.event('action_applied',target=record['service_before']['pod_uid'],actor='policy',meaning='acknowledged deployment mutation plus template snapshot; Pod identity verified separately')
        return result

    def verify_intervention(self,record,moved):
        if not record.get('action_count'):
            original=self.mode
            try:
                self.mode='no-action'
                return super().verify_intervention(record,moved)
            finally:self.mode=original
        if self.case['mode']!='A':return super().verify_intervention(record,moved)
        b=record['service_before']
        if b['pod_uid']==moved['pod_uid'] or any(b[k]!=moved[k] for k in ('node','nova_id','image_id')):
            raise RuntimeError('same-worker restart identity violation')
        if self.s1.placement(moved['nova_id'])['compute_host']!=self.raw['compute_before']:
            raise RuntimeError('same-worker restart moved compute')

    def observe_recovery(self,record,job):
        # Recovery does not shorten H. The final load log is judged independently.
        horizon(self.ev,self.start,self.profile['s1']['horizon_seconds'])
        self.check_clock(record,'horizon-end')
        self.write(record,'fresh-horizon-ended')
        record['stabilization_windows']=[{'start':utc_now(),'end':utc_now()}]

    def recovery_window_start(self,record):
        return epoch(record['baseline_end_at'])

    def recovery_checks(self,record,rows,baseline):
        return {'fresh_independent_judgement_required':True}

    @contextmanager
    def transport_reads(self):
        from fresh_transport import retry_read, transport_lock, listener_reachable
        original_k, original_client_k = self.s1.k, self.client.k
        from workload_state import command
        def invoke_client(plane, values, *, data=None, timeout=30):
            config = 'management' if plane == 'm' else self.client.cluster
            return command(['kubectl', '--kubeconfig', self.client.state/'kubeconfigs'/(config+'.yaml'),
                '--request-timeout=15s', *values], data=data, timeout=self.client.remaining(min(30, timeout)))

        def identity(remaining):
            record = self.read()
            if not record or record.get('fresh_attempt') != str(self.ev.directory.resolve()):
                raise RuntimeError('transport read identity not owned by current attempt')
            job = None
            if record.get('job_uid'):
                raw = original_k('get', 'job', record['job_name'], '-n', S1_NS,
                                 '--ignore-not-found', '-o', 'json', timeout=min(20, remaining()))
                job = json.loads(raw) if raw.strip() else None
                if job and job['metadata']['uid'] != record['job_uid']:
                    raise RuntimeError('transport read Job UID changed; refusing continuation')
                if not job and record.get('phase') != 'completed':
                    raise RuntimeError('transport read Job disappeared before acknowledged cleanup')
            if not job:
                preparation = self.s1.read()
                if not preparation or preparation.get('run_id') != record.get('preparation_id') or preparation.get('environment_run_id') != record.get('environment_run_id'):
                    raise RuntimeError('transport read preparation identity changed')
                obj = json.loads(invoke_client('m', ['get', 'cluster', self.client.cluster,
                                 '-n', self.client.ns, '-o', 'json'], timeout=min(20, remaining())))
                if obj['metadata']['uid'] != preparation.get('cluster_uid'):
                    raise RuntimeError('transport read cluster UID changed; refusing continuation')
                after = record.get('service_after')
                if record.get('phase') == 'completed' and after:
                    pod = json.loads(original_k('get', 'pod', after['pod'], '-n', S1_NS,
                                     '-o', 'json', timeout=min(20, remaining())))
                    if pod['metadata']['uid'] != after['pod_uid']:
                        raise RuntimeError('transport read final service Pod UID changed')
            remaining()

        def reconnect(remaining):
            with transport_lock(self.client.state, remaining):
                if listener_reachable(os.environ['WORKLOAD_LOCAL_API_PORT']):
                    return
                saved = self.client.state/'workload-api-iap-tunnel.log'
                if saved.exists():
                    checkpoint_text(self.ev.directory/('transport-read-before-'+str(time.time_ns())+'.log'),saved.read_text())
                log = self.ev.directory/'transport-read-reconnect.log'
                with log.open('a') as stream:
                    repaired = subprocess.run([str(ROOT/'scripts/gcp-workload-api-tunnel.sh'), 'ensure'],
                        stdout=stream, stderr=subprocess.STDOUT,
                        timeout=min(60, remaining()))
                if repaired.returncode:
                    raise RuntimeError('transport reconnect failed: '+log.read_text()[-4000:])
                remaining()

        def query(*args, data=None, timeout=60):
            def invoke(values, *, data, timeout):
                return original_k(*values, data=data, timeout=timeout)
            return retry_read(invoke, args, data=data, timeout=timeout,
                identity=identity, reconnect=reconnect, evidence=self.ev.directory)

        def client_query(plane, *args, data=None):
            if plane != 'w':
                return original_client_k(plane, *args, data=data)
            def invoke(values, *, data, timeout):
                return invoke_client(plane, values, data=data, timeout=timeout)
            return retry_read(invoke, args, data=data, timeout=self.client.remaining(30),
                identity=identity, reconnect=reconnect, evidence=self.ev.directory)

        self.s1.k, self.client.k = query, client_query
        try:
            yield
        finally:
            self.s1.k, self.client.k = original_k, original_client_k

    def finish(self):
        with self.transport_reads():
            return self.finish_once()

    def finish_once(self):
        cfg=self.profile['s1']
        if self.case['mode']=='V1':
            selected=self.profile['v1_selected']
            if set(selected)!={'cpu_workers','workload_rounds'} or selected['cpu_workers']!=4:
                raise ValueError('current stress fixture supports exactly cpu_workers=4; register a supported candidate')
            rounds=selected['workload_rounds']
        else:rounds=cfg['rounds']
        error = None
        try:
            self.run(rate=cfg['rate'],rounds=rounds,seconds=cfg['seconds'])
            record=self.read();source=record['service_before']
            self.raw['application_image_ids']={'http':record['service_before']['image_id']}
            current=self.s1.verify()
            self.raw.update(service_after=current,service_after_action=record['service_after'],node_after=self.s1.obj('node',source['node'],None),
                            vm_after=self.server(source['nova_id']),compute_after=self.s1.placement(current['nova_id'])['compute_host'],
                            contender_after=json.loads((Path(record['evidence'])/'contender-after.json').read_text()))
            samples=json.loads((Path(record['evidence'])/'hosts-stress-start.json').read_text())
            end=json.loads((Path(record['evidence'])/'hosts-post-relocation.json').read_text())
            self.raw['host_metrics']=interval(samples[self.raw['source_compute']],end[self.raw['source_compute']])
            completion_start=json.loads((Path(record['evidence'])/'hosts-completion-start.json').read_text())
            completion_end=json.loads((Path(record['evidence'])/'hosts-completion-end.json').read_text())
            self.raw['completion_host_metrics']=interval(completion_start[self.raw['source_compute']],completion_end[self.raw['source_compute']])
            self.raw['provenance']={'file':'raw/run.json','fields':['service_before','service_after'],'transform':'fresh-S1 identity snapshots; host interval from raw/hosts-*.json'}
            if self.case['mode']=='V1':
                end=epoch(record['baseline_end_at'])
                self.raw['baseline_interval_utc']=[utc(end-60),utc(end)]
                source_rows=[json.loads(line) for line in (Path(record['evidence'])/'http.jsonl').read_text().splitlines() if line]
                baseline=[row for row in source_rows if end-60<=epoch(row['time'])<end]
                (self.ev.directory/'baseline-requests.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in baseline))
                decisions=[json.loads(line) for line in (Path(record['evidence'])/'decisions.jsonl').read_text().splitlines() if line]
                self.raw['policy_windows_utc']=[[d['window']['start'],d['window']['end']] for d in decisions if d.get('kind')=='diagnosis']
            atomic_json(self.ev.directory/'observations/contract.json',self.raw)
            # Source loadgen contains canonical arrivals as well as legacy fields.
            (self.ev.directory/'requests.jsonl').write_bytes((Path(record['evidence'])/'http.jsonl').read_bytes())
            (self.ev.directory/'decisions.jsonl').write_bytes((Path(record['evidence'])/'decisions.jsonl').read_bytes())
        except BaseException as exc:
            error = exc
            raise
        finally:
            preserve_s1_partial(self.ev, self.read(), self.raw, error)



def restore_mhc(lab, ownership, ev):
    before=ownership['before']
    current=lab.obj('machinehealthcheck',MHC_NAME,plane='m')
    if current['metadata']['uid']!=before['metadata']['uid']:
        raise RuntimeError('MHC identity changed; cannot restore')
    original=before['metadata'].get('annotations',{})
    expected={**original,'cluster.x-k8s.io/paused':'true','openstack-k8s.dev/fresh-owner':ownership['owner']}
    present=current['metadata'].get('annotations',{})
    if present not in (original,expected) or current['spec']!=before['spec']:
        raise RuntimeError('MHC changed outside this attempt')
    if present!=original:
        lab.k('patch','machinehealthcheck',MHC_NAME,'-n',lab.client.ns,'--type=json','-p',json.dumps([
            {'op':'test','path':'/metadata/uid','value':before['metadata']['uid']},
            {'op':'test','path':'/metadata/resourceVersion','value':current['metadata']['resourceVersion']},
            {'op':'add','path':'/metadata/annotations','value':original}]),plane='m')
    restored=lab.obj('machinehealthcheck',MHC_NAME,plane='m')
    atomic_json(ev.directory/'mhc-restored.json',restored)
    if restored['metadata']['uid']!=before['metadata']['uid'] or restored['spec']!=before['spec'] or restored['metadata'].get('annotations',{})!=original:
        raise RuntimeError('MHC restore readback differs from original')
    return restored


class RemoteProbe:
    def __init__(self,runner,command,raw_path,stop_path,seconds):
        self.runner,self.command,self.raw_path,self.stop_path,self.seconds=runner,command,raw_path,stop_path,seconds

    def __enter__(self):
        import concurrent.futures
        self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.future=self.pool.submit(self.runner.remote,self.command,timeout=self.seconds+60)
        try:
            wait_for(lambda:self.runner.remote('if sudo test -s '+shlex.quote(self.raw_path)+'; then echo ready; fi').strip()=='ready',seconds=60,interval=1)
        except BaseException:
            self.__exit__(None,None,None)
            raise
        return self

    def __exit__(self,*_):
        try:
            self.runner.remote('sudo touch '+shlex.quote(self.stop_path))
            self.future.result(timeout=30)
        finally:
            self.pool.shutdown(wait=False,cancel_futures=True)
            for source,destination in ((self.raw_path,'requests.jsonl'),(self.raw_path+'.progress','uploader-progress.jsonl')):
                try:
                    remote_file(self.runner.ev, self.runner.remote, source, destination)
                except Exception as exc:
                    self.runner.ev.event('evidence_capture_error',source=source,detail=str(exc))


class FreshOwnedLab:
    def write(self,phase,**values):
        self.record['fresh_attempt']=str(self.ev.directory.resolve())
        return super().write(phase,**values)


class FreshS2(FreshOwnedLab, EvaluationS2):
    def __init__(self,case,profile,ev):
        super().__init__('fixed-first')
        self.case,self.profile,self.ev=case,profile,ev

    def check_clock(self,phase):
        return clock_check(self.ev,phase,lambda:float(self.remote("python3 -c 'import time; print(time.time())'").strip()),self.profile['s2']['max_clock_offset_seconds'],'receiver host wall clock; network namespace shares this clock')

    def set_rate(self,rate):
        result=super().set_rate(rate)
        atomic_json(self.ev.directory/'observations'/('qos-'+str(time.monotonic_ns())+'.json'),
                    {'utc':utc_now(),'port':self.admin_json('port','show',self.record['workers'][1]['port']['id']),
                     'rule':self.admin_json('network','qos','rule','show',self.record['policy_id'],self.record['rule_id'])})
        return result

    def diagnostic_snapshot(self):
        return {'utc':utc_now(),'monotonic':time.monotonic(),'clock_id':self.ev.clock_id,
                'hosts':{w['host']:self.runtime.host_stat(w['host']) for w in self.record['workers']},
                'qdisc':json.loads(self.remote('sudo tc -s -j qdisc show dev s2-egress'))[0]}

    @staticmethod
    def contention_diagnosis(base,metric,before,after):
        from graduation_s2 import impacted
        from lib.runtime import host_cpu_utilization
        elapsed=after['monotonic']-before['monotonic']
        cpu={h:host_cpu_utilization(before['hosts'][h],after['hosts'][h]) for h in before['hosts']}
        egress=(after['qdisc']['bytes']-before['qdisc']['bytes'])*8/elapsed if elapsed>0 else 0
        overlimits=after['qdisc']['overlimits']-before['qdisc']['overlimits']
        return {'trigger':impacted(base,metric) and egress>=16_000_000 and overlimits>0 and metric['upload_bytes']>0 and bool(cpu) and max(cpu.values())<.7,
                'egress_bps':egress,'overlimits':overlimits,'cpu_utilization':cpu}

    def split_if_enabled(self,a,b,current):
        if self.case['mode']!='P':
            return False
        self.ev.event('action_requested',target=b['port']['id'],actor='policy')
        self.set_rate(current)
        self.k('-n',self.ns,'patch','deployment','upload','--type=merge','-p',json.dumps({'spec':{'template':{'spec':{'nodeSelector':{'kubernetes.io/hostname':b['node']}}}}}))
        wait_for(lambda:self.ready('upload',b['node']))
        old=self.pods('upload')
        if len(old)!=1 or old[0]['spec']['nodeName']!=b['node']:
            raise RuntimeError('uploader relocation readback failed')
        self.ev.event('action_applied',target=b['port']['id'],actor='policy')
        return True

    def finish(self):
        import concurrent.futures
        from graduation_s2 import next_rate, stable, impacted
        workers=self.start()
        try:
            a, b = workers
            # Only node agents/system components may share the controlled worker.
            other = [p['metadata']['name'] for p in self.client.get('w', 'pods', '-A')['items']
                     if p['spec'].get('nodeName') == b['node'] and p['metadata']['namespace'] != 'kube-system'
                     and p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')
                     and not any(o['kind'] == 'DaemonSet' for o in p['metadata'].get('ownerReferences', []))]
            if other or b['port'].get('qos_policy_id'):
                raise RuntimeError('destination port is shared or has a preexisting QoS policy')
            extensions = self.admin_json('extension', 'list', '--network')
            if not any(e.get('Alias') == 'qos' for e in extensions):
                raise RuntimeError('Neutron QoS is not enabled')
            run = self.record['run_id']
            # Remote files contain source only, never cloud credentials.
            self.remote('sudo tee /opt/openstack-k8s/graduation-s2-workload.py >/dev/null',
                        data=(ROOT / 'kubernetes/graduation-s2/workload.py').read_text())
            self.remote('sudo tee /opt/openstack-k8s/graduation-s2-network.sh >/dev/null',
                        data=(ROOT / 'experiments/graduation-s2-network.sh').read_text())
            self.write('network-create-intent', network_attempted=True)
            self.remote('sudo bash /opt/openstack-k8s/graduation-s2-network.sh prepare ' + run)
            self.write('network-ready')
            sg = self.admin_json('security', 'group', 'create', '--project', a['project_id'], run)
            self.write('security-group-created', security_group_id=sg['id'])
            self.admin('security', 'group', 'rule', 'create', '--protocol', 'tcp', '--dst-port', '30080',
                       '--remote-ip', '198.18.0.2/32', sg['id'])
            # OSC appends these groups to the current set; repeating existing IDs is rejected.
            self.admin('port', 'set', '--security-group', sg['id'], a['port']['id'])
            updated_port = self.admin_json('port', 'show', a['port']['id'])
            if set(updated_port['security_group_ids']) != set(a['port']['security_group_ids']) | {sg['id']}:
                raise RuntimeError('source port security groups were not preserved')
            fip = self.admin_json('floating', 'ip', 'create', '--project', a['project_id'],
                                  '--description', run, '--port', a['port']['id'], 'public')
            self.write('fip-created', fip=fip)
            policy = self.admin_json('network', 'qos', 'policy', 'create', '--project', b['project_id'], run)
            self.write('policy-created', policy_id=policy['id'])
            rule = self.admin_json('network', 'qos', 'rule', 'create', '--type', 'bandwidth-limit',
                                   '--max-kbps', '6000', '--max-burst-kbits', '600', '--egress', policy['id'])
            self.write('rule-created', rule_id=rule['id'])
            self.apply({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'code', 'namespace': self.ns},
                        'data': {'workload.py': (ROOT / 'kubernetes/graduation-s2/workload.py').read_text()}})
            self.apply(self.deployment('api', a['node'], ['api']))
            self.apply({'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': 'api', 'namespace': self.ns},
                        'spec': {'type': 'NodePort', 'externalTrafficPolicy': 'Local', 'selector': {'app': 'api'},
                                 'ports': [{'port': 8080, 'targetPort': 8080, 'nodePort': 30080}]}})
            wait_for(lambda: self.ready('api', a['node']))
            fixture_ready(self.ev)
            baseline = self.window('baseline')
            sample=json.loads((Path(self.record['evidence'])/'baseline.json').read_text())
            baseline_gate(self.ev,self.profile['s2'],lambda:sample['rows'],wait=False,source='raw/baseline.json rows; registered external receiver stream')
            if not baseline['complete'] or baseline['failures'] or not baseline['p95_ms']:
                raise RuntimeError('invalid S2 baseline')
            base = baseline['p95_ms']
            self.write('baseline-ready', api_before=self.pods('api')[0])
            cfg=self.profile['s2']
            initial_progress=json.loads(self.remote('curl -fsS http://198.18.0.2:8090/progress'))
            initial=dict(progress=initial_progress,port=self.admin_json('port','show',b['port']['id']),
                         api_node=a['node'],upload_node=a['node'],api_uid=self.pods('api')[0]['metadata']['uid'],
                         api_image_id=self.pods('api')[0]['status']['containerStatuses'][0]['imageID'],source_port=self.admin_json('port','show',a['port']['id']))
            if initial_progress['bytes']!=0 or initial_progress['next']!=0:
                raise RuntimeError('fresh uploader progress must begin at zero')
            raw_path='/var/lib/openstack-k8s-graduation/'+self.record['run_id']+'/fresh-api.jsonl'
            stop_path=raw_path+'.stop'
            progress_path=raw_path+'.progress'
            cmd=shlex.join(['sudo','ip','netns','exec','osk8s-s2','python3','/opt/openstack-k8s/graduation-s2-workload.py','probe','--url',
                            'http://'+self.record['fip']['floating_ip_address']+':30080','--seconds',str(cfg['horizon_seconds']+600),'--stop-file',stop_path,'--progress-file',progress_path,'--rate',str(cfg['rate'])])
            windows=[];current=6000;split=False;next_decision=0;rate_steps=0;rate_locked=False
            previous=initial_progress
            with RemoteProbe(self,"sudo bash -o pipefail -c "+shlex.quote(cmd+' | sudo tee '+shlex.quote(raw_path)+' >/dev/null'),raw_path,stop_path,cfg['horizon_seconds']+600):
                self.check_clock('before-injection')
                injection_guard(self.profile,cfg['horizon_seconds']+remote_tail_seconds(cfg),self.runtime.environment())
                self.ev.event('injection_requested',target=a['port']['id'])
                self.apply(self.deployment('upload',a['node'],['upload','--url','http://198.18.0.2:8090','--seconds',str(cfg['uploader_seconds'])]))
                wait_for(lambda:self.ready('upload',a['node']))
                injection=self.ev.event('injection_applied',target=a['port']['id'],meaning='uploader Ready; congestion independently observed')
                self.ev.state('INJECTED');self.ev.state('OBSERVING')
                start=time.monotonic()
                previous=json.loads(self.remote('curl -fsS http://198.18.0.2:8090/progress'))
                next_decision=start+60;diagnosed=False;detected=False
                diagnostic_before=self.diagnostic_snapshot();diagnostic_progress=previous;consecutive=0
                while time.monotonic()<start+cfg['horizon_seconds']:
                    time.sleep(min(10,max(0,start+cfg['horizon_seconds']-time.monotonic())))
                    progress=json.loads(self.remote('curl -fsS http://198.18.0.2:8090/progress'))
                    windows.append(dict(time=utc_now(),before=previous,after=progress));previous=progress
                    if time.monotonic()>=next_decision:
                        text=self.remote('sudo cat '+shlex.quote(raw_path))
                        checkpoint_text(self.ev.directory/'requests-checkpoint.jsonl',text)
                        samples=[json.loads(l) for l in text.splitlines() if l]
                        tail=[r for r in samples if r['time']>=time.time()-60]
                        from lib.runtime import percentile
                        metric=dict(complete=len(tail)>=cfg['rate']*54,failures=sum(not r['ok'] for r in tail),
                                    p95_ms=percentile([r['latency_ms'] for r in tail if r['ok']],.95),
                                    upload_bytes=progress['bytes']-diagnostic_progress['bytes'])
                        diagnostic_after=self.diagnostic_snapshot()
                        diagnosis=self.contention_diagnosis(base,metric,diagnostic_before,diagnostic_after)
                        consecutive=consecutive+1 if diagnosis['trigger'] else 0
                        append(self.ev.directory/'decisions.jsonl',dict(diagnosis=diagnosis,consecutive=consecutive,raw_before=diagnostic_before,raw_after=diagnostic_after,utc=utc_now(),observer='S2 policy',mode=self.case['mode'],metric=metric,baseline_p95_ms=base,request_ids=[r['request_id'] for r in tail],current_rate=current))
                        if diagnosis['trigger'] and not detected:
                            self.ev.event('symptom_detected',target=a['port']['id']);detected=True
                        if not diagnosed and consecutive>=2:
                            self.ev.event('diagnosis_completed',target=a['port']['id']);diagnosed=True
                        if not split and diagnosed:
                            if self.case['mode']=='P' and time.monotonic()+420<start+cfg['horizon_seconds']:
                                split=self.split_if_enabled(a,b,current)
                        elif split and self.case['mode']=='P' and not rate_locked and time.monotonic()+120<start+cfg['horizon_seconds']:
                            # Same bounded rate ladder; failure at floor remains a service result.
                            healthy=stable(base,metric)
                            following=next_rate(current,healthy)
                            rate_steps+=1
                            rate_locked=not healthy or following==current or rate_steps>=5
                            current=following
                            self.ev.event('action_requested',target=b['port']['id'],actor='policy',rate=current)
                            self.set_rate(current)
                            self.ev.event('action_applied',target=b['port']['id'],actor='policy',rate=current)
                        diagnostic_before=diagnostic_after;diagnostic_progress=progress
                        next_decision=time.monotonic()+60
                horizon(self.ev,start,cfg['horizon_seconds'])
                # Keep the remote clock's complete H and in-flight completions in raw;
                # the analyser still selects only the original runner-clock interval.
                time.sleep(remote_tail_seconds(cfg))
            self.check_clock('horizon-end')
            text=remote_file(self.ev,self.remote,raw_path,'requests.jsonl')
            progress_text=remote_file(self.ev,self.remote,progress_path,'uploader-progress.jsonl')
            from fresh_analysis import uploader_metrics
            upload=uploader_metrics([json.loads(l) for l in progress_text.splitlines() if l],epoch(injection['utc']),epoch(injection['utc'])+cfg['horizon_seconds'])
            windows=upload['windows']
            integrity_code="""import hashlib,json,sqlite3
from pathlib import Path
root=Path(ROOT)
with sqlite3.connect(root/'progress.db') as db:
 rows=db.execute('select id,size,sha from chunks order by id').fetchall()
files=[{'index':i,'size':(root/f'{i:06d}.chunk').stat().st_size,'sha256':hashlib.sha256((root/f'{i:06d}.chunk').read_bytes()).hexdigest()} for i,size,sha in rows]
print(json.dumps({'rows':rows,'files':files}))
""".replace('ROOT',repr('/var/lib/openstack-k8s-graduation/'+self.record['run_id']))
            integrity=json.loads(self.remote('sudo python3 -',data=integrity_code,timeout=300))
            final=dict(port=self.admin_json('port','show',b['port']['id']),upload_node=self.pods('upload')[0]['spec']['nodeName'],
                       api_uid=self.pods('api')[0]['metadata']['uid'],upload_image_id=self.pods('upload')[0]['status']['containerStatuses'][0]['imageID'])
            raw=dict(network_qdisc=json.loads((Path(self.record['evidence'])/'baseline.json').read_text())['qdisc_before'][0],initial=initial,final=final,policy_id=self.record['policy_id'],upload_windows=windows,upload_integrity=integrity,
                     upload_elapsed_seconds=cfg['horizon_seconds'],offered_seconds=cfg['uploader_seconds'],horizon_seconds=cfg['horizon_seconds'],max_chunks=4096,
                     application_image_ids={'api':initial['api_image_id'],'upload':final['upload_image_id']},
                     provenance={'file':'raw/run.json','fields':['workers','policy_id'],'transform':'fresh S2 independent snapshots; windows retain progress samples'})
            atomic_json(self.ev.directory/'observations/contract.json',raw)
            self.write('completed')
        except BaseException as exc:
            self.write('failed',error=str(exc));raise


class FreshS3(FreshOwnedLab, EvaluationS3):
    def __init__(self,case,profile,ev):
        super().__init__('automatic')
        self.case,self.profile,self.ev=case,profile,ev

    def recover_if_enabled(self,source,start,cfg):
        if self.case['mode']!='P3600' or time.monotonic()+180>=start+cfg['horizon_seconds']:
            return False
        self.ev.event('action_requested',target=source['nova_id'],actor='policy')
        self.fence()
        self.ev.event('fence_confirmed',target=source['nova_id'],actor='policy')
        if time.monotonic()<start+cfg['horizon_seconds']:
            self.mark_out_of_service()
            applied=self.obj('node',source['node'],False)
            if not any(t['key']==OUT and t.get('value')==self.record['run_id'] for t in applied['spec'].get('taints',[])):
                raise RuntimeError('out-of-service apply not confirmed')
            self.ev.event('out_of_service_applied',target=source['node_uid'],actor='policy',observation=applied)
            self.ev.event('action_applied',target=source['node_uid'],actor='policy')
        return True

    def finish(self):
        workers=self.start()
        try:
            nodes = self.client.get('w', 'nodes')['items']
            cpnode = next(n for n in nodes if 'node-role.kubernetes.io/control-plane' in n['metadata'].get('labels', {}))
            cp = self.binding(cpnode)
            interfaces = self.admin_json('port', 'list', '--network', workers[0]['port']['network_id'], '--device-owner', 'network:router_interface')
            if len(interfaces) != 1:
                raise RuntimeError('one tenant router required for independent SSH access')
            router_port = self.admin_json('port', 'show', interfaces[0]['ID'])
            self.write('management-path-ready', router_id=router_port['device_id'], control_plane=cp)
            self.controller_policy()
            self.build_database(workers, cp)
            source = self.record['source']
            machine = self.obj('machine', source['machine'], plane='m')
            if SKIP in machine['metadata'].get('annotations', {}) or machine['metadata'].get('deletionTimestamp'):
                raise RuntimeError('source Machine already controlled by another recovery')
            self.write('ownership-intent')
            self.k('-n', self.client.ns, 'annotate', 'machine', source['machine'], SKIP + '=' + self.record['run_id'], plane='m')
            seed = digest({'seed':self.case['seed'],'block':self.case['block'],'scenario':'s3','purpose':self.case['purpose']})
            self.sql("create table evidence(id integer primary key, value text not null); insert into evidence select i, md5(i::text || '" + seed + "') from generate_series(1,1000) i;")
            rows_query = 'select json_agg(t order by t.id) from (select id,value from evidence where id<=1000) t'
            committed_rows = json.loads(self.sql(rows_query))
            expected_rows = [{'id': i, 'value': hashlib.md5((str(i) + seed).encode()).hexdigest()}
                             for i in range(1, 1001)]
            if committed_rows != expected_rows:
                raise RuntimeError('committed baseline records differ from the seed')
            self.save('committed-records-before.json', committed_rows)
            query = "select count(*)::text || ':' || md5(string_agg(id::text || ':' || value, ',' order by id)) from evidence where id<=1000"
            committed_digest = self.sql(query)
            durability = self.sql("select current_setting('fsync') || ':' || current_setting('synchronous_commit') || ':' || current_setting('full_page_writes') || ':' || current_setting('data_directory')")
            if not durability.startswith('on:on:on:/var/lib/postgresql/data/pgdata'):
                raise RuntimeError('DB durability settings differ from the experiment contract')
            fixture_ready(self.ev)
            self.write('baseline-ready', committed_digest=committed_digest, durability=durability)
            # Scoped transient rules: old PostgreSQL remains running, its client path and
            # kubelet API traffic fail. Rules disappear on VM restart and have owned chains.
            cfg=self.profile['s3']
            controller=self.guest(cp,'cat /etc/kubernetes/manifests/kube-controller-manager.yaml')
            mhc=self.client.get('m','machinehealthchecks','-n',self.client.ns)
            actual_specs=sorted((m['spec'] for m in mhc['items']),key=digest)
            if actual_specs!=sorted(self.profile['timers']['mhc_policy']['s3_specs'],key=digest):
                raise RuntimeError('S3 actual MHC policy differs from registered matched timers')
            admitted_machine=self.obj('machine',source['machine'],plane='m')
            if admitted_machine['metadata']['uid']!=source['machine_uid'] or admitted_machine['metadata'].get('annotations',{}).get(SKIP)!=self.record['run_id']:
                raise RuntimeError('S3 remediation exclusion not admitted')
            st=self.obj('statefulset','db')
            def probe():
                answer=self.k('-n',self.ns,'exec','probe','--','env',
                    'PGCONNECT_TIMEOUT='+str(int(cfg['deadline_seconds'])),
                    'PGOPTIONS=-c statement_timeout='+str(int(cfg['deadline_seconds']*1000)),
                    'psql','-X','-At','-v','ON_ERROR_STOP=1','-h','db','-U','postgres','-d','postgres',
                    '-c','select count(*) from evidence',timeout=cfg['deadline_seconds']+2).strip()
                return dict(ok=answer=='1000',correct=answer=='1000',body=answer)
            sampler=OpenLoopProbe(self.ev.directory/'requests.jsonl',probe,cfg['rate'],cfg['horizon_seconds']+300,cfg['deadline_seconds'])
            with sampler:
                baseline_gate(self.ev,cfg,lambda:list(sampler.rows),source='OpenLoopProbe SQL first registered arrivals')
                injection_guard(self.profile,cfg['horizon_seconds'],self.runtime.environment())
                self.ev.event('injection_requested',target=source['node_uid'])
                self.write('fault-intent',fault_at=utc_now())
                fault = '''set -Eeuo pipefail
    ! iptables -S OSK8S_S3_OUT >/dev/null 2>&1
    ! iptables -S OSK8S_S3_DB >/dev/null 2>&1
    test ! -e /run/osk8s-s3-owner
    echo RUN_ID >/run/osk8s-s3-owner
    iptables -N OSK8S_S3_OUT
    iptables -A OSK8S_S3_OUT -p tcp --dport 6443 -j DROP
    iptables -I OUTPUT -j OSK8S_S3_OUT
    iptables -N OSK8S_S3_DB
    iptables -A OSK8S_S3_DB -p tcp --dport 5432 -j DROP
    iptables -I FORWARD -j OSK8S_S3_DB
    crictl ps --name db -o json
    '''.replace('RUN_ID', shlex.quote(self.record['run_id']))
                process = self.guest(source, fault)
                running = json.loads(process)
                self.save('old-db-running-after-fault.json', running)
                old_pod = self.record['pod_before']
                expected_container = old_pod['status']['containerStatuses'][0]['containerID'].split('://', 1)[-1]
                matching = [c for c in running.get('containers', []) if
                            c.get('id') == expected_container and
                            c.get('labels', {}).get('io.kubernetes.pod.uid') == old_pod['metadata']['uid'] and
                            c.get('state') == 'CONTAINER_RUNNING']
                if len(matching) != 1:
                    raise RuntimeError('old DB process was not running after fault')
                injected=self.ev.event('injection_applied',target=source['node_uid'])
                start=time.monotonic();sampler.until=start+cfg['horizon_seconds']
                sampler.until_utc=epoch(injected['utc'])+cfg['horizon_seconds']
                self.ev.state('INJECTED');self.ev.state('OBSERVING')
                not_ready=False;diagnosed=False;last_snapshot=None
                while time.monotonic()<start+cfg['horizon_seconds']:
                    node=self.obj('node',source['node'],False)
                    if not not_ready and not condition(node,'Ready'):
                        self.ev.event('node_not_ready_observed',target=source['node_uid'],observation=node)
                        self.ev.event('symptom_detected',target=source['node_uid'])
                        not_ready=True
                    recent=[r for r in sampler.rows if epoch(r['scheduled_utc'])>=time.time()-15-cfg['deadline_seconds'] and not r.get('generator_rejection') and r.get('error')!='unfinished']
                    recent=sorted(recent,key=lambda r:epoch(r['scheduled_utc']))[-max(1,int(15*cfg['rate'])):]
                    if not diagnosed and not_ready and len(recent)>=15*cfg['rate'] and all(not r['ok'] for r in recent):
                        diagnosed=True
                        append(self.ev.directory/'decisions.jsonl',dict(utc=utc_now(),observer='S3 policy',mode=self.case['mode'],node_observation=node,request_ids=[r['request_id'] for r in recent],all_read_failed=True))
                        self.ev.event('diagnosis_completed',target=source['node_uid'])
                        self.write('diagnosed',not_ready_observed=not_ready,diagnosis_completed_at=utc_now())
                        if self.case['mode']=='P3600' and time.monotonic()+180<start+cfg['horizon_seconds']:
                            self.recover_if_enabled(source,start,cfg)
                    last_snapshot=dict(time=utc_now(),node=node,pod=self.dbpod(),attachments=self.client.get('w','volumeattachments'))
                    atomic_json(self.ev.directory/'observations'/('db-'+str(time.monotonic_ns())+'.json'),last_snapshot)
                    time.sleep(min(3,max(0,start+cfg['horizon_seconds']-time.monotonic())))
                horizon(self.ev,start,cfg['horizon_seconds'])
            seed_after=None;seed_error=None
            try:seed_after=json.loads(self.sql(rows_query,timeout=cfg['evidence_timeout_seconds']))
            except (RuntimeError,TimeoutError,subprocess.TimeoutExpired,json.JSONDecodeError) as exc:
                seed_error=f'{type(exc).__name__}: {exc}'
            fence_path=Path(self.record['evidence'])/'fence.json'
            raw=dict(source_machine_uid=source['machine_uid'],run_id=self.record['run_id'],seed=seed,admitted_machine=admitted_machine,pod_before=self.record['pod_before'],statefulset=st,controller_manifest=controller,mhc_snapshot=mhc,source_vm=source['nova_id'],
                     seed_before=committed_rows,seed_after=seed_after,seed_collection_error=seed_error,
                     fence=json.loads(fence_path.read_text()) if fence_path.exists() else {},db_final=last_snapshot,
                     old_database_processes=running,source_node_uid=source['node_uid'],
                     pvc_after=self.obj('pvc','data-db-0'),pv_after=self.obj('pv',self.record['pv_name'],False),
                     pvc_uid=self.record['pvc_uid'],volume_id=self.record['volume_id'],
                     application_image_ids={'db':self.record['pod_before']['status']['containerStatuses'][0]['imageID']},
                     volume_after=self.admin_json('volume','show',self.record['volume_id']),
                     source_final=self.admin_json('server','show',source['nova_id']),source_host=source['host'],
                     source_final_hypervisor=self.remote('sudo docker exec nova_libvirt virsh domstate '+shlex.quote(source['instance_name']),host=source['host']).strip(),
                     target_vm=self.record['target']['nova_id'],target_node=self.record['target']['node'],
                     provenance={'file':'raw/committed-records-before.json','fields':['id','value'],'transform':'seed comparison only; read probes do not establish continuous write durability'})
            atomic_json(self.ev.directory/'observations/contract.json',raw)
            self.write('completed')
        except BaseException as exc:
            self.write('failed',error=str(exc));raise


class FreshS4Run(S4Run):
    def snapshot(self,directory,index):
        """Read independent APIs concurrently; keep all original identity evidence."""
        obs={'time':utc_now(),'errors':{},'collection_timing':{}}
        queries={
            'md':('m','machinedeployment',self.preparation.md_name,'-n',self.client.ns),
            'mhc':('m','machinehealthcheck',MHC_NAME,'-n',self.client.ns),
            'machines':('m','machines','-n',self.client.ns,'-l','cluster.x-k8s.io/cluster-name='+self.client.cluster),
            'osmachines':('m','openstackmachines','-n',self.client.ns,'-l','cluster.x-k8s.io/cluster-name='+self.client.cluster),
            'nodes':('w','nodes'),'pods':('w','pods','-n',S4_NS),
            'deployment':('w','deployment',HTTP_NAME,'-n',S4_NS),
            'events':('m','events','-n',self.client.ns),
        }
        def collect(name):
            began=utc_now();start=time.monotonic()
            try:
                value=nova('list') if name=='nova' else self.client.get(*queries[name])
                return name,value,None,{'started_utc':began,'ended_utc':utc_now(),'seconds':time.monotonic()-start}
            except (RuntimeError,subprocess.TimeoutExpired,ValueError,OSError) as exc:
                return name,None,f'{type(exc).__name__}: {exc}',{'started_utc':began,'ended_utc':utc_now(),'seconds':time.monotonic()-start}
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            for name,value,error,timing in pool.map(collect,[*queries,'nova']):
                obs['collection_timing'][name]=timing
                if error is None:obs[name]=value
                else:obs['errors'][name]=error
        obs['collected_utc']=utc_now()
        atomic_json(directory/f'{index:04d}.json',obs)
        return obs

    def replacement_evidence(self,record,node,lab):
        # The full snapshot still verifies identity/readiness every cycle.
        # Expensive physical binding and probe creation are needed once per node.
        cached=getattr(self,'_replacement_evidence',None)
        if cached is None or cached[0]!=node:
            self.create_probe(record,node)
            binding=lab.binding(lab.obj('node',node,False))
            cached=(node,binding);self._replacement_evidence=cached
        return cached[1]

    def create_probe(self,record,node):
        # Require scheduler placement on the replacement; nodeName would bypass schedulability.
        name=record['probe_name']
        existing=self.preparation.object('w','pod',name,S4_NS)
        if existing:
            if existing['metadata'].get('labels',{}).get(LABEL_KEY)!=EXPERIMENT or existing['spec'].get('nodeSelector',{}).get('kubernetes.io/hostname')!=node:
                raise RuntimeError('capacity probe ownership/selector changed')
            return
        manifest={'apiVersion':'v1','kind':'Pod','metadata':{'name':name,'namespace':S4_NS,'labels':{LABEL_KEY:EXPERIMENT}},
                  'spec':{'nodeSelector':{'kubernetes.io/hostname':node},'restartPolicy':'Never',
                          'containers':[{'name':'probe','image':'busybox@sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e','command':['sh','-c','sleep '+str(record['horizon_seconds']+600)],
                            'resources':{'requests':{'cpu':'10m','memory':'16Mi'}},
                            'readinessProbe':{'exec':{'command':['sh','-c','wget -q -O - http.graduation-s4.svc.cluster.local:8080/healthz | grep -q ok']},'periodSeconds':3,'timeoutSeconds':2}}]}}
        self.preparation.k('w','apply','-f','-',data=json.dumps(manifest))


def run_s4(case,profile,ev):
    prep=EvaluationS4Preparation()
    prep.prepare()
    runner=FreshS4Run(prep)
    prepared,verified,evidence,target,originals,budget=runner.check_preflight()
    lab=RecoveryLab('s3')
    target['node_uid']=lab.obj('node',target['node'],False)['metadata']['uid']
    before=lab.obj('machinehealthcheck',MHC_NAME,plane='m')
    if 'cluster.x-k8s.io/paused' in before['metadata'].get('annotations',{}):
        raise RuntimeError('MHC already paused by another actor')
    atomic_json(ev.directory/'mhc-ownership.json',{'before':before,'owner':case['id']})
    if case['mode']=='off':
        lab.k('patch','machinehealthcheck',MHC_NAME,'-n',lab.client.ns,'--type=json','-p',json.dumps([
            {'op':'test','path':'/metadata/uid','value':before['metadata']['uid']},
            {'op':'test','path':'/metadata/resourceVersion','value':before['metadata']['resourceVersion']},
            {'op':'add','path':'/metadata/annotations','value':{**before['metadata'].get('annotations',{}),'cluster.x-k8s.io/paused':'true','openstack-k8s.dev/fresh-owner':case['id']}}]),plane='m')
    during=lab.obj('machinehealthcheck',MHC_NAME,plane='m')
    if during['metadata']['uid']!=before['metadata']['uid'] or during['spec']!=before['spec'] or ('cluster.x-k8s.io/paused' in during['metadata'].get('annotations',{}))!=(case['mode']=='off'):
        raise RuntimeError('MHC arm readback failed before injection')
    initial_image_id=prep.object('w','pod',target['pod'],S4_NS)['status']['containerStatuses'][0]['imageID']
    fixture_ready(ev)
    cfg=profile['s4']
    record=dict(version=2,horizon_seconds=cfg['horizon_seconds'],fresh_attempt=str(ev.directory.resolve()),run_id='s4-'+__import__('uuid').uuid4().hex[:12],environment_run_id=prepared['environment_run_id'],
                created=utc_now(),preparation_run_id=prepared['run_id'],evidence=str(evidence),target=target,
                original_workers=originals,probe_name='fresh-capacity-probe',mhc_uid=verified['mhc_uid'],host_deadline_epoch=budget)
    runner.write(record,'baseline-ready')
    def probe():
        from graduation_s4_run import http_probe
        return http_probe(prep.workload)
    sampler=OpenLoopProbe(ev.directory/'requests.jsonl',probe,cfg['rate'],cfg['horizon_seconds']+600,cfg['deadline_seconds'])
    try:
        with sampler:
            baseline_gate(ev,cfg,lambda:list(sampler.rows),source='OpenLoopProbe HTTP first registered arrivals')
            injection_guard(profile,cfg['horizon_seconds'],prep.environment_record())
            ev.event('injection_requested',target=target['nova_id'])
            runner.write(record,'stop-intent',stop_intent_at=utc_now())
            nova('stop',target['nova_id'])
            wait_for(lambda:nova_status(target['nova_id'])['status']=='SHUTOFF',seconds=90)
            stopped_vm=nova_status(target['nova_id'])
            runner.write(record,'injected',injected_at=utc_now())
            injected=ev.event('injection_applied',target=target['nova_id'])
            start=time.monotonic();sampler.until=start+cfg['horizon_seconds']
            sampler.until_utc=epoch(injected['utc'])+cfg['horizon_seconds']
            ev.state('INJECTED');ev.state('OBSERVING')
            snapshots=evidence/'observations';snapshots.mkdir(exist_ok=True)
            index=0;capacity={'state':'pending'};binding=None;capacity_probe=None;observation=None
            while time.monotonic()<start+cfg['horizon_seconds']:
                cycle_started=time.monotonic()
                observation=runner.snapshot(snapshots,index);index+=1
                workers=[m for m in observation.get('machines',{}).get('items',[]) if m['metadata']['uid'] not in originals and m['metadata'].get('labels',{}).get('cluster.x-k8s.io/deployment-name')==prep.md_name]
                if len(workers)==1 and condition(workers[0],'Ready'):
                    node=workers[0].get('status',{}).get('nodeRef',{}).get('name')
                    if node:
                        binding=runner.replacement_evidence(record,node,lab)
                        capacity_probe=next((p for p in observation.get('pods',{}).get('items',[])
                                             if p['metadata']['name']==record['probe_name']),None)
                append(ev.directory/'decisions.jsonl',dict(utc=utc_now(),observer='external MHC/CAPI/CAPO',source='observations/capacity-'+f'{index:04}'+'.json',limitation='internal controller decisions are not instrumented; raw controller events retained'))
                capacity=summarize_capacity(observation,target,originals,record['probe_name'])
                atomic_json(ev.directory/'observations'/f'capacity-{index:04}.json',observation)
                time.sleep(max(0,min(cycle_started+5,start+cfg['horizon_seconds'])-time.monotonic()))
            horizon(ev,start,cfg['horizon_seconds'])
        # Keep off paused until cleanup has restarted the owned VM and observed
        # Node Ready. Unpausing an unhealthy target races native remediation.
        raw=dict(mhc_before=before,mhc_during=during,capacity=capacity,
                 capacity_snapshot=observation,original_workers=originals,probe_name=record['probe_name'],
                 replacement_binding=binding,capacity_probe=capacity_probe,target=target,
                 stopped_vm=stopped_vm,application_image_ids={'http':initial_image_id},
                 allowed_computes=[profile['source_compute'],profile['target_compute']],
                 provenance={'file':'raw/observations/*.json','transform':'S4 capacity independently recalculated from final snapshot; binding is a fresh API read'})
        atomic_json(ev.directory/'observations/contract.json',raw)
        # Observing all H is a completed trial even without service/capacity recovery.
        runner.write(record,'completed',result={'state':'fresh-independent-judgement-required'})
    except BaseException as exc:
        runner.write(record,'failed',error=str(exc));raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',type=Path,required=True)
    parser.add_argument('--profile',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    case=json.loads(args.case.read_text());profile=json.loads(args.profile.read_text())
    from fresh_contract import validate
    validate(profile,live=True)
    ev=Evidence(args.evidence,'scenario')
    import os, signal
    remaining=float(os.environ['FRESH_FIXTURE_DEADLINE_UTC'])-time.time()
    if remaining<=0:raise TimeoutError('fixture whole-phase deadline expired before adapter')
    def fixture_timeout(*_):raise TimeoutError('fixture whole-phase timeout')
    signal.signal(signal.SIGALRM,fixture_timeout)
    signal.setitimer(signal.ITIMER_REAL,remaining)
    atomic_json(ev.directory/'environment.json',{'scenario':case['scenario'],'mode':case['mode'],
                'probe_path':{'s1':'control-plane loadgen Pod','s2':'receiver network namespace','s3':'control-plane SQL probe via Kubernetes exec','s4':'Kubernetes API service proxy'}[case['scenario']],
                'source_profile':'profile-contract.json','state_dir':str(__import__('os').environ['STATE_DIR'])})
    if case['scenario']=='s4':run_s4(case,profile,ev)
    else:{'s1':FreshS1,'s2':FreshS2,'s3':FreshS3}[case['scenario']](case,profile,ev).finish()


if __name__=='__main__':
    main()
