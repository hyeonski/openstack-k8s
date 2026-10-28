#!/usr/bin/env python3
"""One bounded, out-of-sample qualification; never inject a service/VM fault."""
import argparse
import hashlib
import json
import os
import signal
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'evaluation')]
from workload_state import command,command_once
from lib.fresh_reads import identity
from fresh_clock_guard import ClockLease,SERVICE_ROOT,durable
from fresh_evidence import Evidence,append,clock_check,utc
from fresh_read_budget import read_with_budget
from fresh_mutation import mutation_once
from fresh_read_registry import audit,FILES


def run(destination,context_path,seconds=1800):
    if seconds!=1800:raise ValueError('qualification is exactly one >=30-minute observation')
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('qualification destination exists; do not silently repeat')
    destination.mkdir(parents=True)
    ev=Evidence(destination,'qualification');token=uuid.uuid4().hex
    ctx=json.loads(Path(context_path).read_text());ctx['evidence']=str(destination/'reads')
    durable(destination/'read-context.json',ctx)
    os.environ['FRESH_READ_CONTEXT']=str(destination/'read-context.json')
    registry=audit();source={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in FILES}
    for name in ('fresh_clock_guard.py','fresh_read_budget.py','fresh_mutation.py','fresh_baseline.py','fresh_evidence.py','fresh_campaign.py','fresh_seal.py','fresh_read_registry.py'):
        source['evaluation/'+name]=hashlib.sha256((ROOT/'evaluation'/name).read_bytes()).hexdigest()
    name='fresh-qualification-'+token[:16];uid=None;cleanup=False;passed=False
    kube=['kubectl','--kubeconfig',ctx['management_kubeconfig'],'-n','default']
    result=dict(kind='single-out-of-sample-qualification',started=utc(),pid=os.getpid(),
        required_observation_seconds=seconds,real_time_cap_seconds=2700,source_sha256=source,
        registry=registry,no_experiment_attempt=True,no_service_or_vm_fault=True,fixture_name=name)
    durable(destination/'started.json',result)
    def get():return json.loads(command(kube+['get','configmap',name,'-o','json'],timeout=90))
    began=time.monotonic()
    try:
        identity(ctx,lambda:20)
        with ClockLease(destination,seconds=2700):
            protected=time.monotonic();wall=time.time();previous=(wall,protected)
            body=dict(apiVersion='v1',kind='ConfigMap',metadata=dict(name=name,namespace='default',
                labels={'app.kubernetes.io/managed-by':'fresh-qualification'},annotations={'fresh-qualification-token':token}),data={'state':'created'})
            durable(destination/'fixture-intent.json',body)
            # Unique name and immutable token establish ownership even if create acknowledgement is lost.
            try:command_once(kube+['create','-f','-'],data=json.dumps(body),timeout=20)
            except Exception as error:ev.event('fixture_create_response_error',detail=str(error))
            obj=get()
            if obj['metadata'].get('annotations',{}).get('fresh-qualification-token')!=token:raise RuntimeError('fixture ownership mismatch')
            uid=obj['metadata']['uid'];result['fixture_uid']=uid;durable(destination/'fixture-created.json',obj)
            def fixture_identity(left):
                identity(ctx,left)
                found=json.loads(command_once(kube+['get','configmap',name,'-o','json'],timeout=left()))
                if found['metadata']['uid']!=uid:raise RuntimeError('fixture UID changed')
            def patch_lost_ack():
                patch=[dict(op='test',path='/metadata/uid',value=uid),dict(op='replace',path='/data/state',value='readback-confirmed')]
                command_once(kube+['patch','configmap',name,'--type=json','-p',json.dumps(patch)],timeout=20)
                raise RuntimeError('synthetic connection reset after successful single fixture patch')
            mutation_once(ev,'qualification-own-configmap-patch',patch_lost_ack,get,
                lambda found:found['metadata']['uid']==uid and found['data']['state']=='readback-confirmed')
            blackout_started=time.monotonic();attempts=[]
            def injected_read(left):
                elapsed=time.monotonic()-blackout_started;attempts.append(elapsed)
                if elapsed<20:raise RuntimeError('synthetic TLS handshake timeout; local read adapter injection only')
                return command_once(kube+['get','configmap',name,'-o','json'],timeout=left())
            recovered=json.loads(read_with_budget(injected_read,timeout=90,identity=fixture_identity,
                label='qualification-20s-read-outage',evidence=destination))
            assert recovered['metadata']['uid']==uid
            result['read_outage']=dict(simulated_seconds=20,attempt_seconds=attempts,
                recovered_seconds=time.monotonic()-blackout_started,mutation_count=1,observations_filled=False)
            next_sample=0
            while time.monotonic()-protected<seconds:
                now=(time.time(),time.monotonic());delta=(now[0]-previous[0])-(now[1]-previous[1]);previous=now
                if abs(delta)>.1:raise RuntimeError('qualification wall/monotonic step')
                state=json.loads((SERVICE_ROOT/'state.json').read_text())
                if state['status']!='protected' or state['pid']!=os.getpid():raise RuntimeError('clock protection lost')
                append(destination/'local-clock.jsonl',dict(utc=utc(),elapsed=now[1]-protected,delta=delta))
                if now[1]-protected>=next_sample:
                    clock_check(ev,'qualification',lambda:float(command_once(['gcloud','compute','ssh','osk8s-controller',
                        '--project='+ctx['project'],'--zone='+ctx['zone'],'--tunnel-through-iap',
                        '--command='+"python3 -c 'import time; print(time.time())'",'--quiet'],timeout=20).strip()),
                        5,'same controller host clock as S2; original 5-second bound')
                    print(json.dumps(dict(utc=utc(),observed_seconds=now[1]-protected,remaining_seconds=max(0,seconds-(now[1]-protected)))),flush=True)
                    next_sample+=60
                if time.monotonic()-began>2700:raise TimeoutError('qualification cap reached')
                time.sleep(min(1,max(0,seconds-(time.monotonic()-protected))))
            result['protected_observation_seconds']=time.monotonic()-protected
            if abs((time.time()-wall)-result['protected_observation_seconds'])>.1:raise RuntimeError('cumulative clock disagreement')
            fixture_identity(lambda:20)
        result['clock_restored']=json.loads((SERVICE_ROOT/'state.json').read_text())
        if result['clock_restored']['restored_network_time']!=result['clock_restored']['original_network_time']:
            raise RuntimeError('original clock setting not restored')
        passed=True
    except BaseException as error:
        result['error']=type(error).__name__+': '+str(error)
        raise
    finally:
        if uid:
            try:
                current=get()
                if current['metadata']['uid']!=uid or current['metadata'].get('annotations',{}).get('fresh-qualification-token')!=token:
                    raise RuntimeError('refuse fixture cleanup: ownership changed')
                options=dict(apiVersion='v1',kind='DeleteOptions',preconditions=dict(uid=uid))
                command_once(['kubectl','--kubeconfig',ctx['management_kubeconfig'],'delete',
                    '--raw=/api/v1/namespaces/default/configmaps/'+name,'-f','-'],data=json.dumps(options),timeout=20)
                absent=command(kube+['get','configmap',name,'--ignore-not-found','-o','json'],timeout=90)
                if absent.strip():raise RuntimeError('fixture cleanup not confirmed')
                cleanup=True
            except Exception as error:result['cleanup_error']=type(error).__name__+': '+str(error)
        result.update(passed=passed and cleanup,cleanup_verified=cleanup,finished=utc(),elapsed_seconds=time.monotonic()-began)
        result['source_unchanged']=all(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==sha for n,sha in source.items())
        result['passed']=result['passed'] and result['source_unchanged'] and result['elapsed_seconds']<=2700
        durable(destination/'result.json',result)
    return result

if __name__=='__main__':
    def stop(*_):raise RuntimeError('qualification clock guard interrupted owner')
    signal.signal(signal.SIGTERM,stop)
    parser=argparse.ArgumentParser();parser.add_argument('--destination',required=True);parser.add_argument('--context',required=True)
    args=parser.parse_args();result=run(args.destination,args.context)
    print(json.dumps(result));raise SystemExit(0 if result['passed'] else 1)
