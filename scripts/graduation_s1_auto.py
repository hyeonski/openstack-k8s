#!/usr/bin/env python3
"""S1 evidence-based recovery of the registered HTTP fixture."""
from __future__ import annotations

import argparse
import copy
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import time

from graduation_env import utc_now
from graduation_s1 import NAMESPACE, host_cpu_pressure, host_cpu_utilization, pod_cpu_delta
from graduation_s1_contention import S1Contention, epoch, summarize_window
from workload_state import condition

COOLDOWN_KEY = 'openstack-k8s.dev/s1-last-relocation'
POLICY = {'window_seconds': 60, 'consecutive_windows': 2, 'max_windows': 6,
          'impact_ratio': 1.5, 'recovery_ratio': 1.2, 'cpu_min': .7,
          'psi_min': .02, 'psi_baseline_ratio': 2, 'cooldown_seconds': 900,
          'max_sample_age_seconds': 90, 'min_host_memory_bytes': 512 * 1024**2}
POLICY.update(recovery_settle_seconds=30, recovery_window_seconds=60,
              recovery_consecutive_windows=3, recovery_max_windows=8)


def quantity(value):
    match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)([a-zA-Z]*)', str(value))
    if not match:
        raise ValueError('unsupported resource quantity')
    scales = {'': 1, 'm': .001, 'Ki': 1024, 'Mi': 1024**2, 'Gi': 1024**3,
              'Ti': 1024**4, 'k': 1000, 'M': 1000**2, 'G': 1000**3}
    return Decimal(match[1]) * Decimal(str(scales[match[2]]))


def requests(spec, resource):
    regular = sum(quantity(c.get('resources', {}).get('requests', {}).get(resource, 0))
                  for c in spec.get('containers', []))
    sidecars, init = Decimal(0), Decimal(0)
    for container in spec.get('initContainers', []):
        value = quantity(container.get('resources', {}).get('requests', {}).get(resource, 0))
        if container.get('restartPolicy') == 'Always':
            sidecars += value
            init = max(init, sidecars)
        else:
            init = max(init, sidecars + value)
    pod_level = quantity(spec.get('resources', {}).get('requests', {}).get(resource, 0))
    return max(regular + sidecars, init, pod_level) + quantity(spec.get('overhead', {}).get(resource, 0))


def matches(expression, labels):
    key, op = expression['key'], expression['operator']
    values = expression.get('values', [])
    if op == 'In':
        return key in labels and labels[key] in values
    if op == 'NotIn':
        return key not in labels or labels[key] not in values
    if op == 'Exists':
        return key in labels
    if op == 'DoesNotExist':
        return key not in labels
    if op in ('Gt', 'Lt') and key in labels and len(values) == 1:
        try:
            return int(labels[key]) > int(values[0]) if op == 'Gt' else int(labels[key]) < int(values[0])
        except ValueError:
            return False
    return False


def candidate_reasons(node, pods, spec, source_host, placement, metrics):
    reasons = []
    labels = node['metadata'].get('labels', {})
    if not condition(node, 'Ready') or node['spec'].get('unschedulable'):
        reasons.append('node_not_schedulable')
    if 'node-role.kubernetes.io/control-plane' in labels or placement['compute_host'] == source_host:
        reasons.append('not_another_compute_worker')
    for key, value in spec.get('nodeSelector', {}).items():
        if key != 'kubernetes.io/hostname' and labels.get(key) != value:
            reasons.append('node_selector')
    affinity = spec.get('affinity', {})
    if affinity.get('podAffinity') or affinity.get('podAntiAffinity') or spec.get('topologySpreadConstraints'):
        reasons.append('unsupported_cross_pod_constraint')
    terms = affinity.get('nodeAffinity', {}).get('requiredDuringSchedulingIgnoredDuringExecution', {}).get('nodeSelectorTerms')
    if terms is not None and not any(
            bool(term.get('matchExpressions') or term.get('matchFields')) and
            all(matches(e, labels) for e in term.get('matchExpressions', [])) and
            all(matches(e, {'metadata.name': node['metadata']['name']}) for e in term.get('matchFields', []))
            for term in terms):
        reasons.append('node_affinity')
    for taint in node['spec'].get('taints', []):
        if taint['effect'] not in ('NoSchedule', 'NoExecute'):
            continue
        if not any((not t.get('effect') or t['effect'] == taint['effect']) and
                   (t.get('key') == taint['key'] or (not t.get('key') and t.get('operator') == 'Exists')) and
                   (t.get('operator') == 'Exists' or t.get('value', '') == taint.get('value', ''))
                   for t in spec.get('tolerations', [])):
            reasons.append('untolerated_taint')
    for resource in ('cpu', 'memory'):
        available = quantity(node['status']['allocatable'][resource])
        used = sum(requests(p['spec'], resource) for p in pods
                   if p['spec'].get('nodeName') == node['metadata']['name'] and
                   p.get('status', {}).get('phase') not in ('Succeeded', 'Failed'))
        if available - used < requests(spec, resource):
            reasons.append('insufficient_' + resource)
    if metrics['cpu_utilization'] >= POLICY['cpu_min'] or metrics['cpu_pressure_some'] >= POLICY['psi_min']:
        reasons.append('destination_cpu_busy')
    if metrics['memory_available'] < POLICY['min_host_memory_bytes']:
        reasons.append('destination_memory_low')
    if any(metrics.get(name + '_pressure_some', 1) >= .02 for name in ('memory', 'io')):
        reasons.append('destination_other_pressure')
    return reasons


