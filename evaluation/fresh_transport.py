"""Bounded local-transport repair for identified Kubernetes reads only.

No command mutation, synthetic observation, or experiment action is retried.
The caller's original deadline includes reconnect, identity reads and backoff.
"""
from contextlib import contextmanager
import fcntl
from pathlib import Path
import re
import socket
import time



def transient_transport_error(exc):
    from fresh_read_budget import transient_error
    return transient_error(exc)


def read_command(args, data=None):
    if data is not None:
        return False
    # Flags may precede the verb. Do not infer that exec or a rollout mutation
    # is read-only merely because some later argument contains "get".
    values = list(map(str, args))
    index = 0
    takes_value = {'-n', '--namespace', '--context', '--kubeconfig',
                   '--request-timeout', '--server', '-s'}
    while index < len(values) and values[index].startswith('-'):
        flag = values[index]
        index += 2 if flag in takes_value else 1
    if index >= len(values):
        return False
    verb = values[index]
    return verb in ('get', 'wait', 'logs') or (
        verb == 'rollout' and values[index + 1:index + 2] == ['status'])


def deadline_args(args, remaining):
    result = []
    for value in map(str, args):
        if value.startswith(('--timeout=', '--request-timeout=')):
            key, original = value.split('=', 1)
            match = re.fullmatch(r'(\d+(?:\.\d+)?)(ms|s|m|h)', original)
            if not match:
                raise ValueError('unrecognised Kubernetes timeout: ' + value)
            seconds = float(match[1]) * {'ms': .001, 's': 1, 'm': 60, 'h': 3600}[match[2]]
            # Never increase an existing request timeout or reset wait's timeout.
            value = key + '=' + str(max(.001, min(seconds, remaining))) + 's'
        result.append(value)
    return result


def retry_read(invoke, args, *, timeout, identity, reconnect, evidence,
               data=None, attempts=3, clock=time.monotonic, sleep=time.sleep):
    """invoke(args, data=..., timeout=...) must execute exactly one command."""
    if not read_command(args, data):
        return invoke(args, data=data, timeout=timeout)
    from fresh_read_budget import read_with_budget, _ACTIVE
    if _ACTIVE.get() is not None:
        left=_ACTIVE.get()
        return invoke(deadline_args(args,left()),data=data,timeout=left())
    values=list(map(str,args))
    convergence=('wait' in values or ('rollout' in values and 'status' in values))
    end=clock()+timeout
    while True:
        try:
            return read_with_budget(
                lambda left: invoke(deadline_args(args, max(.001,left()-1) if convergence else left()), data=data, timeout=left()),
                timeout=max(.001,end-clock()), identity=identity, reconnect=reconnect,
                label='kubectl:'+repr(tuple(args)), evidence=evidence, attempts=attempts,
                clock=clock, sleep=sleep)
        except Exception as error:
            # Kubernetes convergence timeout is a pending condition, distinct
            # from transport retry. Preserve the original wait's total deadline.
            pending=any(text in str(error).lower() for text in (
                'timed out waiting for the condition','timed out waiting for condition'))
            if not convergence or not pending or clock()>=end:raise
            sleep(min(.1,max(0,end-clock())))


def listener_reachable(port):
    try:
        with socket.create_connection(('127.0.0.1', int(port)), timeout=1):
            return True
    except OSError:
        return False


def coordinate_reconnect(call, state, root, *, clock=time.monotonic):
    """Wrap only the exact local tunnel ensure; delegate every mutation once."""
    def invoke(args, log, timeout=5400, allowed=(0,)):
        if list(map(str,args)) != [str(Path(root)/'scripts/gcp-workload-api-tunnel.sh'),'ensure']:
            return call(args,log,timeout=timeout,allowed=allowed)
        import os
        end=clock()+min(60,timeout)
        def remaining():
            left=end-clock()
            if left<=0:raise TimeoutError('transport reconnect cumulative deadline')
            return left
        with transport_lock(state,remaining):
            if listener_reachable(os.environ['WORKLOAD_LOCAL_API_PORT']):return 0
            result=call(args,log,timeout=remaining(),allowed=allowed)
            remaining()
            return result
    return invoke


@contextmanager
def transport_lock(state, remaining, sleep=time.sleep):
    """One reconnect owner, also used by the existing TransportWatch."""
    with (Path(state) / 'workload-api-reconnect.lock').open('a+') as lock:
        while True:
            remaining()
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                sleep(min(.1, remaining()))
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def transient_ssh_error(exc):
    return transient_transport_error(exc)


def retry_ssh_read(invoke, *, timeout, identity, label, evidence,
                   attempts=3, clock=time.monotonic, sleep=time.sleep):
    from fresh_read_budget import read_with_budget
    return read_with_budget(lambda left: invoke(left()), timeout=timeout,
        identity=identity, label=label, evidence=evidence, attempts=attempts,
        clock=clock, sleep=sleep, log_name='ssh-read-attempts.jsonl')


