#!/usr/bin/env python3
"""Run the S1 same-compute CPU contention and manual Pod relocation experiment."""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import time
import uuid

from graduation_env import atomic_json, utc_now
from graduation_s1 import (IMAGE, LABEL, NAMESPACE, S1, host_cpu_pressure,
                           host_cpu_utilization, percentile, pod_cpu_delta)
from workload_state import artifact_dir, command, condition


HOST_PATTERN = re.compile(r'osk8s-compute[0-9]+\Z')


def epoch(value):
    return dt.datetime.fromisoformat(value).timestamp()


def summarize_window(rows, start, end):
    selected = [row for row in rows if start <= epoch(row['time']) < end]
    selected.sort(key=lambda row: row['time'])
    success = [row['latency_ms'] for row in selected if row.get('ok')]
    indexes = [row['index'] for row in selected]
    gaps = [epoch(b['time']) - epoch(a['time']) for a, b in zip(selected, selected[1:])]
    return {'start': dt.datetime.fromtimestamp(start, dt.timezone.utc).isoformat(),
            'end': dt.datetime.fromtimestamp(end, dt.timezone.utc).isoformat(),
            'requests': len(selected), 'successes': len(success),
            'failures': len(selected) - len(success),
            'success_rate': round(len(success) / len(selected), 5) if selected else None,
            'successful_rps': round(len(success) / (end - start), 3),
            'duplicate_indexes': len(indexes) != len(set(indexes)),
            'max_sample_gap_seconds': round(max(gaps), 3) if gaps else None,
            'latency_ms': {'p50': percentile(success, .5),
                           'p95': percentile(success, .95),
                           'p99': percentile(success, .99)}}


def recovery_controls(record, moved, host_metrics, contender):
    source = record['service_compute_host']
    baseline_pressure = host_metrics['baseline'][source]['cpu_pressure_some']
    pressure_floor = max(.02, baseline_pressure * 2)
    post = host_metrics['relocated'][source]
    completion = host_metrics['completion'][source]
    return {
        'image_unchanged': moved['image_id'] == record['service_before']['image_id'],
        'competitor_active_on_source': (
            str(contender.get('id', '')).lower() == record['server_id'].lower()
            and contender.get('status') == 'ACTIVE'
            and contender.get('OS-EXT-SRV-ATTR:host') == source),
        'source_contention_persisted': (
            post['cpu_utilization'] >= .7 and
            post['cpu_pressure_some'] >= pressure_floor),
        'source_contention_at_completion': (
            completion['cpu_utilization'] >= .7 and
            completion['cpu_pressure_some'] >= pressure_floor),
    }


def stress_user_data(seconds=780):
    duration = max(1200, seconds + 360)
    return f'''#!/bin/bash
set -euo pipefail
cat >/opt/s1-cpu-stress.py <<'PY'
import hashlib
import multiprocessing
import time

def burn():
    while True:
        hashlib.pbkdf2_hmac('sha256', b's1-competitor', b'fixed-salt', 100000)

if __name__ == '__main__':
    processes = [multiprocessing.Process(target=burn) for _ in range(4)]
    for process in processes:
        process.start()
    print('S1_CPU_STRESS_STARTED', flush=True)
    time.sleep({duration})
    for process in processes:
        process.terminate()
    for process in processes:
        process.join()
PY
nohup /usr/bin/timeout {duration + 30}s /usr/bin/python3 -u /opt/s1-cpu-stress.py \
  >/var/log/s1-cpu-stress.log 2>&1 </dev/null &
stress_pid=$!
sleep 2
kill -0 "$stress_pid"
echo S1_CPU_STRESS_STARTED >/dev/console
'''