def interval(before, after):
    result = {'time': after['time'], 'cpu_utilization': host_cpu_utilization(before, after),
              'cpu_pressure_some': host_cpu_pressure(before, after),
              'memory_available': after['memory']['MemAvailable']}
    for name in ('memory', 'io'):
        result[name + '_pressure_some'] = host_cpu_pressure(
            {'time': before['time'], 'cpu_pressure': before[name + '_pressure']},
            {'time': after['time'], 'cpu_pressure': after[name + '_pressure']})
    return result


def diagnose(baseline, sample, metrics, cpu_before, cpu_after, baseline_pressure, rate):
    reasons = []
    if sample['requests'] < rate * POLICY['window_seconds'] * .9 or sample['duplicate_indexes'] or\
            sample['max_sample_gap_seconds'] is None or sample['max_sample_gap_seconds'] > max(2.5, 3 / rate):
        reasons.append('request_evidence_incomplete')
    if not baseline['latency_ms']['p95']:
        reasons.append('latency_unavailable')
    elif sample['failures'] <= baseline['failures']:
        if not sample['latency_ms']['p95']:
            reasons.append('latency_unavailable')
        elif sample['latency_ms']['p95'] <= baseline['latency_ms']['p95'] * POLICY['impact_ratio']:
            reasons.append('service_impact_not_confirmed')
    if metrics['cpu_utilization'] < POLICY['cpu_min'] or\
            metrics['cpu_pressure_some'] < max(POLICY['psi_min'], baseline_pressure * POLICY['psi_baseline_ratio']):
        reasons.append('host_contention_not_confirmed')
    delta, errors = pod_cpu_delta(cpu_before, cpu_after)
    if errors or delta.get('nr_throttled', 0) or delta.get('throttled_usec', 0):
        reasons.append('pod_cpu_evidence_invalid_or_throttled')
    if metrics['memory_pressure_some'] >= .02 or metrics['io_pressure_some'] >= .02 or\
            metrics['memory_available'] < POLICY['min_host_memory_bytes']:
        reasons.append('other_host_pressure')
    return {'trigger': not reasons, 'reasons': reasons, 'pod_cpu_delta': delta, 'cpu_errors': errors}


def stable_window(window, baseline_p95, rate):
    return (window['requests'] >= rate * POLICY['recovery_window_seconds'] * .9 and
            not window['failures'] and not window['duplicate_indexes'] and
            window['latency_ms']['p95'] is not None and
            window['latency_ms']['p95'] <= baseline_p95 * POLICY['recovery_ratio'] and
            window['max_sample_gap_seconds'] is not None and
            window['max_sample_gap_seconds'] <= max(2.5, 3 / rate))


