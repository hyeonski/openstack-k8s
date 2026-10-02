#!/usr/bin/env python3
"""Owned S2/S3 fixture lifecycle and cross-plane identity checks."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import time
import uuid

from graduation_env import atomic_json, utc_now
from graduation_s1 import S1, LABEL
from graduation_s1_contention import S1Contention
from worker_control import WorkerControl
from workload_state import ROOT, artifact_dir, command, condition


class RecoveryLab:
    def __init__(self, scenario):
        self.scenario = scenario
        self.ns = 'graduation-' + scenario
        self.s1 = S1()
        self.client = self.s1.client
        self.cloud = S1Contention(self.s1)
        self.state = self.client.state / (scenario + '-experiment.json')
        self.lock = None
        self.record = json.loads(self.state.read_text()) if self.state.exists() else None

    def acquire(self):
        self.lock = (self.client.state / 'graduation-recovery.lock').open('a+')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def write(self, phase, **values):
        self.record.update(values, phase=phase, updated=utc_now())
        atomic_json(self.state, self.record)
        atomic_json(Path(self.record['evidence']) / 'run.json', self.record)
        print(self.scenario.upper() + ': ' + phase, flush=True)

    def save(self, name, value):
        path = Path(self.record['evidence']) / name
        if isinstance(value, str):
            path.write_text(value)
        else:
            atomic_json(path, value)

    def k(self, *args, data=None, timeout=60, plane='w'):
        config = 'management' if plane == 'm' else self.client.cluster
        return command(['kubectl', '--kubeconfig', self.client.state / 'kubeconfigs' / (config + '.yaml'),
                        *args], data=data, timeout=timeout)

    def obj(self, kind, name, namespace=True, plane='w'):
        args = ['get', kind, name, '--ignore-not-found', '-o', 'json']
        if namespace:
            args += ['-n', self.ns if plane == 'w' else self.client.ns]
        raw = self.k(*args, plane=plane)
        return json.loads(raw) if raw.strip() else None

    def remote(self, script, *, host=None, timeout=120, data=None):
        args = ['gcloud', 'compute', 'ssh', os.environ['TARGET_SSH_USER'] + '@' + (host or os.environ['CONTROLLER_NAME']),
                '--project=' + os.environ['GCP_PROJECT_ID'], '--zone=' + os.environ['GCP_ZONE'], '--quiet']
        if os.environ.get('GCP_USE_IAP_TUNNEL') == 'yes':
            args.append('--tunnel-through-iap')
        return command([*args, '--command=' + shlex.join(['bash', '-lc', script])], timeout=timeout, data=data)

    def admin(self, *args, **kwargs):
        return self.cloud.admin(*args, **kwargs)

    def admin_json(self, *args, **kwargs):
        return self.cloud.admin_json(*args, **kwargs)

    def apply(self, obj):
        return self.k('apply', '-f', '-', data=json.dumps(obj))

    def ownership(self):
        env = self.s1.environment()
        cluster = self.client.get('m', 'cluster', self.client.cluster, '-n', self.client.ns)
        if self.record['environment_run_id'] != env['run_id'] or self.record['cluster_uid'] != cluster['metadata']['uid']:
            raise RuntimeError('experiment belongs to another environment/cluster')
        ns = self.obj('namespace', self.ns, False)
        if ns and (ns['metadata'].get('labels', {}).get(LABEL) != self.record['run_id'] or
                   (self.record.get('namespace_uid') and ns['metadata']['uid'] != self.record['namespace_uid'])):
            raise RuntimeError('namespace ownership changed')

    def start(self):
        self.acquire()
        if self.record and self.record['phase'] != 'cleaned':
            raise RuntimeError('unfinished ' + self.scenario + '; cleanup first')
        for name, allowed in [('s1-preparation.json', 'restored'), ('s4-preparation.json', 'restored'),
                              ('s2-experiment.json', 'cleaned'), ('s3-experiment.json', 'cleaned')]:
            path = self.client.state / name
            if path != self.state and path.exists() and json.loads(path.read_text()).get('phase') != allowed:
                raise RuntimeError('another scenario is active: ' + name)
        env = self.s1.environment()
        mode, observed = self.s1.worker()
        if self.obj('namespace', self.ns, False):
            raise RuntimeError('scenario namespace already exists')
        self.record = {'run_id': self.scenario + '-' + uuid.uuid4().hex[:12], 'created': utc_now(),
                       'environment_run_id': env['run_id'], 'cluster_uid': observed['cluster_uid'],
                       'md_uid': observed['md_uid'], 'original_mode': mode,
                       'original_workers': observed['workers'],
                       'evidence': str(artifact_dir('graduation-' + self.scenario))}
        source_files = [ROOT / 'scripts' / name for name in ('graduation_recovery.py', 'graduation_env.py', 'workload_state.py', 'worker_control.py', 'graduation_s1.py', 'graduation_s1_contention.py', 'graduation_' + self.scenario + '.py')]
        source_files += list((ROOT / 'scripts').glob('graduation-' + self.scenario + '*.sh'))
        self.record['source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
        source_dir = Path(self.record['evidence']) / 'source'
        source_dir.mkdir()
        for name in self.record['source_sha256']:
            (source_dir / Path(name).name).write_bytes((ROOT / name).read_bytes())
        for path in (ROOT / 'kubernetes' / self.ns).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                relative = path.relative_to(ROOT)
                self.record['source_sha256'][str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
                destination = source_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(path.read_bytes())
        self.write('preparing')
        if mode != 'fixed':
            command([ROOT / 'scripts/cluster-autoscaler.sh', 'mode', 'fixed'], timeout=480)
        if observed['workers'] != 2:
            command([ROOT / 'scripts/workload-cluster.sh', 'scale', '2'], timeout=4200)
        self.apply({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {
            'name': self.ns, 'labels': {LABEL: self.record['run_id']}}})
        self.write('namespace-created', namespace_uid=self.obj('namespace', self.ns, False)['metadata']['uid'])
        nodes = self.client.get('w', 'nodes')['items']
        workers = [n for n in nodes if 'node-role.kubernetes.io/control-plane' not in n['metadata'].get('labels', {})]
        if len(workers) != 2 or not all(condition(n, 'Ready') and not n['spec'].get('unschedulable') for n in workers):
            raise RuntimeError('two schedulable Ready workers required')
        bindings = [self.binding(n) for n in sorted(workers, key=lambda n: n['metadata']['name'])]
        self.write('workers-ready', workers=bindings)
        return bindings

    def binding(self, node):
        machines = self.client.get('m', 'machines', '-n', self.client.ns)['items']
        matched = [m for m in machines if not m['metadata'].get('deletionTimestamp') and
                   m.get('status', {}).get('nodeRef', {}).get('name') == node['metadata']['name']]
        if len(matched) != 1:
            raise RuntimeError('ambiguous Node/Machine mapping')
        machine = matched[0]
        provider = machine.get('spec', {}).get('providerID', '')
        if not provider.startswith('openstack:///') or node['spec'].get('providerID') != provider:
            raise RuntimeError('Node/Machine provider identity mismatch')
        nova = self.admin_json('server', 'show', provider.removeprefix('openstack:///'))
        ports = self.admin_json('port', 'list', '--server', nova['id'])
        if nova['status'] != 'ACTIVE' or len(ports) != 1:
            raise RuntimeError('one ACTIVE VM and one unambiguous port required')
        port = self.admin_json('port', 'show', ports[0]['ID'])
        if port['device_id'] != nova['id'] or len(port['fixed_ips']) != 1:
            raise RuntimeError('VM/port identity mismatch')
        return {'node': node['metadata']['name'], 'node_uid': node['metadata']['uid'],
                'machine': machine['metadata']['name'], 'machine_uid': machine['metadata']['uid'],
                'nova_id': nova['id'], 'host': nova['OS-EXT-SRV-ATTR:host'],
                'instance_name': nova['OS-EXT-SRV-ATTR:instance_name'],
                'project_id': nova['project_id'], 'port': port,
                'ip': port['fixed_ips'][0]['ip_address']}

    def restore_workers(self):
        with WorkerControl(self.client) as control:
            def settled():
                mode, observed = control.preflight()
                if observed['md_uid'] != self.record['md_uid']:
                    raise RuntimeError('MachineDeployment identity changed')
                if mode != 'fixed' and (mode, observed['workers']) != (
                        self.record['original_mode'], self.record['original_workers']):
                    raise RuntimeError('worker control changed outside this experiment')
                # Node Ready can precede CAPI availability after a fenced VM reboots.
                return (mode, observed) if control.stable_workers(observed) else False
            mode, observed = wait_for(settled, seconds=600)
            if (mode, observed['workers']) == (self.record['original_mode'], self.record['original_workers']):
                return
            if mode != 'fixed':
                raise RuntimeError('worker control changed outside this experiment')
        if observed['workers'] != self.record['original_workers']:
            command([ROOT / 'scripts/workload-cluster.sh', 'scale', str(self.record['original_workers'])], timeout=4200)
        if self.record['original_mode'] != 'fixed':
            command([ROOT / 'scripts/cluster-autoscaler.sh', 'mode', self.record['original_mode']], timeout=480)
        mode, observed = self.s1.worker()
        if (mode, observed['workers']) != (self.record['original_mode'], self.record['original_workers']):
            raise RuntimeError('worker restoration incomplete')

    def delete_namespace(self):
        self.ownership()
        self.k('delete', 'namespace', self.ns, '--ignore-not-found', '--wait=true', '--timeout=5m', timeout=330)


def wait_for(fn, seconds=300, interval=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(interval)
    raise TimeoutError('condition did not converge before deadline')
