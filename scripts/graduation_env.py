#!/usr/bin/env python3
"""Ensure an existing graduation testbed is ready without rebuilding it.

The environment gate is scenario-agnostic. An absent GCP host or missing
cluster is an error: the greenfield lab-up path is always explicit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Commands:
    def run(self, args, timeout=60):
        result = subprocess.run([str(arg) for arg in args], capture_output=True,
                                text=True, timeout=timeout, check=False)
        if result.returncode:
            # The command's stderr can contain credentials or kubeconfig data.
            diagnostic = ''
            if Path(args[0]).name == 'start-workload-guests.sh':
                messages = [line for line in result.stderr.splitlines()
                            if line.startswith('ERROR: workload guest') or
                            line.startswith('ERROR: no current workload Machine')]
                diagnostic = '; ' + messages[-1] if messages else ''
            raise RuntimeError(f'{args[0]} exited {result.returncode}{diagnostic}')
        return result.stdout


class Environment:
    def __init__(self, config, commands=None):
        self.config = config
        self.commands = commands or Commands()
        self.root = Path(config['root'])
        self.state_dir = Path(config['state_dir'])
        self.state_path = self.state_dir / 'graduation-environment.json'
        self.lock_path = self.state_dir / 'graduation-environment.lock'

    def command(self, *args, timeout=60):
        return self.commands.run(args, timeout=timeout)

    def host(self, name):
        data = json.loads(self.command(
            'gcloud', 'compute', 'instances', 'describe', name,
            '--project=' + self.config['project'], '--zone=' + self.config['zone'],
            '--format=json'))
        if data.get('name') != name:
            raise RuntimeError(f'GCP host identity mismatch: {name}')
        return {'name': name, 'status': data.get('status'),
                'id': str(data.get('id', '')),
                'last_start': data.get('lastStartTimestamp'),
                'max_run_seconds': data.get('scheduling', {}).get('maxRunDuration', {}).get('seconds')}

    def hosts(self):
        return {name: self.host(name) for name in self.config['hosts']}

    def check_local_inputs(self):
        kubeconfigs = self.state_dir / 'kubeconfigs'
        for name in ('management', self.config['cluster']):
            if not (kubeconfigs / (name + '.yaml')).is_file():
                raise RuntimeError(f'missing {name} kubeconfig; use the explicit bootstrap path')

    def kubectl(self, plane, *args):
        name = 'management' if plane == 'management' else self.config['cluster']
        kubeconfig = self.state_dir / 'kubeconfigs' / (name + '.yaml')
        if not kubeconfig.is_file():
            raise RuntimeError(f'missing {plane} kubeconfig; use the explicit bootstrap path')
        return json.loads(self.command('kubectl', '--kubeconfig', kubeconfig,
                                       '--request-timeout=15s', *args, '-o', 'json', timeout=35))

    @staticmethod
    def ready_condition(obj):
        return any(c.get('type') == 'Ready' and c.get('status') == 'True'
                   for c in obj.get('status', {}).get('conditions', []))

    def cluster_ready(self):
        namespace = self.config['namespace']
        cluster = self.config['cluster']
        management_nodes = self.kubectl('management', 'get', 'nodes')['items']
        workload_nodes = self.kubectl('workload', 'get', 'nodes')['items']
        md = self.kubectl('management', 'get', 'machinedeployment',
                          cluster + '-md-0', '-n', namespace)
        capi_cluster = self.kubectl('management', 'get', 'cluster', cluster, '-n', namespace)
        if not management_nodes or not all(self.ready_condition(n) for n in management_nodes):
            return None
        control_planes = [n for n in workload_nodes if
                          'node-role.kubernetes.io/control-plane' in n['metadata'].get('labels', {})]
        workers = [n for n in workload_nodes if n not in control_planes]
        desired = md.get('spec', {}).get('replicas')
        if len(control_planes) != 1 or not self.ready_condition(control_planes[0]):
            return None
        if not isinstance(desired, int) or desired < 1 or len(workers) != desired:
            return None
        if not all(self.ready_condition(n) and not n.get('spec', {}).get('unschedulable') for n in workers):
            return None
        status = md.get('status', {})
        if any(status.get(key, 0) != desired for key in ('replicas', 'readyReplicas', 'availableReplicas')):
            return None
        if capi_cluster['metadata'].get('deletionTimestamp') or md['metadata'].get('deletionTimestamp'):
            raise RuntimeError('CAPI cluster or worker MachineDeployment is deleting')
        return {'management_nodes': [n['metadata']['name'] for n in management_nodes],
                'control_plane': control_planes[0]['metadata']['name'],
                'workers': [n['metadata']['name'] for n in workers],
                'worker_desired': desired,
                'cluster_uid': capi_cluster['metadata']['uid'],
                'md_uid': md['metadata']['uid']}

    def wait_cluster(self, seconds=900):
        deadline = time.monotonic() + seconds
        last_error = None
        while time.monotonic() < deadline:
            try:
                ready = self.cluster_ready()
                if ready:
                    return ready
            except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
                last_error = str(exc)
            time.sleep(min(10, max(0, deadline - time.monotonic())))
        raise TimeoutError(f'cluster did not become Ready; last error: {last_error}')

    def start_current_guests(self, data, attempts=3):
        for attempt in range(1, attempts + 1):
            try:
                output = self.command(self.root / 'observability/start-workload-guests.sh', timeout=360)
                data.pop('guest_error', None)
                data['guest_recovery'] = [line for line in output.splitlines() if 'workload guest' in line]
                self.record(data, 'recovering')
                return
            except RuntimeError as exc:
                self.record(data, 'recovering', guest_error=str(exc), guest_attempt=attempt)
                if attempt == attempts:
                    raise
                time.sleep(20)

    def record(self, data, phase, **values):
        data.update(values)
        if phase == 'ready':
            data.pop('error', None)
        data['phase'] = phase
        data['updated'] = utc_now()
        atomic_json(self.state_path, data)

    def reconcile(self):
        """Reconcile an interrupted start using exact host identity and state."""
        if not self.state_path.exists():
            raise RuntimeError('no environment preparation record to reconcile')
        with self.lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            data = json.loads(self.state_path.read_text())
            if data.get('version') != 1:
                raise RuntimeError('unknown environment record version')
            expected_profile = {'environment': self.config['environment'],
                                'project': self.config['project'], 'zone': self.config['zone'],
                                'cluster': self.config['cluster']}
            if data.get('profile') != expected_profile:
                raise RuntimeError('environment record belongs to another profile')
            current = self.hosts()
            if set(current) != set(data['initial_hosts']) or any(
                item['id'] != data['initial_hosts'][name]['id']
                for name, item in current.items()
            ):
                raise RuntimeError('GCP host identity changed; manual review required')
            if any(item['status'] not in ('RUNNING', 'TERMINATED') for item in current.values()):
                raise RuntimeError('GCP host is in an intermediate state; retry reconciliation later')
            for name in data['start_attempted']:
                if data['initial_hosts'][name]['status'] == 'TERMINATED' and current[name]['status'] == 'RUNNING':
                    if name not in data['started_hosts']:
                        data['started_hosts'].append(name)
            self.record(data, 'reconciled', observed_hosts=current)
            return data

    def ensure(self):
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            previous = json.loads(self.state_path.read_text()) if self.state_path.exists() else None
            if previous and previous.get('phase') in ('inspecting', 'starting', 'recovering'):
                raise RuntimeError('earlier environment ensure was interrupted; inspect its record first')
            if previous and previous.get('phase') == 'failed' and previous.get('start_attempted'):
                raise RuntimeError('earlier environment ensure failed after a host start attempt; reconcile ownership first')
            self.check_local_inputs()
            initial = self.hosts()
            statuses = {name: item['status'] for name, item in initial.items()}
            invalid = {name: status for name, status in statuses.items()
                       if status not in ('RUNNING', 'TERMINATED')}
            if invalid:
                raise RuntimeError(f'GCP hosts absent or in unexpected state: {invalid}; no bootstrap attempted')
            profile = {'environment': self.config['environment'],
                       'project': self.config['project'], 'zone': self.config['zone'],
                       'cluster': self.config['cluster']}
            if previous and previous.get('phase') in ('ready', 'reconciled'):
                if previous.get('version') != 1 or previous.get('profile') != profile:
                    raise RuntimeError('prepared environment record belongs to another profile')
                if set(previous['initial_hosts']) != set(initial) or any(
                    previous['initial_hosts'][name]['id'] != host['id']
                    for name, host in initial.items()
                ):
                    raise RuntimeError('GCP host identity changed since environment preparation')
                data = previous
            else:
                data = {'version': 1, 'run_id': 'env-' + uuid.uuid4().hex[:12],
                        'profile': profile, 'initial_hosts': initial,
                        'start_attempted': [], 'started_hosts': [], 'created': utc_now()}
            if previous and previous.get('phase') == 'ready' and\
                    all(host['status'] == 'RUNNING' for host in initial.values()):
                try:
                    ready = self.cluster_ready()
                except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired):
                    ready = None
                if ready:
                    if any(data['ready'][key] != ready[key] for key in ('cluster_uid', 'md_uid')):
                        raise RuntimeError('Kubernetes cluster identity changed since environment preparation')
                    self.record(data, 'ready', observed_hosts=initial, ready=ready,
                                final_hosts=initial)
                    return data
            self.record(data, 'inspecting', observed_hosts=initial)
            try:
                for name, status in statuses.items():
                    if status == 'RUNNING':
                        continue
                    if name not in data['start_attempted']:
                        data['start_attempted'].append(name)
                    self.record(data, 'starting')
                    self.command('gcloud', 'compute', 'instances', 'start', name,
                                 '--project=' + self.config['project'],
                                 '--zone=' + self.config['zone'], '--quiet', timeout=300)
                    if self.host(name)['status'] != 'RUNNING':
                        raise RuntimeError(f'GCP host did not start: {name}')
                    if name not in data['started_hosts']:
                        data['started_hosts'].append(name)
                    self.record(data, 'starting')
                self.record(data, 'recovering')
                self.command(self.root / 'scripts/gcp-hosts.sh', 'wait-ssh', timeout=330)
                self.command(self.root / 'scripts/gcp-openstack-recover.sh', timeout=360)
                self.start_current_guests(data)
                self.command(self.root / 'scripts/gcp-workload-api-tunnel.sh', 'ensure', timeout=120)
                ready = self.wait_cluster()
                final = self.hosts()
                if any(host['status'] != 'RUNNING' or host['id'] != data['initial_hosts'][name]['id']
                       for name, host in final.items()):
                    raise RuntimeError('GCP host changed or stopped during environment preparation')
                if 'ready' in data and any(data['ready'][key] != ready[key]
                                           for key in ('cluster_uid', 'md_uid')):
                    raise RuntimeError('Kubernetes cluster identity changed since environment preparation')
                self.record(data, 'ready', ready=ready, final_hosts=final)
                return data
            except BaseException as exc:
                self.record(data, 'failed', error=f'{type(exc).__name__}: {exc}')
                raise

    def down(self):
        """Stop only exact GCP hosts this environment run started."""
        if not self.state_path.exists():
            raise RuntimeError('no environment preparation record to close')
        with self.lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            data = json.loads(self.state_path.read_text())
            if data.get('phase') == 'stopped':
                return data
            if data.get('phase') not in ('ready', 'reconciled', 'failed', 'stopping', 'stop-failed'):
                raise RuntimeError('environment preparation is active; refusing to stop hosts')
            expected_profile = {'environment': self.config['environment'],
                                'project': self.config['project'], 'zone': self.config['zone'],
                                'cluster': self.config['cluster']}
            if data.get('version') != 1 or data.get('profile') != expected_profile:
                raise RuntimeError('environment record belongs to another profile')
            if set(data.get('start_attempted', [])) - set(data.get('started_hosts', [])):
                raise RuntimeError('host start ownership is uncertain; reconcile before stopping')
            s4_path = self.state_dir / 's4-preparation.json'
            if s4_path.exists():
                s4 = json.loads(s4_path.read_text())
                if s4.get('environment_run_id') == data['run_id'] and s4.get('phase') != 'restored':
                    raise RuntimeError('S4 fixture is still active or uncertain; clean it before stopping hosts')
            owned = [name for name in data['started_hosts']
                     if data['initial_hosts'][name]['status'] == 'TERMINATED']
            current = self.hosts()
            if set(current) != set(data['initial_hosts']) or any(
                item['id'] != data['initial_hosts'][name]['id'] for name, item in current.items()
            ):
                raise RuntimeError('GCP host identity changed; refusing environment stop')
            data.setdefault('stop_attempted', [])
            data.setdefault('stopped_hosts', [])
            try:
                for name in owned:
                    status = current[name]['status']
                    if status == 'TERMINATED':
                        if name not in data['stopped_hosts']:
                            data['stopped_hosts'].append(name)
                        continue
                    if status != 'RUNNING':
                        raise RuntimeError(f'GCP host {name} is in unexpected state {status}')
                    if name not in data['stop_attempted']:
                        data['stop_attempted'].append(name)
                    self.record(data, 'stopping')
                    self.command('gcloud', 'compute', 'instances', 'stop', name,
                                 '--project=' + self.config['project'],
                                 '--zone=' + self.config['zone'], '--quiet', timeout=300)
                    if self.host(name)['status'] != 'TERMINATED':
                        raise RuntimeError(f'GCP host did not stop: {name}')
                    if name not in data['stopped_hosts']:
                        data['stopped_hosts'].append(name)
                    self.record(data, 'stopping')
                self.record(data, 'stopped', final_hosts=self.hosts())
                return data
            except BaseException as exc:
                self.record(data, 'stop-failed', error=f'{type(exc).__name__}: {exc}')
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'ensure', 'reconcile', 'down'))
    parser.add_argument('--host', action='append', required=True)
    args = parser.parse_args()
    environment = Environment({
        'root': os.environ['PROJECT_ROOT'], 'state_dir': os.environ['STATE_DIR'],
        'environment': os.environ['ENVIRONMENT_NAME'],
        'project': os.environ['GCP_PROJECT_ID'], 'zone': os.environ['GCP_ZONE'],
        'cluster': os.environ['WORKLOAD_CLUSTER_NAME'],
        'namespace': os.environ['WORKLOAD_NAMESPACE'], 'hosts': args.host,
    })
    if args.action == 'status':
        result = {'hosts': environment.hosts(),
                  'record': json.loads(environment.state_path.read_text())
                  if environment.state_path.exists() else None}
    elif args.action == 'reconcile':
        result = environment.reconcile()
    elif args.action == 'down':
        result = environment.down()
    else:
        result = environment.ensure()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
