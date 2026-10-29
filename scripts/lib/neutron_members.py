"""Reconcile Neutron remote-SG caches only before an owned readiness probe.

No security policy changes. A restart is sent once, with a durable ambiguity
journal. Never run while a measurement clock lease is active.
"""
import ipaddress,json,os,shlex,time,uuid
from pathlib import Path
from lib.state import atomic_json
from lib.runtime import LabRuntime
from lib.fresh_reads import context,identity,read


def require_idle_clock():
    if os.environ.get('FRESH_CLOCK_TOKEN'):
        raise RuntimeError('network reconciliation forbidden during measurement')
    state=json.loads(Path('/var/db/openstack-k8s-clock-guard/state.json').read_text())
    if state.get('status')!='restored':
        raise RuntimeError('network reconciliation requires an idle restored clock guard')


def set_name(group_id):
    return 'NIPv4'+str(uuid.UUID(group_id))[:24]


def parse_sets(text,names):
    sets={}
    for line in text.splitlines():
        parts=shlex.split(line)
        if len(parts)>=2 and parts[0]=='create' and parts[1] in names:
            if parts[1] in sets:raise ValueError('duplicate remote SG set')
            sets[parts[1]]=set()
        elif len(parts)>=3 and parts[0]=='add' and parts[1] in names:
            value=ipaddress.ip_network(parts[2],strict=False)
            if value.version!=4 or value.prefixlen!=32:raise ValueError('unexpected remote SG network')
            sets[parts[1]].add(str(value.network_address))
    if set(sets)!=set(names):raise ValueError('required Neutron remote SG set missing')
    return {k:sorted(v) for k,v in sets.items()}


def authoritative(client,runtime,ctx,left):
    if client.cluster!=ctx['cluster'] or client.ns!=ctx['namespace']:raise RuntimeError('cluster binding changed')
    nodes=client.get('w','nodes')['items'];members={'worker':set(),'controlplane':set()};bindings=[]
    for n in nodes:
        role='controlplane' if 'node-role.kubernetes.io/control-plane' in n['metadata'].get('labels',{}) else 'worker'
        addresses=[a['address'] for a in n['status']['addresses'] if a['type']=='InternalIP'];assert len(addresses)==1
        address=str(ipaddress.IPv4Address(addresses[0]));server_id=str(uuid.UUID(n['spec']['providerID'].rsplit('/',1)[-1]))
        server=runtime.admin_json('server','show',server_id,timeout=left())
        host=server['OS-EXT-SRV-ATTR:host']
        if server['status']!='ACTIVE' or host not in ctx['hosts']:raise RuntimeError('worker host identity not bound')
        members[role].add(address);bindings.append(dict(node_uid=n['metadata']['uid'],server_id=server_id,host=host,address=address))
    if len(members['controlplane'])!=1 or not members['worker']:raise RuntimeError('stable CP/worker membership required')
    groups={};expected={}
    for role,ips in members.items():
        name='k8s-cluster-'+client.ns+'-'+client.cluster+'-secgroup-'+role
        group=runtime.admin_json('security','group','show',name,timeout=left())
        if group['name']!=name:raise RuntimeError('security group identity mismatch')
        ports=runtime.admin_json('port','list','--security-group',group['id'],timeout=left())
        actual={ip['ip_address'] for p in ports for ip in p['Fixed IP Addresses']}
        if actual!=ips:raise RuntimeError('Neutron ports and Kubernetes nodes not converged')
        groups[role]=dict(policy=group,ports=sorted(p['ID'] for p in ports));expected[set_name(group['id'])]=sorted(ips)
    if len(expected)!=2:raise RuntimeError('SG prefix collision')
    return dict(groups=groups,expected=expected,bindings=sorted(bindings,key=lambda b:b['server_id']))


def reconcile_hosts(runtime,hosts,expected,path,journal,ctx,left,verify,check_idle):
    names=sorted(expected)
    command='set -e; '+'; '.join('sudo docker exec -u 0 neutron_openvswitch_agent ipset save '+shlex.quote(n) for n in names)
    def remote_read(script,host):
        return read('neutron-readiness:'+script,lambda timeout:runtime.remote(script,host=host,timeout=timeout),left())
    def inspect(host):
        value=json.loads(remote_read('sudo docker inspect neutron_openvswitch_agent',host))
        if len(value)!=1 or value[0].get('Name')!='/neutron_openvswitch_agent' or not value[0]['State']['Running']:raise RuntimeError('existing running Neutron agent required')
        return value[0]['Id']
    observed={};ids={}
    for host in hosts:
        ids[host]=inspect(host);raw=remote_read(command,host);(path/(host+'-before.txt')).write_text(raw);observed[host]=parse_sets(raw,names)
    if journal.exists():
        pending=json.loads(journal.read_text());host=pending['host']
        if (pending['environment_run_id']!=ctx['environment_run_id'] or ids.get(host)!=pending['container_id'] or observed.get(host)!=expected):
            raise RuntimeError('unresolved Neutron restart; manual reconciliation required, no replay')
        atomic_json(path/'prior-journal-observed-complete.json',pending);journal.unlink()
    restarted=[]
    for host in hosts:
        if observed[host]==expected:continue
        check_idle();verify()
        intent=dict(host=host,container_id=ids[host],environment_run_id=ctx['environment_run_id'],expected=expected,observed=observed[host],restart_attempts=1)
        atomic_json(path/(host+'-restart-intent.json'),intent);atomic_json(journal,intent)
        # Mutation deliberately does not use a read/retry adapter.
        response=runtime.remote('sudo docker restart neutron_openvswitch_agent',host=host,timeout=left())
        (path/(host+'-restart-response.txt')).write_text(response)
        while True:
            raw=remote_read(command,host);(path/(host+'-after.txt')).write_text(raw)
            if parse_sets(raw,names)==expected:break
            left();time.sleep(2)
        if inspect(host)!=ids[host]:raise RuntimeError('Neutron container replaced during reconciliation')
        atomic_json(path/(host+'-restart-verified.json'),dict(intent,verified=True));journal.unlink();restarted.append(host)
    return restarted


def reconcile_before_probe(client,path):
    ctx=context()
    if ctx is None:return
    require_idle_clock();end=time.monotonic()+450
    def left():
        remaining=end-time.monotonic()
        if remaining<=0:raise TimeoutError('Neutron readiness reconciliation deadline')
        return min(45,remaining)
    verify=lambda:identity(ctx,left)
    verify();destination=Path(path)/'neutron-membership';destination.mkdir(parents=True,exist_ok=False)
    runtime=LabRuntime(client);before=authoritative(client,runtime,ctx,left);atomic_json(destination/'authority-before.json',before)
    hosts=sorted({b['host'] for b in before['bindings']})
    restarted=reconcile_hosts(runtime,hosts,before['expected'],destination,client.state/'fresh-neutron-reconcile-journal.json',ctx,left,verify,require_idle_clock)
    if restarted:
        after=authoritative(client,runtime,ctx,left);atomic_json(destination/'authority-after.json',after)
        if after!=before:raise RuntimeError('security policy or authoritative membership changed during restart')
    verify();require_idle_clock()
    atomic_json(destination/'result.json',dict(passed=True,restarted_hosts=restarted,same_security_policy=True,members_match_authority=True,measurement_inactive=True,environment_run_id=ctx['environment_run_id'],expected=before['expected']))
