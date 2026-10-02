#!/usr/bin/env python3
"""Prepare an S1 HTTP fixture and measure its direct Service baseline."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import uuid

from graduation_env import atomic_json, utc_now
from worker_control import WorkerControl
from workload_state import Client, artifact_dir, command, condition


ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = 'graduation-s1'
LABEL = 'openstack-k8s.dev/experiment'
SOURCE = ROOT / 'kubernetes/graduation-s1'
MANIFEST = SOURCE / 'service.yaml'
IMAGE = 'python:3.12-alpine'
CPU_COUNTERS = ('usage_usec', 'user_usec', 'system_usec',
                'nr_periods', 'nr_throttled', 'throttled_usec')


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 3)


def host_cpu_utilization(before, after):
    deltas = [end - start for start, end in zip(before['cpu_ticks'], after['cpu_ticks'])]
    total = sum(deltas)
    if len(deltas) != 8 or total <= 0 or any(value < 0 for value in deltas):
        raise RuntimeError('invalid compute host CPU counter delta')
    return round((total - deltas[3] - deltas[4]) / total, 5)


def host_cpu_pressure(before, after):
    def total(snapshot):
        line = next(line for line in snapshot['cpu_pressure'] if line.startswith('some '))
        return int(next(part.removeprefix('total=') for part in line.split()
                        if part.startswith('total=')))
    elapsed = (dt.datetime.fromisoformat(after['time']) -
               dt.datetime.fromisoformat(before['time'])).total_seconds()
    delta = total(after) - total(before)
    if elapsed <= 0 or delta < 0:
        raise RuntimeError('invalid compute host CPU pressure delta')
    return round(delta / (elapsed * 1_000_000), 5)


def pod_cpu_delta(before, after):
    errors = []
    for label, sample in (('before', before), ('after', after)):
        if sample.get('error'):
            errors.append(f'{label}: {sample["error"]}')
        missing = [key for key in CPU_COUNTERS if type(sample.get(key)) is not int or
                   sample[key] < 0]
        if missing:
            errors.append(f'{label}: missing or invalid CPU counters: {", ".join(missing)}')
    if errors:
        return {}, errors
    delta = {key: after[key] - before[key] for key in CPU_COUNTERS}
    reset = [key for key, value in delta.items() if value < 0]
    if reset:
        return {}, ['CPU counters decreased or reset: ' + ', '.join(reset)]
    return delta, []


def analyze_rows(rows, rate, measure_seconds, warmup_seconds=0):
    measured = sorted((row for row in rows if row.get('phase') == 'measure'),
                      key=lambda row: row['index'])
    expected_indexes = {index for index in range(int((warmup_seconds + measure_seconds) * rate))
                        if index / rate >= warmup_seconds}
    expected = len(expected_indexes)
    indexes = [row['index'] for row in measured]
    successes = [row for row in measured if row.get('ok')]
    latencies = [row['latency_ms'] for row in successes]
    by_time = sorted(measured, key=lambda row: row['time'])
    gaps = [round((dt.datetime.fromisoformat(b['time']) -
                   dt.datetime.fromisoformat(a['time'])).total_seconds(), 3)
            for a, b in zip(by_time, by_time[1:])]
    return {'expected_requests': expected, 'requests': len(measured),
            'successes': len(successes), 'failures': len(measured) - len(successes),
            'missing_or_duplicate_indexes': set(indexes) != expected_indexes or len(indexes) != expected,
            'success_rate': round(len(successes) / len(measured), 5) if measured else None,
            'successful_rps': round(len(successes) / measure_seconds, 3),
            'latency_ms': {'p50': percentile(latencies, .5),
                           'p95': percentile(latencies, .95),
                           'p99': percentile(latencies, .99)},
            'max_sample_start_gap_seconds': max(gaps, default=None),
            'errors': {kind: sum(row.get('error') == kind for row in measured)
                       for kind in sorted({row.get('error') for row in measured if row.get('error')})}}


class S1:
    def __init__(self, client=None):
        self.client = client or Client()
        self.path = self.client.state / 's1-preparation.json'
        self.lock_path = self.client.state / 's1-preparation.lock'
        self.workload = self.client.state / 'kubeconfigs' / (self.client.cluster + '.yaml')

    def read(self):
        return json.loads(self.path.read_text()) if self.path.exists() else None

    def write(self, record, phase, **values):
        record.update(values)
        record['phase'] = phase
        record['updated'] = utc_now()
        atomic_json(self.path, record)

    def k(self, *args, data=None, timeout=60):
        return command(['kubectl', '--kubeconfig', self.workload,
                        '--request-timeout=20s', *args], data=data, timeout=timeout)

    def obj(self, kind, name, namespace=NAMESPACE):
        args = ['get', kind, name]
        if namespace:
            args += ['-n', namespace]
        raw = self.k(*args, '--ignore-not-found', '-o', 'json')
        return json.loads(raw) if raw.strip() else None

    def environment(self):
        path = self.client.state / 'graduation-environment.json'
        if not path.exists():
            raise RuntimeError('run graduation-env-ensure first')
        data = json.loads(path.read_text())
        profile = {'environment': os.environ['ENVIRONMENT_NAME'],
                   'project': os.environ['GCP_PROJECT_ID'], 'zone': os.environ['GCP_ZONE'],
                   'cluster': self.client.cluster}
        if data.get('phase') != 'ready' or data.get('profile') != profile:
            raise RuntimeError('environment is not Ready for the selected profile')
        return data

    def worker(self):
        with WorkerControl(self.client) as control:
            mode, observed = control.preflight()
            if not control.stable_workers(observed):
                raise RuntimeError('worker MachineDeployment is unstable')
            return mode, observed

    def require_identity(self, record):
        env = self.environment()
        mode, observed = self.worker()
        if record['environment_run_id'] != env['run_id'] or\
                record['cluster_uid'] != observed['cluster_uid'] or\
                record['md_uid'] != observed['md_uid']:
            raise RuntimeError('S1 record belongs to another environment/cluster')
        return mode, observed

    def ensure_absent(self):
        for name in ('s2-experiment.json', 's3-experiment.json'):
            path = self.client.state / name
            if path.exists() and json.loads(path.read_text()).get('phase') != 'cleaned':
                raise RuntimeError('another scenario is active: ' + name)
        namespace = self.obj('namespace', NAMESPACE, None)
        if namespace:
            raise RuntimeError('graduation-s1 namespace already exists; inspect ownership first')
        other = self.client.state / 's4-preparation.json'
        if other.exists() and json.loads(other.read_text()).get('phase') != 'restored':
            raise RuntimeError('S4 fixture is active; clean it before S1')

    def verify(self):
        record = self.read()
        if not record or record['phase'] != 'prepared':
            raise RuntimeError('S1 fixture is not prepared')
        mode, observed = self.require_identity(record)
        if mode != 'fixed' or observed['workers'] != 2:
            raise RuntimeError('S1 requires fixed mode and two workers')
        deployment = self.obj('deployment', 'http')
        service = self.obj('service', 'http')
        config = self.obj('configmap', 's1-code')
        pods = self.client.get('w', 'pods', '-n', NAMESPACE,
                               '-l', 'app=graduation-s1-http')['items']
        selected = [p for p in pods if not p['metadata'].get('deletionTimestamp')]
        if any(not obj or obj['metadata'].get('labels', {}).get(LABEL) != NAMESPACE
               for obj in (deployment, service, config)):
            raise RuntimeError('S1 HTTP resources missing or ownership changed')
        if deployment.get('status', {}).get('readyReplicas') != 1 or len(selected) != 1 or\
                not condition(selected[0], 'Ready'):
            raise RuntimeError('S1 HTTP Pod is not Ready')
        pod = selected[0]
        container = next((item for item in pod['status'].get('containerStatuses', [])
                          if item.get('name') == 'http'), None)
        if not container or not container.get('containerID') or not container.get('imageID'):
            raise RuntimeError('S1 HTTP container identity is unavailable')
        nodes = self.client.get('w', 'nodes')['items']
        node = next((n for n in nodes if n['metadata']['name'] == pod['spec']['nodeName']), None)
        if not node or not condition(node, 'Ready'):
            raise RuntimeError('S1 HTTP Node is not Ready')
        machines = self.client.get('m', 'machines', '-n', self.client.ns,
                                   '-l', 'cluster.x-k8s.io/cluster-name=' + self.client.cluster)['items']
        machine = next((m for m in machines if m.get('status', {}).get('nodeRef', {}).get('name') == pod['spec']['nodeName']), None)
        if not machine or not machine.get('spec', {}).get('providerID', '').startswith('openstack:///'):
            raise RuntimeError('S1 Pod Node does not map to a Nova VM')
        return {'time': utc_now(), 'state': 'ready', 'pod': pod['metadata']['name'],
                'pod_uid': pod['metadata']['uid'], 'node': pod['spec']['nodeName'],
                'machine_uid': machine['metadata']['uid'],
                'nova_id': machine['spec']['providerID'].removeprefix('openstack:///'),
                'image_id': container['imageID'],
                'container_id': container['containerID'],
                'restart_count': container.get('restartCount', 0),
                'service_uid': service['metadata']['uid']}

    def prepare(self):
        self.client.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            prior = self.read()
            if prior and prior['phase'] == 'prepared':
                return self.verify()
            if prior and prior['phase'] != 'restored':
                raise RuntimeError('unfinished S1 preparation exists; clean it first')
            env = self.environment()
            mode, observed = self.worker()
            self.ensure_absent()
            record = {'version': 1, 'run_id': 's1-prep-' + uuid.uuid4().hex[:12],
                      'created': utc_now(), 'environment_run_id': env['run_id'],
                      'cluster_uid': observed['cluster_uid'], 'md_uid': observed['md_uid'],
                      'original_mode': mode, 'original_workers': observed['workers']}
            self.write(record, 'starting')
            try:
                self.k('apply', '--dry-run=client', '-f', MANIFEST)
                if mode != 'fixed':
                    command([ROOT / 'scripts/cluster-autoscaler.sh', 'mode', 'fixed'], timeout=480)
                if observed['workers'] != 2:
                    command([ROOT / 'scripts/workload-cluster.sh', 'scale', '2'], timeout=4200)
                self.write(record, 'workers-ready')
                self.write(record, 'app-applying', app_apply_intent=True)
                self.k('apply', '-f', MANIFEST, timeout=180)
                source = {name: (SOURCE / name).read_text() for name in ('app.py', 'loadgen.py')}
                config = {'apiVersion': 'v1', 'kind': 'ConfigMap',
                          'metadata': {'name': 's1-code', 'namespace': NAMESPACE,
                                       'labels': {LABEL: NAMESPACE}}, 'data': source}
                self.k('apply', '-f', '-', data=json.dumps(config), timeout=120)
                self.k('-n', NAMESPACE, 'rollout', 'status', 'deployment/http',
                       '--timeout=10m', timeout=660)
                self.write(record, 'prepared', resource_uids={
                    kind: self.obj(kind, name)['metadata']['uid'] for kind, name in
                    (('deployment', 'http'), ('service', 'http'), ('configmap', 's1-code'))},
                           namespace_uid=self.obj('namespace', NAMESPACE, None)['metadata']['uid'])
                result = self.verify()
                self.write(record, 'prepared', verification=result)
                return result
            except BaseException as exc:
                self.write(record, 'failed', error=f'{type(exc).__name__}: {exc}')
                raise

    def baseline(self, rate, rounds, warmup, measure, timeout, max_inflight):
        if not 10000 <= rounds <= 1000000 or not 0 < rate <= 50 or\
                not 0 <= warmup <= 600 or not 1 <= measure <= 1800 or\
                not 0 < timeout <= 30 or not 1 <= max_inflight <= 200:
            raise ValueError('baseline parameters outside safe range')
        self.client.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self._baseline_locked(rate, rounds, warmup, measure, timeout, max_inflight)

    def _baseline_locked(self, rate, rounds, warmup, measure, timeout, max_inflight):
        verification = self.verify()
        jobs = self.client.get('w', 'jobs', '-n', NAMESPACE,
                               '-l', LABEL + '=' + NAMESPACE)['items']
        if jobs:
            raise RuntimeError('an earlier S1 Job remains; clean it before another baseline')
        nodes = self.client.get('w', 'nodes')['items']
        cp = [n for n in nodes if
              'node-role.kubernetes.io/control-plane' in n['metadata'].get('labels', {})]
        if len(cp) != 1 or not condition(cp[0], 'Ready'):
            raise RuntimeError('exactly one Ready control plane is required for direct Service probing')
        alternatives = [n for n in nodes if n['metadata']['name'] != verification['node'] and
                        'node-role.kubernetes.io/control-plane' not in n['metadata'].get('labels', {})
                        and condition(n, 'Ready')]
        if len(alternatives) != 1:
            raise RuntimeError('exactly one other Ready worker is required for S1')
        machines = self.client.get('m', 'machines', '-n', self.client.ns,
                                   '-l', 'cluster.x-k8s.io/cluster-name=' + self.client.cluster)['items']
        def nova_id_for(node):
            machine = next((m for m in machines if
                            m.get('status', {}).get('nodeRef', {}).get('name') ==
                            node['metadata']['name']), None)
            if not machine or not machine.get('spec', {}).get('providerID', '').startswith('openstack:///'):
                raise RuntimeError('S1 Node does not map to a Nova VM: ' + node['metadata']['name'])
            return machine['spec']['providerID'].removeprefix('openstack:///')
        probe_nova_id = nova_id_for(cp[0])
        alternate_nova_id = nova_id_for(alternatives[0])
        before_placement = {'service': self.placement(verification['nova_id']),
                            'probe': self.placement(probe_nova_id),
                            'alternate_worker': self.placement(alternate_nova_id)}
        evidence = artifact_dir('graduation-s1-baseline')
        atomic_json(evidence / 'placement-before.json', before_placement)
        record = {'version': 1, 'run_id': 's1-' + uuid.uuid4().hex[:12],
                  'created': utc_now(), 'preparation_id': self.read()['run_id'],
                  'environment_run_id': self.environment()['run_id'],
                  'service': verification, 'probe_node': cp[0]['metadata']['name'],
                  'probe_nova_id': probe_nova_id,
                  'alternate_node': alternatives[0]['metadata']['name'],
                  'alternate_nova_id': alternate_nova_id,
                  'config': {'rate': rate, 'rounds': rounds, 'warmup_seconds': warmup,
                             'measure_seconds': measure, 'timeout_seconds': timeout,
                             'max_inflight': max_inflight},
                  'source_sha256': {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
                                    for name in ('app.py', 'loadgen.py', 'service.yaml')}}
        atomic_json(evidence / 'run.json', record)
        before_infra = self.client.snapshot(evidence / 'infrastructure-before.json')
        before_cpu = self.cpu_stat(verification['pod'])
        atomic_json(evidence / 'pod-cpu-before.json', before_cpu)
        hosts = sorted({item['compute_host'] for item in before_placement.values()})
        host_before = {host: self.host_stat(host) for host in hosts}
        atomic_json(evidence / 'compute-cpu-before.json', host_before)
        job_name = 's1-baseline-' + uuid.uuid4().hex[:8]
        url = f'http://http.{NAMESPACE}.svc.cluster.local:8080/work?rounds={rounds}'
        job = {'apiVersion': 'batch/v1', 'kind': 'Job',
               'metadata': {'name': job_name, 'namespace': NAMESPACE,
                            'labels': {LABEL: NAMESPACE}},
               'spec': {'backoffLimit': 0, 'template': {
                   'metadata': {'labels': {LABEL: NAMESPACE}},
                   'spec': {'nodeName': cp[0]['metadata']['name'],
                            'tolerations': [{'key': 'node-role.kubernetes.io/control-plane',
                                             'effect': 'NoSchedule', 'operator': 'Exists'}],
                            'restartPolicy': 'Never',
                            'containers': [{'name': 'loadgen', 'image': IMAGE,
                                            'command': ['python', '-B', '/app/loadgen.py'],
                                            'env': [{'name': 'S1_' + key, 'value': str(value)} for key, value in
                                                    {'URL': url, 'RATE': rate,
                                                     'WARMUP_SECONDS': warmup,
                                                     'MEASURE_SECONDS': measure,
                                                     'TIMEOUT_SECONDS': timeout,
                                                     'MAX_INFLIGHT': max_inflight}.items()],
                                            'resources': {'requests': {'cpu': '50m', 'memory': '64Mi'},
                                                          'limits': {'memory': '256Mi'}},
                                            'volumeMounts': [{'name': 'app', 'mountPath': '/app',
                                                              'readOnly': True}]}],
                            'volumes': [{'name': 'app', 'configMap': {'name': 's1-code'}}]}}}}
        atomic_json(evidence / 'job.json', job)
        record['job_name'] = job_name
        atomic_json(evidence / 'run.json', record)
        try:
            self.k('apply', '-f', '-', data=json.dumps(job))
            record['job_uid'] = self.obj('job', job_name)['metadata']['uid']
            atomic_json(evidence / 'run.json', record)
            self.k('-n', NAMESPACE, 'wait', '--for=condition=complete', 'job/' + job_name,
                   f'--timeout={warmup + measure + 180}s', timeout=warmup + measure + 210)
            probe_pods = self.client.get('w', 'pods', '-n', NAMESPACE,
                                         '-l', 'job-name=' + job_name)['items']
            if len(probe_pods) != 1 or probe_pods[0]['spec'].get('nodeName') != cp[0]['metadata']['name'] or\
                    probe_pods[0].get('status', {}).get('phase') != 'Succeeded':
                raise RuntimeError('baseline probe Pod did not finish on the selected control-plane Node')
            atomic_json(evidence / 'probe-pod.json', probe_pods[0])
            raw = self.k('-n', NAMESPACE, 'logs', 'job/' + job_name,
                         timeout=120)
            (evidence / 'http.jsonl').write_text(raw)
            rows = [json.loads(line) for line in raw.splitlines()]
            summary = analyze_rows(rows, rate, measure, warmup)
            after_cpu = self.cpu_stat(verification['pod'])
            atomic_json(evidence / 'pod-cpu-after.json', after_cpu)
            host_after = {host: self.host_stat(host) for host in hosts}
            atomic_json(evidence / 'compute-cpu-after.json', host_after)
            summary['pod_cpu_delta'], summary['pod_cpu_errors'] = pod_cpu_delta(before_cpu, after_cpu)
            summary['pod_cpu_valid'] = not summary['pod_cpu_errors']
            summary['compute_cpu_utilization'] = {
                host: host_cpu_utilization(host_before[host], host_after[host])
                for host in hosts}
            summary['compute_cpu_pressure_some'] = {
                host: host_cpu_pressure(host_before[host], host_after[host])
                for host in hosts}
            after_infra = self.client.snapshot(evidence / 'infrastructure-after.json')
            final_service = self.verify()
            after_placement = {'service': self.placement(final_service['nova_id']),
                               'probe': self.placement(probe_nova_id),
                               'alternate_worker': self.placement(alternate_nova_id)}
            atomic_json(evidence / 'placement-after.json', after_placement)
            summary['compute_placement_stable'] = before_placement == after_placement
            summary['service_compute_host'] = before_placement['service']['compute_host']
            summary['probe_compute_host'] = before_placement['probe']['compute_host']
            summary['probe_compute_distinct'] = (
                summary['service_compute_host'] != summary['probe_compute_host'])
            summary['alternate_compute_host'] = before_placement['alternate_worker']['compute_host']
            summary['alternate_compute_distinct'] = (
                summary['service_compute_host'] != summary['alternate_compute_host'])
            summary['service_identity_stable'] = (
                verification['pod_uid'] == final_service['pod_uid'] and
                verification['nova_id'] == final_service['nova_id'] and
                verification['image_id'] == final_service['image_id'] and
                verification['container_id'] == final_service['container_id'] and
                verification['restart_count'] == final_service['restart_count'])
            summary['infrastructure_errors'] = {'before': before_infra['errors'],
                                                'after': after_infra['errors']}
            summary['state'] = 'complete' if not summary['missing_or_duplicate_indexes'] and\
                not summary['failures'] and summary['requests'] >= 20 and\
                summary['service_identity_stable'] and summary['pod_cpu_valid'] and\
                summary['compute_placement_stable'] and\
                summary['probe_compute_distinct'] and summary['alternate_compute_distinct'] and\
                not before_infra['errors'] and\
                not after_infra['errors'] and\
                (summary['max_sample_start_gap_seconds'] or 0) <= max(2.5, 3 / rate)\
                else 'needs_review'
            summary['probe_path'] = 'direct ClusterIP Service from workload control-plane Pod'
            summary['run_id'] = record['run_id']
            atomic_json(evidence / 'summary.json', summary)
            return {'evidence': str(evidence), **summary}
        except BaseException as exc:
            atomic_json(evidence / 'error.json', {'time': utc_now(),
                                                 'error': f'{type(exc).__name__}: {exc}'})
            try:
                (evidence / 'http.jsonl').write_text(
                    self.k('-n', NAMESPACE, 'logs', 'job/' + job_name, timeout=120))
            except (RuntimeError, TimeoutError):
                pass
            raise
        finally:
            obj = self.obj('job', job_name)
            if obj and obj['metadata'].get('labels', {}).get(LABEL) == NAMESPACE and\
                    (not record.get('job_uid') or obj['metadata']['uid'] == record['job_uid']):
                self.k('delete', 'job', job_name, '-n', NAMESPACE,
                       '--wait=true', '--timeout=3m', timeout=210)

    def cpu_stat(self, pod):
        try:
            raw = self.k('-n', NAMESPACE, 'exec', pod, '--',
                         'cat', '/sys/fs/cgroup/cpu.stat', timeout=60)
        except RuntimeError as exc:
            return {'error': f'{type(exc).__name__}: cgroup CPU counters unavailable'}
        return {parts[0]: int(parts[1]) for line in raw.splitlines()
                if len(parts := line.split()) == 2 and parts[1].isdigit()}

    def placement(self, nova_id):
        raw = command([ROOT / 'scripts/graduation-s1-placement.sh', nova_id], timeout=90)
        info = json.loads(raw)
        if info.get('id') != nova_id or info.get('status') != 'ACTIVE' or not info.get('OS-EXT-SRV-ATTR:host'):
            raise RuntimeError('Nova server placement is unavailable or changed')
        return {'nova_id': nova_id, 'compute_host': info['OS-EXT-SRV-ATTR:host'],
                'hypervisor': info.get('OS-EXT-SRV-ATTR:hypervisor_hostname'),
                'status': info['status']}

    @staticmethod
    def host_stat(host):
        return json.loads(command([ROOT / 'scripts/graduation-s1-host-stat.sh', host], timeout=90))

    def cleanup(self):
        self.client.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            record = self.read()
            if not record or record.get('version') != 1 or record.get('phase') not in (
                    'starting', 'workers-ready', 'app-applying', 'prepared', 'failed',
                    'resources-removed', 'cleanup-failed'):
                raise RuntimeError('no active S1 preparation to clean up')
            env = self.environment()
            if record['environment_run_id'] != env['run_id']:
                raise RuntimeError('S1 record belongs to another environment run')
            cluster = self.client.get('m', 'cluster', self.client.cluster, '-n', self.client.ns)
            md = self.client.get('m', 'machinedeployment', self.client.cluster + '-md-0',
                                 '-n', self.client.ns)
            if cluster['metadata']['uid'] != record['cluster_uid'] or\
                    md['metadata']['uid'] != record['md_uid']:
                raise RuntimeError('S1 cluster identity changed; refusing cleanup')
            resources_removed = False
            try:
                namespace = self.obj('namespace', NAMESPACE, None)
                if namespace:
                    if namespace['metadata'].get('labels', {}).get(LABEL) != NAMESPACE or\
                            not (record.get('app_apply_intent') or record.get('namespace_uid')) or\
                            (record.get('namespace_uid') and
                             record['namespace_uid'] != namespace['metadata']['uid']):
                        raise RuntimeError('S1 namespace ownership/UID changed')
                    resources = self.client.get('w', 'pods,replicasets,deployments,services,configmaps,secrets,persistentvolumeclaims,jobs',
                                                '-n', NAMESPACE)['items']
                    foreign = [x['kind'] + '/' + x['metadata']['name'] for x in resources
                               if x['metadata'].get('labels', {}).get(LABEL) != NAMESPACE and not
                               (x['kind'] == 'ConfigMap' and x['metadata']['name'] == 'kube-root-ca.crt')]
                    if foreign:
                        raise RuntimeError(f'S1 namespace contains foreign resources: {foreign}')
                    for kind, name in (('deployment', 'http'), ('service', 'http'), ('configmap', 's1-code')):
                        obj = self.obj(kind, name)
                        if obj:
                            uid = record.get('resource_uids', {}).get(kind)
                            if not (uid or record.get('app_apply_intent')) or\
                                    (uid and uid != obj['metadata']['uid']):
                                raise RuntimeError(f'S1 {kind} ownership/UID changed')
                    self.k('delete', 'namespace', NAMESPACE, '--wait=true', '--timeout=5m', timeout=330)
                self.write(record, 'resources-removed', resources_removed=True)
                resources_removed = True
                mode, observed = self.require_identity(record)
                if observed['workers'] != record['original_workers']:
                    command([ROOT / 'scripts/workload-cluster.sh', 'scale', str(record['original_workers'])],
                            timeout=4200)
                if mode != record['original_mode']:
                    command([ROOT / 'scripts/cluster-autoscaler.sh', 'mode', record['original_mode']], timeout=480)
                final_mode, final = self.worker()
                if final_mode != record['original_mode'] or final['workers'] != record['original_workers']:
                    raise RuntimeError('original worker state did not return')
                self.write(record, 'restored', final_mode=final_mode, final_workers=final['workers'])
                return record
            except BaseException as exc:
                self.write(record, 'cleanup-failed',
                           cleanup_stage='worker-restore' if resources_removed
                           else 'resource-removal',
                           error=f'{type(exc).__name__}: {exc}')
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'verify', 'baseline', 'cleanup', 'status'))
    parser.add_argument('--rate', type=float, default=5)
    parser.add_argument('--rounds', type=int, default=100000)
    parser.add_argument('--warmup', type=int, default=60)
    parser.add_argument('--measure', type=int, default=300)
    parser.add_argument('--timeout', type=float, default=5)
    parser.add_argument('--max-inflight', type=int, default=50)
    args = parser.parse_args()
    s1 = S1()
    if args.action == 'prepare':
        result = s1.prepare()
    elif args.action == 'verify':
        result = s1.verify()
    elif args.action == 'baseline':
        result = s1.baseline(args.rate, args.rounds, args.warmup, args.measure,
                             args.timeout, args.max_inflight)
    elif args.action == 'cleanup':
        result = s1.cleanup()
    else:
        result = s1.read()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
