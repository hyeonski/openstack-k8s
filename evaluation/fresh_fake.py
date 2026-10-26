"""SYNTHETIC validator fixtures only. These traces are never experiment results."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import uuid

from fresh_evidence import append, utc
from fresh_contract import STATES, digest


def synthetic_profile(profile):
    p=copy.deepcopy(profile)
    p['readiness']='synthetic-only'
    for s in ('s1','s2','s3','s4'):
        p[s].update(horizon_seconds=40,stable_seconds=10,bin_seconds=5,min_samples=2,
                    deadline_seconds=2,slo_ms=100,bin_max_bad_fraction=0)
    p['s3']['evidence_timeout_seconds']=60
    p['v1_condition']={'slo_ms':100,'bin_max_bad_fraction':0,'baseline_p95_ratio':1.5}
    p['s1']['max_clock_offset_seconds']=2
    p['s2']['max_clock_offset_seconds']=2
    p['s2']['uploader_seconds']=640
    p['timers']['mhc_policy']={'s3_specs':[{'maxUnhealthy':1}]}
    return p


class FakeBackend:
    def __init__(self, fail_cleanup=False, unrecovered=False):
        self.fail_cleanup=fail_cleanup
        self.unrecovered=unrecovered
        self.executed=[]

    def execute(self, case, profile, ev):
        self.executed.append(case['id'])
        cfg=profile[case['scenario']]
        if cfg['horizon_seconds'] is None:
            raise ValueError('synthetic run requires explicit synthetic parameters; generate profile with fresh_fake.py')
        t=1792972800.0
        self.t=t
        self.ev=ev
        def event(kind, offset=0, **fields):
            append(ev.directory/'events.jsonl',dict(event_id=uuid.uuid4().hex,kind=kind,utc=utc(t+offset),
                monotonic_ns=int((1000+offset)*1e9),clock_id='synthetic-clock',observer='synthetic',**{'target_uid':'source','actor':'observer',**fields}))
        self.event=event
        event('phase',-3,phase='PREPARED');event('phase',-2,phase='BASELINE')
        event('injection_requested',-1)
        event('injection_applied',0)
        event('phase',0,phase='INJECTED');event('phase',0,phase='OBSERVING')
        control=case['mode'] in ('M','M3600','off')
        v1=case['mode']=='V1'
        if case['scenario']=='s3' and control:event('node_not_ready_observed',2,target_uid='source-node',observation={'metadata':{'uid':'source-node'},'status':{'conditions':[{'type':'Ready','status':'Unknown'}]}})
        if not control and not v1:
            event('node_not_ready_observed',2,target_uid='source-node',observation={'metadata':{'uid':'source-node'},'status':{'conditions':[{'type':'Ready','status':'Unknown'}]}}) if case['scenario']=='s3' else None
            event('diagnosis_completed',3)
            event('action_requested',4,actor='policy')
            if case['scenario']=='s3':event('fence_confirmed',5,actor='policy');event('out_of_service_applied',6,actor='policy')
            event('action_applied',7,actor='policy',target_uid='old')
        H=cfg['horizon_seconds']
        count=int(profile['s1']['seconds']*cfg['rate']) if case['scenario']=='s1' else int(H*cfg['rate'])
        for i in range(count):
            offset=i/cfg['rate']
            good=v1 or (not control and not self.unrecovered and offset>=10) or offset>=H
            append(ev.directory/'requests.jsonl',dict(request_id=str(i),index=i,scheduled_utc=utc(t+offset),
                time=utc(t+offset),latency_ms=10,
                started_utc=utc(t+offset+.001),completed_utc=utc(t+offset+.011),ok=good,correct=good,bytes=128 if good else 0,
                generator_rejection=False,deadline_seconds=cfg['deadline_seconds'],clock_id='synthetic-request',
                started_monotonic=1000+offset+.001,completed_monotonic=1000+offset+.011))
        if case['scenario'] in ('s1','s2'):
            for phase,offset in (('before-injection',-1),('horizon-end',H)):
                append(ev.directory/'clock-checks.jsonl',{'phase':phase,'utc':utc(t+offset),'source':'synthetic clock only','offset_lower_seconds':0,'offset_upper_seconds':0,'round_trip_seconds':0})
        raw=fake_raw(case)
        if v1:
            raw['baseline_interval_utc']=[utc(t-60),utc(t)]
            raw['policy_windows_utc']=[[utc(t),utc(t+H)]]
            for i in range(300):
                append(ev.directory/'baseline-requests.jsonl',dict(index=i,time=utc(t-60+i/5),ok=True,latency_ms=10))
        if case['scenario']=='s2':
            append(ev.directory/'decisions.jsonl',{'raw_before':{'utc':utc(t),'monotonic':0,'clock_id':'synthetic-network','qdisc':{'bytes':0,'overlimits':0}},'raw_after':{'utc':utc(t+H-1),'monotonic':H-1,'clock_id':'synthetic-network','qdisc':{'bytes':(H-1)*2_500_000,'overlimits':10}}})
            for second in range(-1,H+1):
                append(ev.directory/'uploader-progress.jsonl',{'utc':utc(t+second),'progress':{'bytes':max(0,second)*100,'next':0}})
        if case['scenario']=='s4':
            raw.update(original_workers=['m1','m3'],probe_name='probe')
            for second in range(0,H+1,5):
                snap=capacity_snapshot(raw,t+second,case['mode']=='on' and second>=10)
                from lib.state import atomic_json
                atomic_json(ev.directory/'observations'/f'capacity-{second:04}.json',snap)
            raw['capacity_snapshot']=snap
        from lib.state import atomic_json
        atomic_json(ev.directory/'environment.json',{'synthetic':True,'version':'fake','image_digest':'fake-sha256'})
        atomic_json(ev.directory/'observations/contract.json',raw)
        event('horizon_end',H);event('phase',H,phase='HORIZON_END')

    def cleanup(self, case, profile, ev):
        if case['scenario']=='s4' and not self.fail_cleanup:
            from lib.state import atomic_json
            atomic_json(ev.directory/'mhc-restored.json',fake_raw(case)['mhc_restored'])
        return {'synthetic':True,'actor':'cleanup','checks':{'owned_resources_absent':not self.fail_cleanup,'controller_restored':not self.fail_cleanup}}


def fake_raw(case):
    mode=case['mode']
    before=dict(pod_uid='old',node='n1',nova_id='v1',image_id='image',container_id='c1',restart_count=0)
    after={**before}
    if mode=='P':after.update(pod_uid='new',node='n2',nova_id='v2',container_id='c2')
    if mode=='A':after.update(pod_uid='new',container_id='c2')
    mhc={'metadata':{'uid':'mhc'},'spec':{'maxUnhealthy':1}}
    source={'metadata':{'uid':'node-1'}}
    seed=digest({'seed':case['seed'],'block':case['block'],'scenario':'s3','purpose':case['purpose']})
    import hashlib
    seed_rows=[{'id':i,'value':hashlib.md5((str(i)+seed).encode()).hexdigest()} for i in range(1,1001)]
    fence_server={'status':'SHUTOFF','id':'v1','OS-EXT-STS:power_state':4,'OS-EXT-STS:task_state':None,'OS-EXT-SRV-ATTR:host':'h1'}
    raw=dict(network_qdisc={'kind':'tbf','options':{'rate':2_500_000}},application_image_ids={'application':'synthetic-image'},run_id='fake-run',source_machine_uid='m1',admitted_machine={'metadata':{'uid':'m1','annotations':{'cluster.x-k8s.io/skip-remediation':'fake-run'}}},
             pvc_uid='pvc',volume_id='volume',target_vm='v2',target_node='n2',pvc_after={'metadata':{'uid':'pvc'}},pv_after={'spec':{'claimRef':{'uid':'pvc'},'csi':{'volumeHandle':'volume'}}},volume_after={'id':'volume','attachments':[{'server_id':'v1' if mode=='M3600' else 'v2'}]},seed=seed,source_node_uid='source-node',service_before=before,service_after=after,contender_after={'status':'ACTIVE','OS-EXT-SRV-ATTR:host':'h1'},source_compute='h1',
             compute_before='h1',compute_after='h2' if mode=='P' else 'h1',node_before=source,node_after=source,
             vm_before={'id':'v1'},vm_after={'id':'v1'},host_metrics={'cpu_utilization':.9,'cpu_pressure_some':.2},completion_host_metrics={'cpu_utilization':.9,'cpu_pressure_some':.2},
             initial=dict(progress={'bytes':0,'next':0},port={'qos_policy_id':None},api_node='n1',upload_node='n1',api_uid='api'),
             final=dict(port={'qos_policy_id':'qos' if mode=='P' else None},upload_node='n2' if mode=='P' else 'n1',api_uid='api'),
             policy_id='qos',upload_integrity={'rows':[[0,4096,'digest']],'files':[{'index':0,'size':4096,'sha256':'digest'}]},upload_windows=[{'before':{'bytes':0},'after':{'bytes':4096}}],upload_elapsed_seconds=40,
             statefulset={'spec':{'template':{'spec':{'tolerations':[{'key':k,'tolerationSeconds':3600} for k in ('node.kubernetes.io/not-ready','node.kubernetes.io/unreachable')]}}}},
             old_database_processes={'containers':[{'id':'container','state':'CONTAINER_RUNNING','labels':{'io.kubernetes.pod.uid':'db-old'}}]},pod_before={'metadata':{'uid':'db-old'},'status':{'containerStatuses':[{'containerID':'containerd://container'}]}},controller_manifest='--disable-force-detach-on-timeout=true',mhc_snapshot={'items':[mhc]},source_vm='v1',
             fence={} if mode=='M3600' else {'server':fence_server,'hypervisor_state':'shut off'},source_final={**fence_server} if mode!='M3600' else {'id':'v1','status':'ACTIVE'},source_host='h1',source_final_hypervisor='shut off',db_final={'node':{'spec':{}},'pod':{'metadata':{'uid':'db-new'},'spec':{'nodeName':'n2'}}},seed_before=seed_rows,seed_after=None if mode=='M3600' else seed_rows,
             mhc_before=mhc,mhc_during={**mhc,'metadata':{'uid':'mhc','annotations':{'cluster.x-k8s.io/paused':'true'}}} if mode=='off' else mhc,mhc_restored=mhc,
             capacity={'state':'pending'} if mode=='off' else {'state':'recovered','replacement':{'machine_uid':'m2','node':'n2','nova_id':'v2'}},
             replacement_binding={'machine_uid':'m2','node':'n2','node_uid':'node2','nova_id':'v2','host':'h2'},allowed_computes=['h1','h2'],
             stopped_vm={'id':'v1','status':'SHUTOFF'},target={'machine_uid':'m1','node':'n1','node_uid':'node1','nova_id':'v1'},capacity_probe={'spec':{'nodeName':'n2','nodeSelector':{'kubernetes.io/hostname':'n2'}},'status':{'phase':'Running','conditions':[{'type':'Ready','status':'True'}]}})
    return raw


def capacity_snapshot(raw, at, recovered):
    """Raw fake API objects, independently consumed by the production capacity adapter."""
    ready={'conditions':[{'type':'Ready','status':'True'}]}
    def machine(uid,node,vm):
        return {'metadata':{'name':uid,'uid':uid,'labels':{'cluster.x-k8s.io/deployment-name':'workers'}},'spec':{'providerID':'openstack:///'+vm},'status':{**ready,'nodeRef':{'name':node}}}
    machines=[machine('m3','n3','v3'),machine('m2','n2','v2')] if recovered else [machine('m3','n3','v3'),machine('m1','n1','v1')]
    nodes=[{'metadata':{'name':m['status']['nodeRef']['name'],'uid':'node2' if m['metadata']['uid']=='m2' else m['metadata']['uid']},'spec':{},'status':ready} for m in machines]
    http={'metadata':{'name':'http','labels':{'app':'graduation-s4-http'}},'spec':{'nodeName':'n3'},'status':ready}
    pods=[http]
    if recovered:pods.append({'metadata':{'name':'probe'},'spec':raw['capacity_probe']['spec'],'status':raw['capacity_probe']['status']})
    return dict(time=utc(at),errors={},md={'metadata':{'name':'workers'},'status':{'replicas':2,'readyReplicas':2 if recovered else 1,'availableReplicas':2 if recovered else 1}},
                machines={'items':machines},nodes={'items':nodes},nova=[{'ID':'v3','Status':'ACTIVE'},{'ID':'v2' if recovered else 'v1','Status':'ACTIVE' if recovered else 'SHUTOFF'}],
                deployment={'status':{'readyReplicas':1}},pods={'items':pods},osmachines={'items':[]},mhc=raw['mhc_during'])


if __name__=='__main__':
    # Print an explicitly marked, deterministic validation configuration; never confirm a live draft.
    p=json.loads(Path(sys.argv[1]).read_text())
    print(json.dumps(synthetic_profile(p),indent=2))