class S1Automatic(S1Contention):

    def __init__(self, s1=None):
        super().__init__(s1)
        self.state = self.client.state / 's1-auto.json'

    def event(self, record, item):
        item = {'time': utc_now(), **item}
        with (Path(record['evidence']) / 'decisions.jsonl').open('a') as stream:
            stream.write(json.dumps(item) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    def observe_contention(self, record, job_name, before_cpu, before_host, stress_start, host_sample):
        record['policy'] = dict(POLICY)
        record['policy_source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        deployment = self.s1.obj('deployment', 'http')
        record['deployment_before'] = deployment
        last = deployment['metadata'].get('annotations', {}).get(COOLDOWN_KEY)
        if last and time.time() - epoch(last) < POLICY['cooldown_seconds']:
            raise RuntimeError('S1 automatic recovery deferred: cooldown')
        baseline_rows = self.s1.k('-n', NAMESPACE, 'logs', 'job/' + job_name, timeout=60)
        rows = [json.loads(line) for line in baseline_rows.splitlines()]
        end = epoch(record['baseline_end_at'])
        baseline = summarize_window(rows, end - 60, end)
        if baseline['failures'] or baseline['requests'] < record['rate'] * 54:
            raise RuntimeError('S1 automatic recovery deferred: invalid baseline')
        record['baseline_window'] = baseline
        host_baseline = json.loads((Path(record['evidence']) / 'hosts-baseline-start.json').read_text())
        source = record['service_compute_host']
        pressure = host_cpu_pressure(host_baseline[source], before_host[source])
        consecutive = 0
        start = stress_start
        cpu_start = before_cpu
        for attempt in range(POLICY['max_windows']):
            window_start = utc_now()
            time.sleep(POLICY['window_seconds'])
            window_end = utc_now()
            current = host_sample('decision-' + str(attempt))
            cpu = self.s1.cpu_stat(record['service_before']['pod'])
            raw = self.s1.k('-n', NAMESPACE, 'logs', 'job/' + job_name, timeout=60)
            rows = [json.loads(line) for line in raw.splitlines()]
            window = summarize_window(rows, epoch(window_start), epoch(window_end))
            metrics = {host: interval(start[host], current[host]) for host in current}
            decision = diagnose(baseline, window, metrics[source], cpu_start, cpu, pressure, record['rate'])
            consecutive = consecutive + 1 if decision['trigger'] else 0
            self.event(record, {'kind': 'diagnosis', 'attempt': attempt, 'window': window,
                                'host_metrics': metrics, 'consecutive': consecutive, **decision})
            if consecutive >= POLICY['consecutive_windows']:
                record['decision_metrics'] = metrics
                record['automatic_trigger'] = True
                self.write(record, 'diagnosed', diagnosis_at=utc_now())
                return cpu, current
            start, cpu_start = current, cpu
        self.write(record, 'deferred', defer_reason='sustained_service_and_host_evidence_missing')
        raise RuntimeError('S1 automatic recovery deferred: sustained evidence missing')

    def move_service(self, record):
        source = self.s1.verify()
        if any(source[k] != record['service_before'][k] for k in
               ('pod_uid', 'nova_id', 'image_id', 'container_id', 'restart_count')):
            raise RuntimeError('S1 source changed before automatic action')
        source_place = self.s1.placement(source['nova_id'])
        contender = self.server(record['server_id'])
        if source_place['compute_host'] != record['service_compute_host'] or\
                contender.get('status') != 'ACTIVE' or contender.get('OS-EXT-SRV-ATTR:host') != source_place['compute_host']:
            raise RuntimeError('S1 source/competitor placement changed')
        deployment = self.s1.obj('deployment', 'http')
        original = record['deployment_before']
        if deployment['metadata']['uid'] != original['metadata']['uid'] or deployment['spec'] != original['spec']:
            raise RuntimeError('S1 Deployment was changed by another controller')
        if deployment['spec']['replicas'] != 1 or deployment['spec']['strategy'] != {
                'type': 'RollingUpdate', 'rollingUpdate': {'maxSurge': 1, 'maxUnavailable': 0}}:
            raise RuntimeError('S1 requires surge-before-removal rollout')
        nodes = self.client.get('w', 'nodes')['items']
        pods = self.client.get('w', 'pods', '-A')['items']
        machines = self.client.get('m', 'machines', '-n', self.client.ns,
                                   '-l', 'cluster.x-k8s.io/cluster-name=' + self.client.cluster)['items']
        candidates = []
        for node in nodes:
            if 'node-role.kubernetes.io/control-plane' in node['metadata'].get('labels', {}):
                continue
            matches_machine = [m for m in machines if not m['metadata'].get('deletionTimestamp') and
                               m.get('status', {}).get('nodeRef', {}).get('name') == node['metadata']['name']]
            if len(matches_machine) != 1:
                continue
            provider = matches_machine[0].get('spec', {}).get('providerID', '')
            if not provider.startswith('openstack:///') or node['spec'].get('providerID') != provider:
                continue
            place = self.s1.placement(provider.removeprefix('openstack:///'))
            metrics = record['decision_metrics'].get(place['compute_host'])
            if not metrics or time.time() - epoch(metrics['time']) > POLICY['max_sample_age_seconds']:
                continue
            reasons = candidate_reasons(node, pods, deployment['spec']['template']['spec'],
                                        source_place['compute_host'], place, metrics)
            self.event(record, {'kind': 'candidate', 'node': node['metadata']['name'],
                                'placement': place, 'reasons': reasons})
            if not reasons:
                candidates.append((metrics['cpu_utilization'], node['metadata']['name'], node, place))
        if not candidates:
            self.write(record, 'deferred', defer_reason='no_eligible_destination')
            raise RuntimeError('S1 automatic recovery deferred: no eligible destination')
        _, _, node, place = min(candidates, key=lambda x: (x[0], x[1]))
        record.update(target_node=node['metadata']['name'], target_selector=node['metadata']['labels']['kubernetes.io/hostname'],
                      target_nova_id=place['nova_id'], target_compute_host=place['compute_host'])
        annotations = dict(deployment['metadata'].get('annotations', {}))
        annotations[COOLDOWN_KEY] = utc_now()
        selector = dict(deployment['spec']['template']['spec'].get('nodeSelector', {}))
        selector['kubernetes.io/hostname'] = record['target_selector']
        patch = [{'op': 'test', 'path': '/metadata/uid', 'value': deployment['metadata']['uid']},
                 {'op': 'test', 'path': '/metadata/resourceVersion', 'value': deployment['metadata']['resourceVersion']},
                 {'op': 'add', 'path': '/metadata/annotations', 'value': annotations},
                 {'op': 'add', 'path': '/spec/template/spec/nodeSelector', 'value': selector}]
        self.write(record, 'relocation-intent', relocation_intent_at=utc_now(), action_count=1)
        self.s1.k('-n', NAMESPACE, 'patch', 'deployment', 'http', '--type=json', '-p', json.dumps(patch))

    def observe_recovery(self, record, job_name):
        time.sleep(POLICY['recovery_settle_seconds'])
        observations = record['stabilization_observations'] = []
        consecutive = 0
        for attempt in range(POLICY['recovery_max_windows']):
            start = utc_now()
            time.sleep(POLICY['recovery_window_seconds'])
            end = utc_now()
            raw = self.s1.k('-n', NAMESPACE, 'logs', 'job/' + job_name, timeout=60)
            rows = [json.loads(line) for line in raw.splitlines()]
            window = summarize_window(rows, epoch(start), epoch(end))
            healthy = stable_window(window, record['baseline_window']['latency_ms']['p95'], record['rate'])
            consecutive = consecutive + 1 if healthy else 0
            observations.append(window)
            self.event(record, {'kind': 'stabilization', 'attempt': attempt,
                                'window': window, 'healthy': healthy, 'consecutive': consecutive})
            if consecutive >= POLICY['recovery_consecutive_windows']:
                record['stabilization_windows'] = observations[-POLICY['recovery_consecutive_windows']:]
                self.write(record, 'service-stable', recovery_confirmed_at=utc_now())
                return
            self.write(record, 'stabilizing')
        record['stabilization_windows'] = observations[-POLICY['recovery_consecutive_windows']:]
        self.write(record, 'recovery-needs-review', recovery_confirmed_at=None)

    def recovery_window_start(self, record):
        return epoch(record['stabilization_windows'][-1]['start'])

    def recovery_checks(self, record, rows, baseline_p95):
        # Recompute the online-selected windows from the final immutable request log.
        windows = [summarize_window(rows, epoch(w['start']), epoch(w['end']))
                   for w in record['stabilization_windows']]
        record['stabilization_windows'] = windows
        last = max(epoch(row['time']) for row in rows) + 1 / record['rate']
        final_window = summarize_window(rows, last - POLICY['recovery_window_seconds'], last)
        record['final_window'] = final_window
        deployment = self.s1.obj('deployment', 'http')
        before = copy.deepcopy(record['deployment_before']['spec'])
        after = copy.deepcopy(deployment['spec'])
        before['template']['spec'].pop('nodeSelector', None)
        after['template']['spec'].pop('nodeSelector', None)
        checks = {'automatic_trigger': record.get('automatic_trigger') is True,
                  'one_action': record.get('action_count') == 1,
                  'workload_configuration_unchanged': before == after,
                  'three_stable_windows': bool(record.get('recovery_confirmed_at')) and
                      len(windows) == POLICY['recovery_consecutive_windows'] and
                      all(stable_window(w, baseline_p95, record['rate']) for w in windows),
                  'final_window_stable': stable_window(final_window, baseline_p95, record['rate']),
                  'all_requests_successful': all(row['ok'] for row in rows)}
        self.event(record, {'kind': 'recovery', 'windows': windows, 'final_window': final_window, 'checks': checks})
        return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'cleanup', 'status'))
    parser.add_argument('--seconds', type=int, default=1080)
    args = parser.parse_args()
    runner = S1Automatic()
    result = runner.run(seconds=args.seconds) if args.action == 'run' else runner.cleanup() if args.action == 'cleanup' else runner.read()
    print(json.dumps(result, indent=2))
    if args.action == "run" and result["state"] != "passed":
        raise SystemExit(2)


if __name__ == '__main__':
    main()
