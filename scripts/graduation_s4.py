#!/usr/bin/env python3
"""Prepare and verify the S4 worker-failure fixture; never inject a fault."""
from __future__ import annotations

import json
import os
from pathlib import Path
from string import Template
import sys
import time

from graduation_env import atomic_json, utc_now
from worker_control import WorkerControl
from workload_state import Client, artifact_dir, command, condition


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = 'graduation-s4'
NAMESPACE = EXPERIMENT
MHC_NAME = EXPERIMENT + '-worker'
HTTP_NAME = 'http'
LABEL_KEY = 'openstack-k8s.dev/experiment'


def owned(obj):
    return obj['metadata'].get('labels', {}).get(LABEL_KEY) == EXPERIMENT


def worker_machines(machines, cluster, md_name):
    selected = [machine for machine in machines if
                machine['metadata'].get('labels', {}).get('cluster.x-k8s.io/cluster-name') == cluster
                and machine['metadata'].get('labels', {}).get('cluster.x-k8s.io/deployment-name') == md_name]
    if len(selected) != 2 or any(not condition(machine, 'Ready') or
                                 machine['metadata'].get('deletionTimestamp') or
                                 not any(owner.get('kind') == 'MachineSet' for owner in
                                         machine['metadata'].get('ownerReferences', []))
                                 for machine in selected):
        raise RuntimeError('S4 requires exactly two healthy MachineSet-owned worker Machines')
    return selected


def target_identity(pods, workers):
    selected = [pod for pod in pods if not pod['metadata'].get('deletionTimestamp')]
    if len(selected) != 1 or not condition(selected[0], 'Ready'):
        raise RuntimeError('S4 requires exactly one Ready HTTP Pod')
    pod = selected[0]
    node = pod['spec'].get('nodeName')
    matches = [machine for machine in workers if machine.get('status', {}).get('nodeRef', {}).get('name') == node]
    if len(matches) != 1:
        raise RuntimeError('HTTP Pod Node does not map to exactly one S4 worker Machine')
    machine = matches[0]
    provider = machine.get('spec', {}).get('providerID', '')
    if not provider.startswith('openstack:///') or not provider.removeprefix('openstack:///'):
        raise RuntimeError('target worker has no valid OpenStack providerID')
    return {'pod': pod['metadata']['name'], 'pod_uid': pod['metadata']['uid'],
            'node': node, 'machine': machine['metadata']['name'],
            'machine_uid': machine['metadata']['uid'],
            'nova_id': provider.removeprefix('openstack:///')}


def archive_restored_record(state_dir, previous):
    if not previous or previous.get('phase') != 'restored':
        return previous
    archive = state_dir / 'graduation-s4-history' / (
        previous['environment_run_id'] + '-' + previous['created'].replace(':', '') + '.json')
    if not archive.exists():
        atomic_json(archive, previous)
    return None


