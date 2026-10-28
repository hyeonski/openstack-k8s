"""Opt-in operational adapters for the frozen fresh evaluation only.

The context file fixes environment and cluster identities. Structured CLI reads
are registered here; arbitrary shell commands are never inferred to be reads.
"""
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]


def context():
    source=os.environ.get('FRESH_READ_CONTEXT')
    if not source:return None
    value=json.loads(Path(source).read_text())
    if value.get('version')!=1:raise ValueError('unknown fresh read context')
    return value


def identity(ctx,remaining):
    # Direct commands under the outer deadline; no recursive transport retry.
    from workload_state import command_once
    env=json.loads(Path(ctx['environment_path']).read_text())
    if env['run_id']!=ctx['environment_run_id']:raise RuntimeError('environment identity changed')
    hosts=json.loads(command_once(['gcloud','compute','instances','list',
        '--project='+ctx['project'],'--filter=zone:('+ctx['zone']+')',
        '--format=json(name,id,status)'],timeout=remaining()))
    actual={h['name']:h for h in hosts if h['name'] in ctx['hosts']}
    if set(actual)!=set(ctx['hosts']) or any(str(actual[n]['id'])!=str(v) or actual[n]['status']!='RUNNING' for n,v in ctx['hosts'].items()):
        raise RuntimeError('VM identity changed')
    objects=json.loads(command_once(['kubectl','--kubeconfig',ctx['management_kubeconfig'],
        '--request-timeout='+str(remaining())+'s','get','cluster/'+ctx['cluster'],
        'machinedeployment/'+ctx['md'],
        '-n',ctx['namespace'],'-o','json'],timeout=remaining()))
    uids={o['kind']:o['metadata']['uid'] for o in objects['items']}
    ca=json.loads(command_once(['kubectl','--kubeconfig',ctx['management_kubeconfig'],
        '--request-timeout='+str(remaining())+'s','get','deployment','cluster-autoscaler',
        '-n',ctx['ca_namespace'],'-o','json'],timeout=remaining()))
    uids['Deployment']=ca['metadata']['uid']
    if uids!=ctx['management_uids']:raise RuntimeError('management object UID changed')
    remaining()


def read(label,invoke,timeout):
    ctx=context()
    if ctx is None:return invoke(timeout)
    if str(ROOT/'evaluation') not in sys.path:sys.path.insert(0,str(ROOT/'evaluation'))
    from fresh_read_budget import read_with_budget
    return read_with_budget(lambda left:invoke(left()),timeout=timeout,
        identity=lambda left:identity(ctx,left),label=label,evidence=ctx['evidence'],
        compound=label=='openstack-workload-inventory')


# Explicit OpenStack grammar. Mutations are dispatched once by LabRuntime.
OPENSTACK_READS={('server','show'),('server','list'),('port','show'),('port','list'),
    ('volume','show'),('volume','list'),('flavor','show'),('flavor','list'),
    ('image','show'),('image','list'),('extension','list'),
    ('network','show'),('network','list'),('subnet','show'),('subnet','list'),
    ('network','qos','policy','list'),('network','qos','policy','show'),
    ('network','qos','rule','show'),('network','qos','rule','list'),
    ('security','group','list'),('security','group','show'),
    ('floating','ip','list'),('floating','ip','show'),
    ('volume','service','list'),('compute','service','list'),
    ('hypervisor','show'),('hypervisor','list')}


def openstack_read(args):
    return any(tuple(map(str,args[:len(prefix)]))==prefix for prefix in OPENSTACK_READS)


def command_read(args,data=None):
    if data is not None or not args:return None
    values=list(map(str,args));exe=Path(values[0]).name
    if exe=='kubectl':
        # Service proxy GET and SQL exec are intentionally excluded.
        if any('/proxy/' in x for x in values):return None
        from fresh_transport import read_command
        if read_command(values[1:]):return 'kubernetes-operational'
    if exe=='gcloud' and values[1:4] in (['compute','instances','list'],['compute','instances','describe']):return 'gcp-identity'
    if exe=='graduation-s4-nova.sh' and values[1:2] in (['list'],['show']):return 's4-nova-read'
    if exe=='workload-inventory.sh':return 'openstack-workload-inventory'
    if exe=='graduation-s1-placement.sh':return 's1-nova-placement'
    return None


REMOTE_READS={
    'uname -m':'controller-architecture',
    'if ip link show s2-egress >/dev/null 2>&1; then echo present; else echo absent; fi':'s2-cleanup-link',
    'curl -fsS http://198.18.0.2:8090/progress':'s2-uploader-progress',
    'sudo tc -s -j qdisc show dev s2-egress':'s2-qdisc',
    "python3 -c 'import time; print(time.time())'":'remote-clock',
}