def load_job(name, node, rate, rounds, seconds):
    url = f'http://http.{NAMESPACE}.svc.cluster.local:8080/work?rounds={rounds}'
    env = {'URL': url, 'RATE': rate, 'WARMUP_SECONDS': 0,
           'MEASURE_SECONDS': seconds, 'TIMEOUT_SECONDS': 5, 'MAX_INFLIGHT': 50}
    return {'apiVersion': 'batch/v1', 'kind': 'Job',
            'metadata': {'name': name, 'namespace': NAMESPACE, 'labels': {LABEL: NAMESPACE}},
            'spec': {'backoffLimit': 0, 'template': {
                'metadata': {'labels': {LABEL: NAMESPACE}},
                'spec': {'nodeName': node, 'restartPolicy': 'Never',
                         'tolerations': [{'key': 'node-role.kubernetes.io/control-plane',
                                          'operator': 'Exists', 'effect': 'NoSchedule'}],
                         'containers': [{'name': 'loadgen', 'image': IMAGE,
                                         'command': ['python', '-B', '/app/loadgen.py'],
                                         'env': [{'name': 'S1_' + key, 'value': str(value)}
                                                 for key, value in env.items()],
                                         'resources': {'requests': {'cpu': '50m', 'memory': '64Mi'},
                                                       'limits': {'memory': '256Mi'}},
                                         'volumeMounts': [{'name': 'app', 'mountPath': '/app',
                                                           'readOnly': True}]}],
                         'volumes': [{'name': 'app', 'configMap': {'name': 's1-code'}}]}}}}