class S4Preparation:
    def __init__(self, client=None):
        self.client = client or Client()
        self.state_dir = self.client.state
        self.record_path = self.state_dir / 's4-preparation.json'
        self.management = self.state_dir / 'kubeconfigs/management.yaml'
        self.workload = self.state_dir / 'kubeconfigs' / (self.client.cluster + '.yaml')
        self.md_name = self.client.cluster + '-md-0'
        self.mhc_manifest = self.state_dir / 'generated/graduation-s4-mhc.yaml'
        self.app_manifest = ROOT / 'kubernetes/graduation-s4/http-service.yaml'

    def record(self, data, phase, **values):
        data.update(values)
        data['phase'] = phase
        data['updated'] = utc_now()
        atomic_json(self.record_path, data)
        print('S4 preparation: ' + phase, flush=True)

    def read(self):
        return json.loads(self.record_path.read_text()) if self.record_path.exists() else None

    def k(self, plane, *args, data=None, timeout=90):
        kubeconfig = self.management if plane == 'm' else self.workload
        return command(['kubectl', '--kubeconfig', kubeconfig, '--request-timeout=20s', *args],
                       data=data, timeout=timeout)

    def object(self, plane, resource, name, namespace=None):
        args = ['get', resource, name]
        if namespace:
            args += ['-n', namespace]
        result = self.k(plane, *args, '--ignore-not-found', '-o', 'json')
        return json.loads(result) if result.strip() else None

    def environment_record(self):
        path = self.state_dir / 'graduation-environment.json'
        if not path.is_file():
            raise RuntimeError('run graduation-env-ensure before S4 preparation')
        record = json.loads(path.read_text())
        expected = {'environment': os.environ['ENVIRONMENT_NAME'],
                    'project': os.environ['GCP_PROJECT_ID'], 'zone': os.environ['GCP_ZONE'],
                    'cluster': self.client.cluster}
        if record.get('phase') != 'ready' or record.get('profile') != expected:
            raise RuntimeError('environment record is not Ready for this profile')
        return record

    def preflight(self):
        environment = self.environment_record()
        command([ROOT / 'scripts/gcp-workload-api-tunnel.sh', 'ensure'], timeout=180)
        with WorkerControl(self.client) as control:
            mode, observed = control.preflight()
            if not control.stable_workers(observed):
                raise RuntimeError('worker MachineDeployment is not stable')
            if observed['cluster_uid'] != environment['ready']['cluster_uid'] or\
                    observed['md_uid'] != environment['ready']['md_uid']:
                raise RuntimeError('worker identity differs from environment preparation')
            return mode, observed

    def render_and_validate(self):
        self.mhc_manifest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        template = (ROOT / 'kubernetes/graduation-s4/machine-health-check.yaml.tpl').read_text()
        rendered = Template(template).substitute(WORKLOAD_NAMESPACE=self.client.ns,
                                                WORKLOAD_CLUSTER_NAME=self.client.cluster)
        self.mhc_manifest.write_text(rendered)
        self.mhc_manifest.chmod(0o600)
        self.k('m', 'apply', '--dry-run=server', '-f', self.mhc_manifest)
        self.k('w', 'apply', '--dry-run=client', '-f', self.app_manifest)
        return rendered

    def require_unowned_absent(self):
        for plane, resource, name, namespace in (
            ('m', 'machinehealthcheck', MHC_NAME, self.client.ns),
            ('w', 'namespace', NAMESPACE, None),
            ('w', 'configmap', 'http-content', NAMESPACE),
            ('w', 'deployment', HTTP_NAME, NAMESPACE),
            ('w', 'service', HTTP_NAME, NAMESPACE),
        ):
            obj = self.object(plane, resource, name, namespace)
            if obj and not owned(obj):
                raise RuntimeError(f'{resource}/{name} exists without S4 ownership label')
        checks = self.client.get('m', 'machinehealthchecks', '-n', self.client.ns).get('items', [])
        other = [item['metadata']['name'] for item in checks if
                 item['metadata']['name'] != MHC_NAME and
                 item.get('spec', {}).get('clusterName') == self.client.cluster]
        if other:
            raise RuntimeError(f'existing MachineHealthChecks require overlap review: {other}')

    def ensure_two_fixed_workers(self):
        mode, observed = self.preflight()
        if mode != 'fixed':
            command([ROOT / 'scripts/cluster-autoscaler.sh', 'mode', 'fixed'], timeout=480)
        if observed['workers'] != 2:
            command([ROOT / 'scripts/workload-cluster.sh', 'scale', '2'], timeout=4200)
        mode, observed = self.preflight()
        if mode != 'fixed' or observed['workers'] != 2:
            raise RuntimeError('S4 worker mode and count did not converge to fixed/2')

    def verify_mhc(self):
        machines = self.client.get('m', 'machines', '-n', self.client.ns,
                                   '-l', 'cluster.x-k8s.io/cluster-name=' + self.client.cluster)['items']
        workers = worker_machines(machines, self.client.cluster, self.md_name)
        cp = [machine for machine in machines if machine not in workers]
        if len(cp) != 1:
            raise RuntimeError('expected exactly one control-plane Machine outside S4 MHC selector')
        mhc = self.object('m', 'machinehealthcheck', MHC_NAME, self.client.ns)
        if not mhc or not owned(mhc):
            raise RuntimeError('S4 worker MachineHealthCheck is missing or unowned')
        selector = mhc['spec']['selector'].get('matchLabels', {})
        expected = {'cluster.x-k8s.io/deployment-name': self.md_name}
        if selector != expected or mhc['spec'].get('clusterName') != self.client.cluster:
            raise RuntimeError('S4 MHC selector or cluster name differs from the verified workers')
        if any(all(machine['metadata'].get('labels', {}).get(k) == v for k, v in selector.items()) for machine in cp):
            raise RuntimeError('S4 MHC also selects the control plane')
        status = mhc.get('status', {})
        if status.get('expectedMachines') != 2 or status.get('currentHealthy') != 2:
            raise RuntimeError(f'S4 MHC has not observed two healthy workers: {status}')
        return workers, mhc

    def wait_mhc(self, seconds=180):
        deadline = time.monotonic() + seconds
        last_error = None
        while time.monotonic() < deadline:
            try:
                return self.verify_mhc()
            except RuntimeError as exc:
                last_error = str(exc)
            time.sleep(5)
        raise TimeoutError(last_error or 'MHC did not converge')

    def verify_http(self, workers):
        deployment = self.object('w', 'deployment', HTTP_NAME, NAMESPACE)
        service = self.object('w', 'service', HTTP_NAME, NAMESPACE)
        pods = self.client.get('w', 'pods', '-n', NAMESPACE,
                               '-l', 'app=graduation-s4-http')['items']
        if not deployment or not service or not owned(deployment) or not owned(service):
            raise RuntimeError('S4 HTTP Deployment or Service missing/ownership mismatch')
        if deployment['spec'].get('replicas') != 1 or deployment.get('status', {}).get('readyReplicas') != 1:
            raise RuntimeError('S4 HTTP Deployment is not one Ready replica')
        target = target_identity(pods, workers)
        path = f'/api/v1/namespaces/{NAMESPACE}/services/{HTTP_NAME}:http/proxy/healthz'
        samples = []
        for _ in range(5):
            started = time.monotonic()
            body = self.k('w', 'get', '--raw=' + path, timeout=30)
            samples.append({'time': utc_now(), 'latency_ms': round((time.monotonic() - started) * 1000, 2),
                            'body': body.strip()})
            if body.strip() != 'ok':
                raise RuntimeError('S4 HTTP service proxy did not return ok')
        return target, deployment, service, samples

    def verify(self):
        record = self.read()
        if not record or record.get('phase') != 'prepared':
            raise RuntimeError('S4 fixture has not been prepared')
        mode, observed = self.preflight()
        if mode != 'fixed' or observed['workers'] != 2 or not WorkerControl.stable_workers(observed):
            raise RuntimeError('S4 worker control is not fixed/2 and stable')
        workers, mhc = self.verify_mhc()
        target, deployment, service, samples = self.verify_http(workers)
        if record['target']['machine_uid'] != target['machine_uid']:
            raise RuntimeError('S4 target changed since preparation')
        result = {'time': utc_now(), 'state': 'ready', 'target': target,
                  'mhc_uid': mhc['metadata']['uid'],
                  'deployment_uid': deployment['metadata']['uid'],
                  'service_uid': service['metadata']['uid'], 'http_samples': samples}
        if 'result' in record and 'evidence_dir' in record['result']:
            evidence = Path(record['result']['evidence_dir'])
            atomic_json(evidence / 'verification.json', result)
            atomic_json(evidence / 'mhc.json', mhc)
            atomic_json(evidence / 'worker-machines.json', workers)
        return result

    def prepare(self):
        environment = self.environment_record()
        previous = archive_restored_record(self.state_dir, self.read())
        if previous and previous.get('phase') == 'prepared':
            result = self.verify()
            print(json.dumps(result, indent=2))
            return result
        mode, observed = self.preflight()
        if previous:
            if previous.get('environment_run_id') != environment['run_id'] or\
                    previous.get('cluster_uid') != observed['cluster_uid'] or\
                    previous.get('md_uid') != observed['md_uid']:
                raise RuntimeError('S4 preparation record belongs to another environment or cluster')
            record = previous
        else:
            record = {'version': 1, 'created': utc_now(),
                      'environment_run_id': environment['run_id'],
                      'cluster_uid': observed['cluster_uid'], 'md_uid': observed['md_uid'],
                      'original_mode': mode, 'original_workers': observed['workers']}
        try:
            self.render_and_validate()
            self.require_unowned_absent()
            self.record(record, 'validated')
            self.ensure_two_fixed_workers()
            self.record(record, 'workers-ready')
            machines = self.client.get('m', 'machines', '-n', self.client.ns,
                                       '-l', 'cluster.x-k8s.io/cluster-name=' + self.client.cluster)['items']
            worker_machines(machines, self.client.cluster, self.md_name)
            self.k('m', 'apply', '-f', self.mhc_manifest)
            workers, mhc = self.wait_mhc()
            self.record(record, 'mhc-ready', mhc_uid=mhc['metadata']['uid'])
            self.k('w', 'apply', '-f', self.app_manifest)
            self.k('w', '-n', NAMESPACE, 'rollout', 'status', 'deployment/' + HTTP_NAME,
                   '--timeout=10m', timeout=660)
            target, deployment, service, samples = self.verify_http(workers)
            evidence = artifact_dir('graduation-s4-preparation')
            self.client.snapshot(evidence / 'baseline.json')
            atomic_json(evidence / 'mhc.json', mhc)
            atomic_json(evidence / 'worker-machines.json', workers)
            atomic_json(evidence / 'http-deployment.json', deployment)
            atomic_json(evidence / 'http-service.json', service)
            result = {'time': utc_now(), 'state': 'ready', 'target': target,
                      'mhc_uid': mhc['metadata']['uid'],
                      'deployment_uid': deployment['metadata']['uid'],
                      'service_uid': service['metadata']['uid'],
                      'http_samples': samples, 'evidence_dir': str(evidence)}
            atomic_json(evidence / 'result.json', result)
            self.record(record, 'prepared', target=target, result=result)
            print(json.dumps(result, indent=2), flush=True)
            return result
        except BaseException as exc:
            self.record(record, 'failed', error=f'{type(exc).__name__}: {exc}')
            raise

    def cleanup(self):
        record = self.read()
        if not record or record.get('phase') not in ('prepared', 'resources-removed', 'cleanup-failed'):
            raise RuntimeError('no prepared S4 fixture to clean up')
        environment = self.environment_record()
        if record['environment_run_id'] != environment['run_id']:
            raise RuntimeError('S4 fixture belongs to another environment run')
        mode, observed = self.preflight()
        if observed['cluster_uid'] != record['cluster_uid'] or observed['md_uid'] != record['md_uid']:
            raise RuntimeError('S4 fixture cluster identity changed; refusing cleanup')
        try:
            mhc = self.object('m', 'machinehealthcheck', MHC_NAME, self.client.ns)
            if mhc:
                if not owned(mhc) or mhc['metadata']['uid'] != record.get('mhc_uid'):
                    raise RuntimeError('S4 MHC ownership/UID changed; refusing cleanup')
                self.k('m', 'delete', 'machinehealthcheck', MHC_NAME, '-n', self.client.ns,
                       '--wait=true', '--timeout=3m', timeout=210)
            for resource, key in (('deployment', 'deployment_uid'), ('service', 'service_uid')):
                obj = self.object('w', resource, HTTP_NAME, NAMESPACE)
                if obj and (not owned(obj) or obj['metadata']['uid'] != record['result'][key]):
                    raise RuntimeError(f'S4 {resource} ownership/UID changed; refusing cleanup')
            namespace = self.object('w', 'namespace', NAMESPACE)
            if namespace and not owned(namespace):
                raise RuntimeError('S4 namespace ownership changed; refusing cleanup')
            if namespace:
                # This dedicated namespace is created by the manifest. Refuse to
                # remove it if another workload was added after preparation.
                resources = json.loads(self.k('w', 'get',
                                              'pods,deployments,services,configmaps,secrets,persistentvolumeclaims',
                                              '-n', NAMESPACE, '-o', 'json'))['items']
                foreign = [item['kind'] + '/' + item['metadata']['name'] for item in resources
                           if not owned(item) and not (
                               item['kind'] == 'ConfigMap' and item['metadata']['name'] == 'kube-root-ca.crt')]
                if foreign:
                    raise RuntimeError(f'S4 namespace contains foreign resources: {foreign}')
                self.k('w', 'delete', '-f', self.app_manifest, '--ignore-not-found=true',
                       '--wait=true', '--timeout=5m', timeout=330)
            self.record(record, 'resources-removed')
            original_workers = record['original_workers']
            if observed['workers'] != original_workers:
                command([ROOT / 'scripts/workload-cluster.sh', 'scale', str(original_workers)], timeout=4200)
            if mode != record['original_mode']:
                command([ROOT / 'scripts/cluster-autoscaler.sh', 'mode', record['original_mode']], timeout=480)
            final_mode, final = self.preflight()
            if final_mode != record['original_mode'] or final['workers'] != original_workers or\
                    not WorkerControl.stable_workers(final):
                raise RuntimeError('original worker control state did not converge')
            self.record(record, 'restored', restored_mode=final_mode,
                        restored_workers=final['workers'])
            return record
        except BaseException as exc:
            self.record(record, 'cleanup-failed', error=f'{type(exc).__name__}: {exc}')
            raise


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    preparation = S4Preparation()
    if action == 'prepare':
        preparation.prepare()
    elif action == 'verify':
        print(json.dumps(preparation.verify(), indent=2))
    elif action == 'cleanup':
        print(json.dumps(preparation.cleanup(), indent=2))
    elif action == 'status':
        print(json.dumps(preparation.read(), indent=2))
    else:
        raise SystemExit('usage: graduation_s4.py {prepare|verify|cleanup|status}')


if __name__ == '__main__':
    main()