class SSHReadBoundary:
    """Only fixed S2 read commands and current-run evidence file reads."""
    def __init__(self, runner):
        self.runner = runner

    def identity(self, host, remaining):
        import json, os
        from workload_state import command
        runner = self.runner
        env = runner.runtime.environment()
        if (env['run_id'] != runner.record['environment_run_id']
                or runner.record.get('fresh_attempt') != str(runner.ev.directory.resolve())):
            raise RuntimeError('SSH read attempt/environment ownership changed')
        project, zone = runner.profile['project'], runner.profile['zone']
        if (os.environ['GCP_PROJECT_ID'], os.environ['GCP_ZONE']) != (project, zone):
            raise RuntimeError('SSH read project/zone changed')
        expected = env['final_hosts'].get(host)
        if not expected: raise RuntimeError('SSH read host outside owned environment')
        actual = json.loads(command(['gcloud', 'compute', 'instances', 'describe', host,
            '--project='+project, '--zone='+zone, '--format=json(name,id,status,zone)'],
            timeout=min(30, remaining())))
        if (actual.get('name') != host or str(actual.get('id')) != str(expected['id'])
                or actual.get('status') != 'RUNNING' or actual.get('zone','').split('/')[-1] != zone):
            raise RuntimeError('SSH read VM identity/existence changed')
        ns = json.loads(command(['kubectl', '--kubeconfig',
            runner.client.state/'kubeconfigs'/(runner.client.cluster+'.yaml'),
            '--request-timeout='+str(min(15, remaining()))+'s',
            'get', 'namespace', runner.ns, '-o', 'json'], timeout=min(20, remaining())))
        from lib.runtime import LABEL
        if (ns['metadata']['uid'] != runner.record['namespace_uid']
                or ns['metadata'].get('labels',{}).get(LABEL) != runner.record['run_id']):
            raise RuntimeError('SSH read namespace/run UID changed')
        remaining()

    def remote(self, script, *, timeout=120, host=None):
        import os, shlex
        runner = self.runner
        fixed = {'curl -fsS http://198.18.0.2:8090/progress',
                 'sudo tc -s -j qdisc show dev s2-egress',
                 "python3 -c 'import time; print(time.time())'"}
        root = '/var/lib/openstack-k8s-graduation/'+runner.record['run_id']
        files = [root+'/fresh-api.jsonl', root+'/fresh-api.jsonl.progress']
        allowed = fixed | {'sudo cat '+shlex.quote(p) for p in files}
        allowed.add('if sudo test -s '+shlex.quote(files[0])+'; then echo ready; fi')
        allowed.add('if sudo test -e '+shlex.quote(files[0]+'.stop')+'; then echo stopped; fi')
        controller=os.environ.get('CONTROLLER_NAME')
        if not controller:raise ValueError('SSH read controller is not configured')
        target = host or controller
        source=runner.record.get('source',{})
        source_state=('sudo docker exec nova_libvirt virsh domstate '+shlex.quote(source['instance_name'])) if source.get('instance_name') else None
        owned_source_read=source_state is not None and script==source_state and host==source.get('host')
        if not owned_source_read and (script not in allowed or target!=controller):
            raise ValueError('not an explicitly registered SSH read')
        return retry_ssh_read(lambda left: runner.remote(script, timeout=left, **({'host':host} if host is not None else {})),
            timeout=runner.client.remaining(timeout),
            identity=lambda remaining: self.identity(target, remaining),
            label=script, evidence=runner.ev.directory)

    def admin_json(self, args, *, timeout=60):
        import os
        runner=self.runner;args=tuple(args)
        ports={w['port']['id'] for w in runner.record['workers']}
        allowed=(len(args)==3 and args[:2]==('port','show') and args[2] in ports
            or args==('extension','list','--network')
            or args==('network','qos','rule','show',runner.record.get('policy_id'),runner.record.get('rule_id')))
        if not allowed:raise ValueError('not an explicitly registered OpenStack read')
        return retry_ssh_read(lambda left: runner.admin_json(*args,timeout=left),
            timeout=runner.client.remaining(timeout),
            identity=lambda remaining:self.identity(os.environ['CONTROLLER_NAME'],remaining),
            label='admin-json:'+str(args),evidence=runner.ev.directory)

    def host_stat(self, host):
        from fresh_collection import durable_host_stat
        runner=self.runner
        if host not in {w['host'] for w in runner.record['workers']}:
            raise ValueError('host stat outside current workers')
        runner._host_stat_sequence=getattr(runner,'_host_stat_sequence',0)+1
        return durable_host_stat(runner.ev,runner.runtime,host,runner._host_stat_sequence,
            identity=lambda left:self.identity(host,left),seconds=runner.client.remaining(90))