class S1Contention:
    recovery_seconds = 120
    recovery_window_offset = 30

    def __init__(self, s1=None):
        self.s1 = s1 or S1()
        self.client = self.s1.client
        self.state = self.client.state / 's1-contention.json'

    def read(self):
        return json.loads(self.state.read_text()) if self.state.exists() else None

    def write(self, record, phase, **values):
        record.update(values, phase=phase, updated=utc_now())
        atomic_json(self.state, record)
        atomic_json(Path(record['evidence']) / 'run.json', record)
        print(f'S1 contention: {phase}', flush=True)

    def admin(self, *args, timeout=60, user_data=None):
        cloud = ('set -euo pipefail; source /opt/kolla-venv/bin/activate; '
                 'export OS_CLIENT_CONFIG_FILE=/etc/kolla/clouds.yaml; ')
        if user_data is not None:
            encoded = base64.b64encode(user_data.encode()).decode()
            cloud += ("file=$(mktemp); trap 'rm -f \"$file\"' EXIT; "
                      f'printf %s {shlex.quote(encoded)} | base64 -d >"$file"; ')
            args = tuple('$file' if arg == '@user-data' else arg for arg in args)
            quoted = ' '.join('"$file"' if arg == '$file' else shlex.quote(str(arg))
                              for arg in args)
        else:
            quoted = shlex.join(map(str, args))
        cloud += 'openstack --os-cloud kolla-admin ' + quoted
        gcloud = ['gcloud', 'compute', 'ssh',
                  os.environ['TARGET_SSH_USER'] + '@' + os.environ['CONTROLLER_NAME'],
                  '--project=' + os.environ['GCP_PROJECT_ID'],
                  '--zone=' + os.environ['GCP_ZONE'], '--quiet']
        if os.environ.get('GCP_USE_IAP_TUNNEL') == 'yes':
            gcloud.append('--tunnel-through-iap')
        gcloud.append('--command=' + shlex.join(('bash', '-lc', cloud)))
        return command(gcloud, timeout=timeout)

    def admin_json(self, *args, **kwargs):
        return json.loads(self.admin(*args, '-f', 'json', **kwargs))

    def server(self, server_id):
        row = self.admin_json('server', 'show', server_id)
        if row['id'].lower() != server_id.lower():
            raise RuntimeError('S1 contender Nova UUID changed')
        return row

    def create_competitor(self, record):
        host = record['service_compute_host']
        if not HOST_PATTERN.fullmatch(host):
            raise RuntimeError('unsupported S1 compute host: ' + host)
        flavor = 's1-cpu-' + record['run_id']
        server_name = 's1-cpu-' + record['run_id']
        self.write(record, 'flavor-create-intent', flavor_name=flavor,
                   server_name=server_name)
        created = self.admin_json('flavor', 'create', '--vcpus', '4', '--ram', '1024',
                                  '--disk', '10', flavor)
        self.write(record, 'flavor-created', flavor_id=created['id'])
        self.write(record, 'server-create-intent')
        result = self.admin_json('server', 'create', '--wait', '--config-drive', 'true',
                                 '--availability-zone', 'nova:' + host,
                                 '--flavor', record['flavor_id'], '--image',
                                 os.environ['UBUNTU_IMAGE_NAME'], '--network',
                                 os.environ['TENANT_NETWORK_NAME'], '--user-data', '@user-data',
                                 server_name, timeout=900,
                                 user_data=stress_user_data(record['seconds']))
        self.write(record, 'server-created', server_id=result['id'])
        observed = self.server(record['server_id'])
        if observed.get('status') != 'ACTIVE' or observed.get('OS-EXT-SRV-ATTR:host') != host:
            raise RuntimeError('S1 contender did not become ACTIVE on the service compute')
        atomic_json(Path(record['evidence']) / 'contender-server.json', observed)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            console = self.admin('console', 'log', 'show', record['server_id'])
            if 'S1_CPU_STRESS_STARTED' in console:
                (Path(record['evidence']) / 'contender-console.txt').write_text(console)
                self.write(record, 'stress-started', stress_observed_at=utc_now())
                return observed
            time.sleep(5)
        raise RuntimeError('S1 contender did not report CPU stress startup')

    def remove_competitor(self, record):
        if record.get('server_name'):
            matches = self.admin_json('server', 'list', '--name', record['server_name'])
            owned = [row for row in matches if row['Name'] == record['server_name']]
            if len(owned) > 1 or (owned and record.get('server_id') and
                                  owned[0]['ID'].lower() != record['server_id'].lower()):
                raise RuntimeError('S1 contender server identity changed; refusing deletion')
            if owned:
                self.admin('server', 'delete', '--wait', owned[0]['ID'], timeout=600)
        if record.get('flavor_name'):
            matches = self.admin_json('flavor', 'list', '--long')
            owned = [row for row in matches if row['Name'] == record['flavor_name']]
            if len(owned) > 1:
                raise RuntimeError('multiple S1 contender flavors have the same name')
            if owned:
                flavor = self.admin_json('flavor', 'show', record['flavor_name'])
                if record.get('flavor_id') and flavor['id'] != record['flavor_id']:
                    raise RuntimeError('S1 contender flavor identity changed; refusing deletion')
                self.admin('flavor', 'delete', flavor['id'])
        self.write(record, 'competitor-removed')

    def wait_probe_samples(self, job_name):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                raw = self.s1.k('-n', NAMESPACE, 'logs', 'job/' + job_name, timeout=30)
                if len(raw.splitlines()) >= 10:
                    return
            except RuntimeError:
                pass
            time.sleep(5)
        raise RuntimeError('S1 contention Job did not produce ten initial HTTP samples')

    def capture_failed_job(self, record):
        """Save available request and Pod evidence before removing a failed Job."""
        evidence = Path(record['evidence'])
        result = {'time': utc_now(), 'job_name': record['job_name'],
                  'http_log_saved': False, 'errors': []}
        try:
            job = self.s1.obj('job', record['job_name'])
            if not job:
                result['errors'].append('Job no longer exists')
            elif job['metadata'].get('labels', {}).get(LABEL) != NAMESPACE or\
                    (record.get('job_uid') and job['metadata']['uid'] != record['job_uid']):
                result['errors'].append('Job ownership/UID changed; evidence query skipped')
            else:
                atomic_json(evidence / 'job-on-failure.json', job)
                try:
                    pods = self.client.get('w', 'pods', '-n', NAMESPACE,
                                           '-l', 'job-name=' + record['job_name'])['items']
                    atomic_json(evidence / 'probe-pods-on-failure.json', pods)
                except Exception as exc:
                    result['errors'].append(f'Pod query: {type(exc).__name__}: {exc}')
                try:
                    raw = self.s1.k('-n', NAMESPACE, 'logs', 'job/' + record['job_name'],
                                    timeout=120)
                    (evidence / 'http.jsonl').write_text(raw)
                    result['http_log_saved'] = True
                    result['http_log_lines'] = len(raw.splitlines())
                except Exception as exc:
                    result['errors'].append(f'HTTP log query: {type(exc).__name__}: {exc}')
        except Exception as exc:
            result['errors'].append(f'Job query: {type(exc).__name__}: {exc}')
        atomic_json(evidence / 'failure-evidence.json', result)
        return result

    def run(self, rate=5, rounds=100000, seconds=780):
        if not 0 < rate <= 50 or not 10000 <= rounds <= 1000000 or not 600 <= seconds <= 1800:
            raise ValueError('S1 contention parameters outside safe range')
        self.client.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.s1.lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            previous = self.read()
            if previous and previous['phase'] != 'completed':
                raise RuntimeError('unfinished S1 contention exists; clean it first')
            for name in ('s1-contention.json', 's1-auto.json'):
                path = self.client.state / name
                if path != self.state and path.exists() and json.loads(path.read_text())['phase'] != 'completed':
                    raise RuntimeError('another S1 experiment is unfinished: ' + name)
            service = self.s1.verify()
            jobs = self.client.get('w', 'jobs', '-n', NAMESPACE,
                                   '-l', LABEL + '=' + NAMESPACE)['items']
            if jobs:
                raise RuntimeError('S1 Job already exists')
            nodes = self.client.get('w', 'nodes')['items']
            control = [node for node in nodes if
                       'node-role.kubernetes.io/control-plane' in node['metadata'].get('labels', {})]
            workers = [node for node in nodes if
                       'node-role.kubernetes.io/control-plane' not in node['metadata'].get('labels', {})
                       and condition(node, 'Ready')]
            if len(control) != 1 or len(workers) != 2 or not condition(control[0], 'Ready'):
                raise RuntimeError('S1 requires one Ready control plane and two Ready workers')
            machines = self.client.get('m', 'machines', '-n', self.client.ns,
                                       '-l', 'cluster.x-k8s.io/cluster-name=' + self.client.cluster)['items']
            def placement(node):
                machine = next((item for item in machines if
                                item.get('status', {}).get('nodeRef', {}).get('name') ==
                                node['metadata']['name']), None)
                if not machine or not machine.get('spec', {}).get('providerID', '').startswith('openstack:///'):
                    raise RuntimeError('S1 Node has no verified Nova VM: ' + node['metadata']['name'])
                nova_id = machine['spec']['providerID'].removeprefix('openstack:///')
                return nova_id, self.s1.placement(nova_id)
            probe_nova, probe_place = placement(control[0])
            worker_places = [(node, *placement(node)) for node in workers]
            sources = [item for item in worker_places if
                       item[2]['compute_host'] != probe_place['compute_host']]
            if len(sources) != 1:
                raise RuntimeError('exactly one worker must be on a compute distinct from the probe')
            source = sources[0]
            target = next(item for item in worker_places if item[0] != source[0])
            if target[2]['compute_host'] == source[2]['compute_host']:
                raise RuntimeError('alternate worker is on the same compute as service')
            source_selector = source[0]['metadata'].get('labels', {}).get('kubernetes.io/hostname')
            target_selector = target[0]['metadata'].get('labels', {}).get('kubernetes.io/hostname')
            if not source_selector or not target_selector:
                raise RuntimeError('S1 worker hostname labels are unavailable')
            deployment = self.s1.obj('deployment', 'http')
            selector = deployment['spec']['template']['spec'].get('nodeSelector')
            if selector and selector != {'kubernetes.io/hostname': source_selector}:
                raise RuntimeError('S1 Deployment has an unexpected nodeSelector')
            evidence = artifact_dir('graduation-s1-contention')
            environment = self.s1.environment()
            deadlines = [epoch(host['last_start']) + int(host['max_run_seconds'])
                         for host in environment['final_hosts'].values()]
            if min(deadlines) - time.time() < seconds + 1800:
                raise RuntimeError('GCP host auto-stop headroom is too short for S1 contention')
            record = {'version': 1, 'run_id': 's1c-' + uuid.uuid4().hex[:12],
                      'created': utc_now(), 'evidence': str(evidence),
                      'environment_run_id': environment['run_id'],
                      'preparation_id': self.s1.read()['run_id'],
                      'service_initial': service,
                      'service_compute_host': source[2]['compute_host'],
                      'source_node': source[0]['metadata']['name'],
                      'source_selector': source_selector,
                      'target_node': target[0]['metadata']['name'],
                      'target_selector': target_selector,
                      'target_nova_id': target[1],
                      'target_compute_host': target[2]['compute_host'],
                      'probe_nova_id': probe_nova,
                      'probe_compute_host': probe_place['compute_host'],
                      'rate': rate, 'rounds': rounds, 'seconds': seconds,
                      'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
            source_files = [Path(__file__), Path(__file__).with_name('graduation_s1.py'),
                            Path(__file__).with_name('graduation-s1-host-stat.sh')]
            if self.state.name == 's1-auto.json':
                source_files.append(Path(__file__).with_name('graduation_s1_auto.py'))
            (evidence / 'source').mkdir()
            record['source_files_sha256'] = {}
            for path in source_files:
                content = path.read_bytes()
                (evidence / 'source' / path.name).write_bytes(content)
                record['source_files_sha256'][path.name] = hashlib.sha256(content).hexdigest()
            self.write(record, 'prepared')
            initial_patch = {'spec': {'template': {'spec': {'nodeSelector': {
                'kubernetes.io/hostname': source_selector}}}}}
            self.write(record, 'preposition-intent', preposition_intent_at=utc_now())
            self.s1.k('-n', NAMESPACE, 'patch', 'deployment', 'http',
                      '--type=merge', '-p', json.dumps(initial_patch))
            self.s1.k('-n', NAMESPACE, 'rollout', 'status', 'deployment/http',
                      '--timeout=5m', timeout=330)
            service = self.s1.verify()
            if service['node'] != source[0]['metadata']['name'] or\
                    service['nova_id'] != source[1]:
                raise RuntimeError('S1 service did not preposition on the isolated compute')
            self.write(record, 'prepositioned', service_before=service,
                       prepositioned_at=utc_now())
            atomic_json(evidence / 'placement-before.json',
                        {'service': source[2], 'target': target[2], 'probe': probe_place})
            return self.run_locked(record, control[0]['metadata']['name'])

    def observe_contention(self, record, job_name, before_cpu, before_host, stress_start, host_sample):
        time.sleep(120)
        return self.s1.cpu_stat(record['service_before']['pod']), host_sample('stress-end')

    def move_service(self, record):
        patch = {'spec': {'template': {'spec': {'nodeSelector': {
            'kubernetes.io/hostname': record['target_selector']}}}}}
        self.write(record, 'relocation-intent', relocation_intent_at=utc_now())
        self.s1.k('-n', NAMESPACE, 'patch', 'deployment', 'http',
                  '--type=merge', '-p', json.dumps(patch))

    def recovery_checks(self, record, rows, baseline_p95):
        return {}

    def verify_intervention(self, record, moved):
        if moved['node'] != record['target_node'] or moved['pod_uid'] == record['service_before']['pod_uid']:
            raise RuntimeError('S1 HTTP Pod did not relocate to the alternate worker')
        target_after = self.s1.placement(moved['nova_id'])
        if target_after['compute_host'] != record['target_compute_host']:
            raise RuntimeError('S1 target worker compute placement changed')

    def evaluation_result(self, summary, valid):
        """Keep measurement validity separate from the intervention's recovery result."""
        summary['measurement_valid'] = bool(valid)
        summary['state'] = 'passed' if valid and summary['latency_recovery_within_1_2x'] and\
            all(summary['recovery_checks'].values()) else 'needs_review'
        return summary

    def observe_recovery(self, record, job_name):
        time.sleep(self.recovery_seconds)

    def recovery_window_start(self, record):
        return epoch(record['relocated_at']) + self.recovery_window_offset

    def run_locked(self, record, probe_node):
        evidence = Path(record['evidence'])
        hosts = (record['service_compute_host'], record['target_compute_host'])
        def host_sample(name):
            sample = {host: self.s1.host_stat(host) for host in hosts}
            atomic_json(evidence / ('hosts-' + name + '.json'), sample)
            return sample
        job_name = 's1-contention-' + uuid.uuid4().hex[:8]
        job = load_job(job_name, probe_node, record['rate'], record['rounds'],
                       record['seconds'])
        atomic_json(evidence / 'job.json', job)
        self.write(record, 'job-create-intent', job_name=job_name)
        primary_error = None
        try:
            self.s1.k('apply', '-f', '-', data=json.dumps(job))
            job_obj = self.s1.obj('job', job_name)
            self.write(record, 'sampling', job_uid=job_obj['metadata']['uid'],
                       sampling_started_at=utc_now())
            self.wait_probe_samples(job_name)
            host_start = host_sample('baseline-start')
            time.sleep(90)
            baseline_end = utc_now()
            before_cpu = self.s1.cpu_stat(record['service_before']['pod'])
            before_host = host_sample('baseline-end')
            atomic_json(evidence / 'pod-cpu-before.json', before_cpu)
            self.write(record, 'baseline-sampled', baseline_end_at=baseline_end)
            self.create_competitor(record)
            stress_start_host = host_sample('stress-start')
            during_cpu, during_host = self.observe_contention(
                record, job_name, before_cpu, before_host, stress_start_host, host_sample)
            atomic_json(evidence / 'pod-cpu-during.json', during_cpu)
            self.write(record, 'stress-sampled', stress_end_at=utc_now())
            self.move_service(record)
            self.s1.k('-n', NAMESPACE, 'rollout', 'status', 'deployment/http',
                      '--timeout=5m', timeout=330)
            moved = self.s1.verify()
            self.verify_intervention(record, moved)
            self.write(record, 'relocated', service_after=moved, relocated_at=utc_now())
            relocated_host = host_sample('relocated')
            self.observe_recovery(record, job_name)
            after_host = host_sample('post-relocation')
            self.s1.k('-n', NAMESPACE, 'wait', '--for=condition=complete',
                      'job/' + job_name, f'--timeout={record["seconds"] + 180}s',
                      timeout=record['seconds'] + 210)
            completion_start = host_sample('completion-start')
            time.sleep(30)
            completion_end = host_sample('completion-end')
            contender_after = self.server(record['server_id'])
            atomic_json(evidence / 'contender-after.json', contender_after)
            probe_pods = self.client.get('w', 'pods', '-n', NAMESPACE,
                                         '-l', 'job-name=' + job_name)['items']
            if len(probe_pods) != 1 or probe_pods[0]['spec'].get('nodeName') != probe_node or\
                    probe_pods[0].get('status', {}).get('phase') != 'Succeeded':
                raise RuntimeError('S1 contention probe did not finish on control plane')
            atomic_json(evidence / 'probe-pod.json', probe_pods[0])
            raw = self.s1.k('-n', NAMESPACE, 'logs', 'job/' + job_name, timeout=120)
            (evidence / 'http.jsonl').write_text(raw)
            rows = [json.loads(line) for line in raw.splitlines()]
            baseline_end = epoch(record['baseline_end_at'])
            stress_end = epoch(record['stress_end_at'])
            recovery_start = self.recovery_window_start(record)
            windows = {
                'baseline': summarize_window(rows, baseline_end - 60, baseline_end),
                'contention': summarize_window(rows, stress_end - 60, stress_end),
                'relocated': summarize_window(rows, recovery_start, recovery_start + 60)}
            delta, cpu_errors = pod_cpu_delta(before_cpu, during_cpu)
            host_metrics = {phase: {host: {
                'cpu_utilization': host_cpu_utilization(start[host], end[host]),
                'cpu_pressure_some': host_cpu_pressure(start[host], end[host])}
                for host in hosts} for phase, start, end in (
                    ('baseline', host_start, before_host),
                    ('contention', stress_start_host, during_host),
                    ('relocated', relocated_host, after_host),
                    ('completion', completion_start, completion_end))}
            baseline_p95 = windows['baseline']['latency_ms']['p95']
            stressed_p95 = windows['contention']['latency_ms']['p95']
            relocated_p95 = windows['relocated']['latency_ms']['p95']
            impact = bool((baseline_p95 and stressed_p95 and
                           stressed_p95 > 1.5 * baseline_p95) or
                          windows['contention']['failures'] > windows['baseline']['failures'])
            recovery = bool(baseline_p95 and relocated_p95 and
                            relocated_p95 <= 1.2 * baseline_p95 and
                            windows['relocated']['failures'] == 0)
            expected = int(record['rate'] * record['seconds'])
            all_indexes = [row['index'] for row in rows]
            quality = all(item['requests'] >= 200 and not item['duplicate_indexes']
                          and (item['max_sample_gap_seconds'] or 0) <= 2.5
                          for item in windows.values()) and not cpu_errors and\
                len(rows) == expected and set(all_indexes) == set(range(expected))
            source_host = record['service_compute_host']
            baseline_pressure = host_metrics['baseline'][source_host]['cpu_pressure_some']
            stressed_pressure = host_metrics['contention'][source_host]['cpu_pressure_some']
            host_contention = (stressed_pressure >= max(.02, baseline_pressure * 2)
                               and host_metrics['contention'][source_host]['cpu_utilization'] >= .7)
            pod_throttling_observed = delta.get('nr_throttled', 0) > 0
            controls = recovery_controls(record, moved, host_metrics, contender_after)
            checks = self.recovery_checks(record, rows, baseline_p95)
            summary = {'time': utc_now(), 'run_id': record['run_id'], 'windows': windows,
                       'pod_cpu_delta_before_relocation': delta, 'pod_cpu_errors': cpu_errors,
                       'host_metrics': host_metrics,
                       'host_contention_confirmed': host_contention,
                       **controls,
                       'recovery_checks': checks,
                       'pod_throttling_observed': pod_throttling_observed,
                       'service_before': record['service_before'], 'service_after': moved,
                       'service_compute_host': record['service_compute_host'],
                       'target_compute_host': record['target_compute_host'],
                       'latency_impact_over_1_5x': bool(impact),
                       'latency_recovery_within_1_2x': bool(recovery),
                       'state': 'needs_review'}
            summary = self.evaluation_result(summary, quality and impact and host_contention and
                                             all(controls.values()) and not pod_throttling_observed)
            atomic_json(evidence / 'summary.json', summary)
            self.write(record, 'measured', summary_state=summary['state'])
            return summary
        except BaseException as exc:
            primary_error = f'{type(exc).__name__}: {exc}'
            self.write(record, 'failed', error=primary_error)
            raise
        finally:
            cleanup_errors = []
            if primary_error:
                try:
                    record['failure_evidence'] = self.capture_failed_job(record)
                except Exception as exc:
                    record['evidence_capture_error'] = f'{type(exc).__name__}: {exc}'
            if record.get('job_name'):
                try:
                    obj = self.s1.obj('job', job_name)
                    if obj and obj['metadata'].get('labels', {}).get(LABEL) == NAMESPACE and\
                            (not record.get('job_uid') or obj['metadata']['uid'] == record['job_uid']):
                        self.s1.k('delete', 'job', job_name, '-n', NAMESPACE,
                                  '--wait=true', '--timeout=3m', timeout=210)
                except BaseException as exc:
                    cleanup_errors.append(f'Job: {type(exc).__name__}: {exc}')
            if record.get('server_name') or record.get('flavor_name'):
                try:
                    self.remove_competitor(record)
                except BaseException as exc:
                    cleanup_errors.append(f'contender: {type(exc).__name__}: {exc}')
            if cleanup_errors:
                self.write(record, 'cleanup-failed', cleanup_errors=cleanup_errors,
                           primary_error=primary_error)
                if primary_error is None:
                    raise RuntimeError('; '.join(cleanup_errors))
            elif primary_error:
                self.write(record, 'failed', error=primary_error)
            else:
                self.write(record, 'completed')

    def cleanup(self):
        with self.s1.lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            record = self.read()
            if not record or record.get('phase') == 'completed':
                return record
            if record['environment_run_id'] != self.s1.environment()['run_id']:
                raise RuntimeError('S1 contention belongs to another environment run')
            cleanup_errors = []
            if record.get('job_name'):
                try:
                    obj = self.s1.obj('job', record['job_name'])
                    if obj and obj['metadata'].get('labels', {}).get(LABEL) == NAMESPACE and\
                            (not record.get('job_uid') or obj['metadata']['uid'] == record['job_uid']):
                        record['failure_evidence'] = self.capture_failed_job(record)
                        self.s1.k('delete', 'job', record['job_name'], '-n', NAMESPACE,
                                  '--wait=true', '--timeout=3m', timeout=210)
                except Exception as exc:
                    cleanup_errors.append(f'Job: {type(exc).__name__}: {exc}')
            try:
                self.remove_competitor(record)
            except Exception as exc:
                cleanup_errors.append(f'contender: {type(exc).__name__}: {exc}')
            if cleanup_errors:
                self.write(record, 'cleanup-failed', cleanup_errors=cleanup_errors)
                raise RuntimeError('; '.join(cleanup_errors))
            self.write(record, 'completed')
            return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'cleanup', 'status'))
    parser.add_argument('--rate', type=float, default=5)
    parser.add_argument('--rounds', type=int, default=100000)
    parser.add_argument('--seconds', type=int, default=780)
    args = parser.parse_args()
    experiment = S1Contention()
    if args.action == 'run':
        result = experiment.run(args.rate, args.rounds, args.seconds)
    elif args.action == 'cleanup':
        result = experiment.cleanup()
    else:
        result = experiment.read()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
