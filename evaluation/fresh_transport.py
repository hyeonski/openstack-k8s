"""Bounded local-transport repair for identified Kubernetes reads only.

No command mutation, synthetic observation, or experiment action is retried.
The caller's original deadline includes reconnect, identity reads and backoff.
"""
from contextlib import contextmanager
import fcntl
import math
from pathlib import Path
import re
import socket
import time

from fresh_evidence import append, utc


def transient_transport_error(exc):
    text = str(exc).lower()
    if any(word in text for word in ('forbidden', 'unauthorized', 'notfound',
                                     'not found', 'permission denied', 'certificate')):
        return False
    return any(word in text for word in ('connection reset', 'connection refused',
        'broken pipe', 'unexpected eof', 'unable to connect to the server',
        'error while connecting to', 'failed to receive data from'))


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
    if not math.isfinite(timeout) or timeout <= 0:
        raise TimeoutError('read deadline exhausted before command')
    end = clock() + timeout

    def remaining():
        value = end - clock()
        if value <= 0:
            raise TimeoutError('read cumulative deadline exhausted')
        return value

    for number in range(1, attempts + 1):
        remaining()
        try:
            if number > 1:
                # Reconnect is serialised with the preparation/cleanup watcher.
                reconnect(remaining)
                identity(remaining)
            result = invoke(deadline_args(args, remaining()), data=data, timeout=remaining())
            if number > 1:
                identity(remaining)
            remaining()
        except Exception as exc:
            append(Path(evidence) / 'transport-read-attempts.jsonl', dict(
                utc=utc(), command=list(map(str, args)), attempt=number,
                error=type(exc).__name__ + ': ' + str(exc),
                remaining_seconds=max(0, end - clock()), observation_filled=False))
            if number == attempts or not transient_transport_error(exc):
                raise
            pause = min(float(number), remaining())
            sleep(pause)
            remaining()
        else:
            append(Path(evidence) / 'transport-read-attempts.jsonl', dict(
                utc=utc(), command=list(map(str, args)), attempt=number,
                captured=True, remaining_seconds=max(0, end - clock()),
                observation_filled=False))
            return result


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
    text = str(exc).lower()
    if any(word in text for word in ('forbidden', 'unauthorized', 'permission denied',
            'not found', 'notfound', 'invalid argument', 'invalid choice',
            'certificate', '403:', '401:')):
        return False
    return ('4047' in text and 'failed to lookup instance' in text) or any(
        word in text for word in ('connection reset', 'connection refused',
            'broken pipe', 'unexpected eof', 'failed to receive data',
            'connection timed out', 'connection closed by remote host'))


def retry_ssh_read(invoke, *, timeout, identity, label, evidence,
                   attempts=3, clock=time.monotonic, sleep=time.sleep):
    """Explicit read only; no shell classification and no nested command retry.

    identity must independently establish the existing VM and attempt ownership.
    Its queries, both backoffs and every read share the original timeout.
    A successful retry is a later real observation, never a filled missing row.
    """
    if not math.isfinite(timeout) or timeout <= 0 or attempts not in (1, 2, 3):
        raise ValueError('invalid bounded SSH read budget')
    end = clock() + timeout
    def remaining():
        left = end - clock()
        if left <= 0: raise TimeoutError('SSH read cumulative deadline exhausted')
        return left
    for number in range(1, attempts + 1):
        started = utc(); begin = clock()
        try:
            result = invoke(remaining())
            remaining()
        except Exception as exc:
            append(Path(evidence)/'ssh-read-attempts.jsonl', dict(label=label,
                attempt=number, started_utc=started, ended_utc=utc(),
                elapsed_seconds=clock()-begin, error=type(exc).__name__+': '+str(exc),
                remaining_seconds=max(0, end-clock()), observation_filled=False))
            if not transient_ssh_error(exc): raise
            if number == attempts:
                raise TimeoutError('SSH read attempt limit exhausted: '+label) from exc
            # In particular, IAP4047 alone is not evidence of a transient error.
            try:
                identity(remaining)
                remaining()
            except Exception as identity_error:
                append(Path(evidence)/'ssh-read-attempts.jsonl', dict(label=label,
                    attempt=number, identity_error=type(identity_error).__name__+': '+str(identity_error),
                    utc=utc(), observation_filled=False))
                raise
            sleep(min(float(number), remaining()))
            remaining()
        else:
            if number > 1:
                try:
                    identity(remaining)
                    remaining()
                except Exception as identity_error:
                    append(Path(evidence)/'ssh-read-attempts.jsonl', dict(label=label,
                        attempt=number, utc=utc(), after_read_identity_error=type(identity_error).__name__+': '+str(identity_error),
                        captured=False, observation_filled=False))
                    raise
            append(Path(evidence)/'ssh-read-attempts.jsonl', dict(label=label,
                attempt=number, started_utc=started, ended_utc=utc(),
                elapsed_seconds=clock()-begin, captured=True,
                remaining_seconds=max(0, end-clock()), observation_filled=False))
            return result


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
        import json
        from workload_state import ROOT, command
        runner = self.runner
        if host not in {w['host'] for w in runner.record['workers']}:
            raise ValueError('host stat outside current workers')
        return json.loads(retry_ssh_read(
            lambda left: command([ROOT/'scripts/host-stat.sh', host], timeout=left),
            timeout=runner.client.remaining(90),
            identity=lambda remaining: self.identity(host, remaining),
            label='host-stat:'+host, evidence=runner.ev.directory))


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