def stop_probe_once(runner, stop_path, *, clock=time.monotonic):
    """Lost stop acknowledgement: inspect its state, never issue touch twice."""
    import shlex
    expected='/var/lib/openstack-k8s-graduation/'+runner.record['run_id']+'/fresh-api.jsonl.stop'
    if stop_path != expected:raise ValueError('foreign probe stop path')
    end=clock()+runner.client.remaining(120)
    def remaining():
        left=end-clock()
        if left<=0:raise TimeoutError('probe stop acknowledgement deadline exhausted')
        return left
    try:
        runner.remote('sudo touch '+shlex.quote(stop_path),timeout=remaining())
    except Exception as error:
        runner.ev.event('mutation_response_error',operation='stop existing probe',
                        detail=type(error).__name__+': '+str(error),mutation_repeated=False)
        state=runner.read_remote('if sudo test -e '+shlex.quote(stop_path)+'; then echo stopped; fi',timeout=remaining()).strip()
        runner.ev.event('mutation_state_readback',operation='stop existing probe',
                        applied=state=='stopped',mutation_repeated=False)
        if state!='stopped':raise error


def read_owned_s3_binding(runner, node, *, timeout=60):
    """Only the three named Nova/port reads for a fixed S3 Node/Machine.

    No mutation, remote shell classifier or retry of the scenario. A single
    conservative 60-second budget covers mapping reads, SSH attempts and UID
    readbacks; each remote command has at most three attempts.
    """
    import os
    controller = os.environ.get('CONTROLLER_NAME')
    if not controller or runner.scenario != 's3':
        raise ValueError('owned S3 binding requires its controller')
    end = time.monotonic() + runner.client.remaining(timeout)
    previous = runner.client.deadline
    runner.client.deadline = end if previous is None else min(previous, end)
    def left():
        remaining = end - time.monotonic()
        if remaining <= 0: raise TimeoutError('S3 binding cumulative deadline exhausted')
        return remaining
    try:
        machines = runner.client.get('m', 'machines', '-n', runner.client.ns)['items']
        matched = [m for m in machines if not m['metadata'].get('deletionTimestamp')
                   and m.get('status', {}).get('nodeRef', {}).get('name') == node['metadata']['name']]
        if len(matched) != 1:
            raise RuntimeError('ambiguous Node/Machine mapping')
        machine = matched[0]
        provider = machine.get('spec', {}).get('providerID', '')
        if not provider.startswith('openstack:///') or node['spec'].get('providerID') != provider:
            raise RuntimeError('Node/Machine provider identity mismatch')
        def identity(remaining):
            SSHReadBoundary(runner).identity(controller, remaining)
            current_node = runner.client.get('w', 'node', node['metadata']['name'])
            current_machine = runner.client.get('m', 'machine', machine['metadata']['name'], '-n', runner.client.ns)
            if (current_node['metadata']['uid'] != node['metadata']['uid']
                    or current_node['spec'].get('providerID') != provider
                    or current_machine['metadata']['uid'] != machine['metadata']['uid']
                    or current_machine['metadata'].get('deletionTimestamp')
                    or current_machine['spec'].get('providerID') != provider
                    or current_machine.get('status', {}).get('nodeRef', {}).get('name') != node['metadata']['name']):
                raise RuntimeError('S3 binding Node/Machine identity changed')
            remaining()
        def query(*args):
            return retry_ssh_read(lambda seconds: runner.admin_json(*args, timeout=seconds),
                timeout=left(), identity=identity, label='S3 owned binding '+repr(args),
                evidence=runner.ev.directory)
        nova = query('server', 'show', provider.removeprefix('openstack:///'))
        if nova.get('id') != provider.removeprefix('openstack:///'):
            raise RuntimeError('S3 binding Nova identity changed')
        ports = query('port', 'list', '--server', nova['id'])
        if nova['status'] != 'ACTIVE' or len(ports) != 1:
            raise RuntimeError('one ACTIVE VM and one unambiguous port required')
        port = query('port', 'show', ports[0]['ID'])
        if port.get('id') != ports[0]['ID'] or port['device_id'] != nova['id'] or len(port['fixed_ips']) != 1:
            raise RuntimeError('VM/port identity mismatch')
        left()
        return {'node': node['metadata']['name'], 'node_uid': node['metadata']['uid'],
                'machine': machine['metadata']['name'], 'machine_uid': machine['metadata']['uid'],
                'nova_id': nova['id'], 'host': nova['OS-EXT-SRV-ATTR:host'],
                'instance_name': nova['OS-EXT-SRV-ATTR:instance_name'],
                'project_id': nova['project_id'], 'port': port,
                'ip': port['fixed_ips'][0]['ip_address']}
    finally:
        runner.client.deadline = previous
