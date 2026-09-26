#!/usr/bin/env python3
"""Inject one exact S4 Nova worker stop and preserve independent recovery evidence."""
from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

from graduation_env import atomic_json, utc_now
from graduation_s4 import (EXPERIMENT, HTTP_NAME, LABEL_KEY, MHC_NAME,
                           NAMESPACE, ROOT, S4Preparation, owned)
from worker_control import WorkerControl
from workload_state import Client, artifact_dir, command, condition, evaluate


HTTP_PATH = f'/api/v1/namespaces/{NAMESPACE}/services/{HTTP_NAME}:http/proxy/healthz'
NOVA = ROOT / 'scripts/graduation-s4-nova.sh'
OBSERVE_SECONDS = 2700
STABLE_SECONDS = 30


def unix_time(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def nova(action, server=None):
    args = [NOVA, action]
    if server:
        args.append(server)
    raw = command(args, timeout=100)
    return json.loads(raw) if action != 'stop' else None


def nova_status(server):
    row = nova('show', server)
    row = {key.lower(): value for key, value in row.items()}
    if row.get('id', '').lower() != server.lower():
        raise RuntimeError('Nova server show returned a different UUID')
    return row


def s4_host_budget(preparation_record):
    names = set(preparation_record['initial_hosts'])
    rows = json.loads(command(['gcloud', 'compute', 'instances', 'list',
                               '--project=' + os.environ['GCP_PROJECT_ID'],
                               '--filter=zone:(' + os.environ['GCP_ZONE'] + ')',
                               '--format=json'], timeout=60))
    current = {row['name']: row for row in rows if row['name'] in names}
    if set(current) != names:
        raise RuntimeError('not all exact GCP hosts exist before S4 injection')
    deadlines = []
    for name, row in current.items():
        initial = preparation_record['initial_hosts'][name]
        seconds = int(row.get('scheduling', {}).get('maxRunDuration', {}).get('seconds', 0))
        if str(row.get('id')) != initial['id'] or row.get('status') != 'RUNNING' or\
                not row.get('lastStartTimestamp') or seconds <= 0:
            raise RuntimeError('GCP host identity/state/budget mismatch: ' + name)
        deadlines.append(unix_time(row['lastStartTimestamp']) + seconds)
    return min(deadlines)


def http_probe(kubeconfig):
    started = time.monotonic()
    result = {'time': utc_now(), 'ok': False}
    try:
        body = command(['kubectl', '--kubeconfig', kubeconfig, '--request-timeout=5s',
                        'get', '--raw=' + HTTP_PATH], timeout=9).strip()
        result['body'] = body[:200]
        result['ok'] = body == 'ok'
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
        result['error'] = f'{type(exc).__name__}: {str(exc)[:300]}'
    result['latency_ms'] = round((time.monotonic() - started) * 1000, 2)
    return result


class ProbeSampler:
    def __init__(self, kubeconfig, path, period=1):
        self.kubeconfig, self.path, self.period = kubeconfig, path, period
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.samples = []
        self.error = None

    def loop(self):
        try:
            with self.path.open('a') as stream:
                while not self.stop.is_set():
                    sample = http_probe(self.kubeconfig)
                    stream.write(json.dumps(sample, ensure_ascii=False) + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                    self.samples.append(sample)
                    self.stop.wait(self.period)
        except BaseException as exc:
            self.error = f'{type(exc).__name__}: {exc}'

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=12)
        if self.thread.is_alive():
            self.error = 'HTTP sampler did not terminate'


def summarize_http(samples, injection, stable_seconds=STABLE_SECONDS):
    after = [row for row in samples if unix_time(row['time']) >= unix_time(injection)]
    if not after:
        return {'state': 'unavailable', 'reason': 'no HTTP samples after injection'}
    failures = [row for row in after if not row['ok']]
    if not failures:
        return {'state': 'no_observed_outage', 'requests': len(after), 'failed': 0,
                'service_recovered_at': None, 'outage_seconds': None}
    last_failure = failures[-1]
    later = [row for row in after if unix_time(row['time']) > unix_time(last_failure['time'])]
    if not later or not all(row['ok'] for row in later) or\
            unix_time(later[-1]['time']) - unix_time(later[0]['time']) < stable_seconds:
        return {'state': 'not_stable', 'requests': len(after), 'failed': len(failures),
                'first_failure_at': failures[0]['time'], 'last_failure_at': last_failure['time']}
    return {'state': 'recovered', 'requests': len(after), 'failed': len(failures),
            'first_failure_at': failures[0]['time'], 'last_failure_at': last_failure['time'],
            'service_recovered_at': later[0]['time'],
            'outage_seconds': round(unix_time(later[0]['time']) - unix_time(failures[0]['time']), 3)}


def summarize_capacity(observation, target, originals, probe_name):
    if observation.get('errors'):
        return {'state': 'unavailable', 'reasons': observation['errors']}
    machines = observation['machines']['items']
    workers = [m for m in machines if m['metadata'].get('labels', {}).get(
        'cluster.x-k8s.io/deployment-name') == observation['md']['metadata']['name']]
    old = [m for m in workers if m['metadata']['uid'] == target['machine_uid']]
    replacements = [m for m in workers if m['metadata']['uid'] not in originals]
    nodes = {n['metadata']['name']: n for n in observation['nodes']['items']}
    servers = {str(row.get('ID') or row.get('id', '')).lower(): row for row in observation['nova']}
    reasons = []
    if old:
        reasons.append('original Machine remains')
    if target['node'] in nodes:
        reasons.append('original Node remains')
    if target['nova_id'].lower() in servers:
        reasons.append('original Nova VM remains')
    if len(workers) != 2 or len(replacements) != 1:
        reasons.append('two workers with one replacement are not present')
    md = observation['md']
    if any(md.get('status', {}).get(k) != 2 for k in ('replicas', 'readyReplicas', 'availableReplicas')):
        reasons.append('MachineDeployment is not 2/2/2')
    replacement = replacements[0] if len(replacements) == 1 else None
    if replacement:
        node_name = replacement.get('status', {}).get('nodeRef', {}).get('name')
        provider = replacement.get('spec', {}).get('providerID', '')
        server_id = provider.removeprefix('openstack:///') if provider.startswith('openstack:///') else ''
        if not condition(replacement, 'Ready') or not node_name or not condition(nodes.get(node_name, {}), 'Ready'):
            reasons.append('replacement Machine/Node not Ready')
        if not server_id or str(servers.get(server_id.lower(), {}).get('Status') or
                                servers.get(server_id.lower(), {}).get('status', '')).upper() != 'ACTIVE':
            reasons.append('replacement Nova VM not ACTIVE')
    else:
        node_name, server_id = None, None
    if any(not condition(m, 'Ready') or not condition(nodes.get(m.get('status', {}).get(
            'nodeRef', {}).get('name'), {}), 'Ready') for m in workers):
        reasons.append('not all worker Machines/Nodes are Ready')
    app = observation['deployment']
    service_pods = [p for p in observation['pods']['items'] if
                    p['metadata'].get('labels', {}).get('app') == 'graduation-s4-http'
                    and not p['metadata'].get('deletionTimestamp')]
    if app.get('status', {}).get('readyReplicas') != 1 or len(service_pods) != 1 or\
            not condition(service_pods[0], 'Ready') or\
            service_pods[0]['spec'].get('nodeName') == target['node']:
        reasons.append('HTTP Pod is not Ready on a surviving worker')
    osms = observation['osmachines']['items']
    if any(m['metadata']['name'] == target.get('osmachine') for m in osms):
        reasons.append('original OpenStackMachine remains')
    probes = [p for p in observation['pods']['items'] if p['metadata']['name'] == probe_name]
    if not probes or not condition(probes[0], 'Ready') or probes[0]['spec'].get('nodeName') != node_name:
        reasons.append('new worker HTTP probe not Ready')
    return {'state': 'recovered' if not reasons else 'pending', 'reasons': reasons,
            'replacement': {'machine': replacement['metadata']['name'],
                            'machine_uid': replacement['metadata']['uid'],
                            'node': node_name, 'nova_id': server_id} if replacement else None}


class S4Run:
    def __init__(self, preparation=None):
        self.preparation = preparation or S4Preparation()
        self.client = self.preparation.client
        self.record_path = self.client.state / 's4-experiment.json'
        self.lock_path = self.client.state / 's4-experiment.lock'

    def read(self):
        return json.loads(self.record_path.read_text()) if self.record_path.exists() else None

    def write(self, record, phase, **values):
        record.update(values)
        record['phase'] = phase
        record['updated'] = utc_now()
        atomic_json(self.record_path, record)
        atomic_json(Path(record['evidence']) / 'run.json', record)
        print(f'S4 experiment: {phase}', flush=True)

    def snapshot(self, directory, index):
        obs = {'time': utc_now(), 'errors': {}}
        queries = {
            'md': ('m', 'machinedeployment', self.preparation.md_name, '-n', self.client.ns),
            'mhc': ('m', 'machinehealthcheck', MHC_NAME, '-n', self.client.ns),
            'machines': ('m', 'machines', '-n', self.client.ns,
                         '-l', 'cluster.x-k8s.io/cluster-name=' + self.client.cluster),
            'osmachines': ('m', 'openstackmachines', '-n', self.client.ns,
                           '-l', 'cluster.x-k8s.io/cluster-name=' + self.client.cluster),
            'nodes': ('w', 'nodes'),
            'pods': ('w', 'pods', '-n', NAMESPACE),
            'deployment': ('w', 'deployment', HTTP_NAME, '-n', NAMESPACE),
            'events': ('m', 'events', '-n', self.client.ns),
        }
        for name, args in queries.items():
            try:
                obs[name] = self.client.get(*args)
            except (RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
                obs['errors'][name] = f'{type(exc).__name__}: {exc}'
        try:
            obs['nova'] = nova('list')
        except (RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
            obs['errors']['nova'] = f'{type(exc).__name__}: {exc}'
        atomic_json(directory / f'{index:04d}.json', obs)
        return obs

    def create_probe(self, record, node):
        name = record['probe_name']
        existing = self.preparation.object('w', 'pod', name, NAMESPACE)
        if existing:
            if not owned(existing) or existing['spec'].get('nodeName') != node:
                raise RuntimeError('replacement probe name/ownership mismatch')
            return
        manifest = {'apiVersion': 'v1', 'kind': 'Pod',
                    'metadata': {'name': name, 'namespace': NAMESPACE,
                                 'labels': {LABEL_KEY: EXPERIMENT}},
                    'spec': {'nodeName': node, 'restartPolicy': 'Never',
                             'containers': [{'name': 'probe', 'image': 'busybox:1.37.0',
                                             'command': ['sh', '-c', 'sleep 3600'],
                                             'resources': {'requests': {'cpu': '10m', 'memory': '16Mi'}},
                                             'readinessProbe': {'exec': {'command': [
                                                 'sh', '-c', 'wget -q -O - http.graduation-s4.svc.cluster.local:8080/healthz | grep -q ok']},
                                                 'periodSeconds': 3, 'timeoutSeconds': 2}}]}}
        self.preparation.k('w', 'apply', '-f', '-', data=json.dumps(manifest))

    def check_preflight(self):
        verified = self.preparation.verify()
        prep = self.preparation.read()
        budget = s4_host_budget(self.preparation.environment_record())
        if budget - time.time() < OBSERVE_SECONDS + 1200:
            raise RuntimeError('GCP auto-stop headroom is too short for S4 observation and cleanup')
        evidence = artifact_dir('graduation-s4-experiment')
        baseline = self.client.snapshot(evidence / 'baseline.json')
        state, reasons = evaluate(baseline, 2, os.environ)
        if state != 'ready':
            raise RuntimeError(f'S4 baseline is {state}: {reasons}')
        target = verified['target']
        matches = [m for m in baseline['machines']['items'] if m['metadata']['uid'] == target['machine_uid']]
        if len(matches) != 1 or matches[0]['metadata']['name'] != target['machine']:
            raise RuntimeError('target Machine identity changed before injection')
        target['osmachine'] = matches[0]['spec']['infrastructureRef']['name']
        servers = {row['id'].lower(): row for row in baseline['nova']['servers']}
        if servers.get(target['nova_id'].lower(), {}).get('status') != 'ACTIVE':
            raise RuntimeError('target Nova VM is not ACTIVE in baseline inventory')
        live_nova = nova_status(target['nova_id'])
        if live_nova['status'] != 'ACTIVE':
            raise RuntimeError('target Nova VM is not ACTIVE immediately before injection')
        originals = [m['metadata']['uid'] for m in baseline['machines']['items'] if
                     m['metadata'].get('labels', {}).get('cluster.x-k8s.io/deployment-name') == self.preparation.md_name]
        if len(originals) != 2:
            raise RuntimeError('baseline did not contain exactly two worker UIDs')
        return prep, verified, evidence, target, originals, budget

    def run(self):
        with self.lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            prior = self.read()
            if prior and prior['phase'] not in ('completed', 'completed_with_gap', 'failed'):
                raise RuntimeError('unfinished S4 experiment exists; use observe, never inject twice')
            if prior and self.preparation.read().get('environment_run_id') == prior['environment_run_id']:
                raise RuntimeError('S4 experiment already ran in this prepared environment')
            prep, verified, evidence, target, originals, budget = self.check_preflight()
            record = {'version': 1, 'run_id': 's4-' + uuid.uuid4().hex[:12],
                      'environment_run_id': prep['environment_run_id'], 'created': utc_now(),
                      'evidence': str(evidence), 'target': target, 'original_workers': originals,
                      'probe_name': 'new-worker-probe-' + uuid.uuid4().hex[:8],
                      'mhc_uid': verified['mhc_uid'], 'host_deadline_epoch': budget,
                      'source_sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                        for path in (ROOT / 'scripts/graduation_s4_run.py',
                                                     ROOT / 'scripts/graduation_s4.py',
                                                     ROOT / 'kubernetes/graduation-s4/http-service.yaml',
                                                     self.preparation.mhc_manifest)}}
            self.write(record, 'baseline-ready')
            try:
                with WorkerControl(self.client) as control:
                    mode, observed = control.preflight('fixed')
                    if mode != 'fixed' or observed['workers'] != 2 or not control.stable_workers(observed):
                        raise RuntimeError('worker control changed before injection')
                    with ProbeSampler(self.preparation.workload, evidence / 'http.jsonl') as sampler:
                        while len(sampler.samples) < 5 and not sampler.error:
                            time.sleep(1)
                        if sampler.error or not all(row['ok'] for row in sampler.samples[-5:]):
                            raise RuntimeError('HTTP sampler baseline did not produce five successes')
                        if nova_status(target['nova_id'])['status'] != 'ACTIVE':
                            raise RuntimeError('target Nova VM state changed before stop')
                        self.write(record, 'stop-intent', stop_intent_at=utc_now())
                        nova('stop', target['nova_id'])
                        stopped = None
                        stop_deadline = time.monotonic() + 90
                        while time.monotonic() < stop_deadline:
                            stopped = nova_status(target['nova_id'])
                            if stopped['status'] == 'SHUTOFF':
                                break
                            time.sleep(3)
                        if not stopped or stopped['status'] != 'SHUTOFF':
                            raise RuntimeError('Nova stop requested but SHUTOFF was not confirmed')
                        atomic_json(evidence / 'stopped-nova.json', stopped)
                        self.write(record, 'injected', injected_at=utc_now())
                        self.observe_locked(record, sampler)
                return record
            except BaseException as exc:
                self.write(record, 'failed', error=f'{type(exc).__name__}: {exc}')
                raise

    def observe_locked(self, record, sampler):
        evidence = Path(record['evidence'])
        snapshots = evidence / 'observations'
        snapshots.mkdir(exist_ok=True)
        deadline = min(time.monotonic() + OBSERVE_SECONDS,
                       time.monotonic() + max(0, record['host_deadline_epoch'] - time.time() - 600))
        capacity_since = None
        index = len(list(snapshots.glob('[0-9][0-9][0-9][0-9].json')))
        last_capacity = None
        while time.monotonic() < deadline:
            if sampler.error:
                raise RuntimeError('HTTP sampler stopped: ' + sampler.error)
            observation = self.snapshot(snapshots, index)
            index += 1
            # The new Machine's target Node must be established before the probe is created.
            workers = [m for m in observation.get('machines', {}).get('items', []) if
                       m['metadata'].get('labels', {}).get('cluster.x-k8s.io/deployment-name') == self.preparation.md_name
                       and m['metadata']['uid'] not in record['original_workers']]
            if len(workers) == 1 and condition(workers[0], 'Ready'):
                node = workers[0].get('status', {}).get('nodeRef', {}).get('name')
                if node:
                    self.create_probe(record, node)
            capacity = summarize_capacity(observation, record['target'],
                                          record['original_workers'], record['probe_name'])
            last_capacity = capacity
            atomic_json(evidence / 'latest-capacity.json', capacity)
            if capacity['state'] == 'recovered':
                capacity_since = capacity_since or time.monotonic()
            else:
                capacity_since = None
            # The stop operation can take a minute; failures during that call
            # are part of the experiment, not baseline traffic.
            http = summarize_http(sampler.samples, record['stop_intent_at'])
            atomic_json(evidence / 'latest-http.json', http)
            print(f"S4 observe: capacity={capacity['state']} http={http['state']} samples={len(sampler.samples)}", flush=True)
            if capacity_since and time.monotonic() - capacity_since >= STABLE_SECONDS and\
                    http['state'] in ('recovered', 'no_observed_outage') and\
                    unix_time(sampler.samples[-1]['time']) - unix_time(record['stop_intent_at']) >= STABLE_SECONDS:
                sampler.stop.set()
                sampler.thread.join(timeout=12)
                if sampler.thread.is_alive() or sampler.error:
                    raise RuntimeError('HTTP sampler did not finish cleanly')
                http = summarize_http(sampler.samples, record['stop_intent_at'])
                result = {'time': utc_now(),
                          'state': 'passed_with_observation_gap' if record.get('resumed_with_gap') else 'passed',
                          'target': record['target'],
                          'capacity': capacity, 'capacity_recovered_at': observation['time'],
                          'capacity_seconds': round(unix_time(observation['time']) - unix_time(record['injected_at']), 3),
                          'http': http, 'http_samples': len(sampler.samples)}
                atomic_json(evidence / 'result.json', result)
                self.write(record, 'completed_with_gap' if record.get('resumed_with_gap') else 'completed',
                           result=result)
                return result
            time.sleep(5)
        result = {'time': utc_now(), 'state': 'timeout', 'capacity': last_capacity,
            'http': summarize_http(sampler.samples, record['stop_intent_at']),
                  'http_samples': len(sampler.samples)}
        atomic_json(evidence / 'result.json', result)
        raise TimeoutError('S4 observation exceeded deadline; see result.json')

    def observe(self):
        with self.lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            record = self.read()
            if not record or record['phase'] not in ('injected', 'observing', 'failed', 'stop-intent'):
                raise RuntimeError('no injected/interrupted S4 experiment to observe')
            if not record.get('injected_at') and record.get('stop_intent_at'):
                state = nova_status(record['target']['nova_id'])
                if state['status'] not in ('SHUTOFF', 'ERROR'):
                    raise RuntimeError('stop outcome ambiguous; do not reinject automatically')
                self.write(record, 'injected', injected_at=utc_now(), resumed_with_gap=True)
            elif not record.get('injected_at'):
                raise RuntimeError('experiment failed before a confirmed stop')
            if record['environment_run_id'] != self.preparation.environment_record()['run_id']:
                raise RuntimeError('environment run differs from S4 experiment')
            with WorkerControl(self.client) as control:
                mode, observed = control.preflight('fixed')
                if mode != 'fixed' or observed['workers'] != 2:
                    raise RuntimeError('worker desired state changed during experiment')
                self.write(record, 'observing', resumed_with_gap=True)
                with ProbeSampler(self.preparation.workload, Path(record['evidence']) / 'http.jsonl') as sampler:
                    return self.observe_locked(record, sampler)


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    runner = S4Run()
    if action == 'run':
        runner.run()
    elif action == 'observe':
        print(json.dumps(runner.observe(), indent=2, ensure_ascii=False))
    elif action == 'status':
        print(json.dumps(runner.read(), indent=2, ensure_ascii=False))
    else:
        raise SystemExit('usage: graduation-s4-run.sh run|observe|status')


if __name__ == '__main__':
    main()
