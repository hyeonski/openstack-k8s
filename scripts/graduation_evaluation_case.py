#!/usr/bin/env python3
"""Frozen evaluation variants; production recovery thresholds are not relaxed."""
from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from graduation_env import atomic_json, utc_now
from graduation_recovery import RecoveryLab
from graduation_s1 import NAMESPACE
from graduation_s1_auto import S1Automatic
from graduation_s2 import S2
from graduation_s3 import S3, OUT, volume_matches
from graduation_s4 import S4Preparation
from graduation_s4_run import S4Run
from graduation_s4_workflow import Workflow
from workload_state import ROOT, command

SOURCE_HOST = 'osk8s-compute02'
TARGET_HOST = 'osk8s-compute01'
REJECTION_FILE = 'expected-rejection.json'


class ExpectedRejection(RuntimeError):
    pass


def checked_rejection(runner, kind, checks, detail):
    proof = {'time': utc_now(), 'kind': kind, 'checks': checks,
             'passed': all(checks.values()), 'detail': detail}
    runner.save(REJECTION_FILE, proof)
    if not proof['passed']:
        raise RuntimeError('negative case protection failed: ' + json.dumps(proof))
    raise ExpectedRejection(kind)


class EvaluationS1(S1Automatic):
    def __init__(self, mode, s1=None):
        super().__init__(s1)
        self.mode = mode

    def observe_contention(self, record, *args):
        record['evaluation_mode'] = self.mode
        if (record['service_compute_host'], record['target_compute_host'], record['probe_compute_host']) != (
                SOURCE_HOST, TARGET_HOST, TARGET_HOST):
            raise RuntimeError('S1 placement differs from the frozen evaluation profile')
        return super().observe_contention(record, *args)

    def move_service(self, record):
        if self.mode == 'automatic':
            return super().move_service(record)
        if self.mode == 'no-action':
            self.write(record, 'control-no-action', action_count=0)
            self.event(record, {'kind': 'control', 'mode': 'no-action', 'action_count': 0})
            return
        if self.mode != 'no-destination':
            raise ValueError(self.mode)
        name = record['target_node']
        node = self.s1.obj('node', name, None)
        key = 'openstack-k8s.dev/evaluation-unavailable'
        if any(t['key'] == key for t in node['spec'].get('taints', [])):
            raise RuntimeError('negative case taint already exists')
        deployment = self.s1.obj('deployment', 'http')
        negative_before = {'deployment': deployment, 'service': self.s1.verify(), 'node': node}
        taints = copy.deepcopy(node['spec'].get('taints', []))
        added = {'key': key, 'value': record['run_id'], 'effect': 'NoSchedule'}
        self.event(record, {'kind': 'negative-taint-intent', 'node': name, 'node_uid': node['metadata']['uid']})
        self.s1.k('patch', 'node', name, '--type=json', '-p', json.dumps([
            {'op': 'test', 'path': '/metadata/uid', 'value': node['metadata']['uid']},
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': node['metadata']['resourceVersion']},
            {'op': 'add', 'path': '/spec/taints', 'value': taints + [added]}]))
        rejected, detail = False, ''
        during = self.s1.obj('node', name, None)
        try:
            try:
                super().move_service(record)
            except RuntimeError as exc:
                rejected = 'no eligible destination' in str(exc)
                detail = str(exc)
            after = self.s1.obj('deployment', 'http')
            proof = {'time': utc_now(), 'kind': 'no-destination', 'detail': detail,
                     'checks': {'rejected': rejected,
                                'deployment_uid_unchanged': after['metadata']['uid'] == deployment['metadata']['uid'],
                                'deployment_spec_unchanged': after['spec'] == deployment['spec'],
                                'pod_unchanged': self.s1.verify()['pod_uid'] == record['service_before']['pod_uid'],
                                'no_action': record.get('action_count', 0) == 0}}
        finally:
            current = self.s1.obj('node', name, None)
            present = current['spec'].get('taints', [])
            if current['metadata']['uid'] != node['metadata']['uid'] or added not in present:
                raise RuntimeError('negative taint ownership changed; manual inspection required')
            self.s1.k('patch', 'node', name, '--type=json', '-p', json.dumps([
                {'op': 'test', 'path': '/metadata/uid', 'value': node['metadata']['uid']},
                {'op': 'test', 'path': '/metadata/resourceVersion', 'value': current['metadata']['resourceVersion']},
                {'op': 'add', 'path': '/spec/taints', 'value': [t for t in present if t != added]}]))
        proof['checks']['temporary_taint_removed'] = not any(
            t['key'] == key for t in self.s1.obj('node', name, None)['spec'].get('taints', []))
        atomic_json(Path(record['evidence']) / 'negative-raw.json', {
            'before': negative_before, 'during_node': during,
            'after': {'deployment': after, 'service': self.s1.verify(), 'node': self.s1.obj('node', name, None)}})
        proof['passed'] = all(proof['checks'].values())
        atomic_json(Path(record['evidence']) / REJECTION_FILE, proof)
        if not proof['passed']:
            raise RuntimeError('S1 negative case protection failed')
        raise ExpectedRejection('no-destination')

    def verify_intervention(self, record, moved):
        if self.mode != 'no-action':
            return super().verify_intervention(record, moved)
        before = record['service_before']
        if any(moved[k] != before[k] for k in ('pod_uid', 'node', 'nova_id', 'image_id', 'container_id', 'restart_count')):
            raise RuntimeError('no-action service was changed by another actor')
        if self.s1.placement(moved['nova_id'])['compute_host'] != SOURCE_HOST:
            raise RuntimeError('no-action source compute changed')

    def recovery_checks(self, record, rows, baseline_p95):
        if self.mode != 'no-action':
            return super().recovery_checks(record, rows, baseline_p95)
        after = self.s1.obj('deployment', 'http')
        return {'automatic_diagnosis': record.get('automatic_trigger') is True,
                'no_action': record.get('action_count') == 0,
                'configuration_unchanged': record['deployment_before']['spec'] == after['spec']}

    def evaluation_result(self, summary, valid):
        result = super().evaluation_result(summary, valid)
        result['evaluation_mode'] = self.mode
        if self.mode == 'no-action':
            result['state'] = 'control_valid' if valid and all(result['recovery_checks'].values()) else 'needs_review'
            result['control_meaning'] = 'valid observation without intervention; not a recovery success'
        return result


class OrderedWorkers:
    def start(self):
        workers = super().start()
        if {w['host'] for w in workers} != {SOURCE_HOST, TARGET_HOST}:
            raise RuntimeError('workers must occupy the two frozen compute roles')
        workers.sort(key=lambda w: (w['host'] != SOURCE_HOST, w['node']))
        self.write('evaluation-workers-ready', workers=workers, evaluation_mode=self.mode)
        return workers


class EvaluationS2(OrderedWorkers, S2):
    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        self.comparison_order = 'dynamic-first' if mode == 'dynamic-first' else 'fixed-first'

    def set_rate(self, rate):
        if self.mode != 'qos-rejection':
            return super().set_rate(rate)
        before = self.pods('upload')[0]
        port_before = self.admin_json('port', 'show', self.record['workers'][1]['port']['id'])
        rule_before = self.admin_json('network', 'qos', 'rule', 'show', self.record['policy_id'], self.record['rule_id'])
        rejected, detail = False, ''
        try:
            # Submit a real invalid rule to Neutron. A failed update must stop
            # the normal run before upload relocation or subsequent policies.
            super().set_rate(-1)
        except RuntimeError as exc:
            rejected, detail = True, str(exc)
        after = self.pods('upload')
        port = self.admin_json('port', 'show', self.record['workers'][1]['port']['id'])
        rule = self.admin_json('network', 'qos', 'rule', 'show', self.record['policy_id'], self.record['rule_id'])
        self.save('negative-raw.json', {'before': {'pod': before, 'port': port_before, 'rule': rule_before},
                                        'after': {'pods': after, 'port': port, 'rule': rule}})
        checked_rejection(self, 'qos-rejection', {
            'request_rejected': rejected,
            'upload_pod_unchanged': len(after) == 1 and after[0]['metadata']['uid'] == before['metadata']['uid'],
            'upload_node_unchanged': len(after) == 1 and after[0]['spec']['nodeName'] == before['spec']['nodeName'],
            'port_policy_unattached': not port.get('qos_policy_id'),
            'rule_original_rate_preserved': int(rule['max_kbps']) == 6000,
            'no_successful_policy_change': not self.record.get('policy_changes'),
        }, detail)


class EvaluationS3(OrderedWorkers, S3):
    def __init__(self, mode):
        super().__init__()
        self.mode = mode

    def runbook_step(self, step):
        record = self.record
        started = utc_now()
        result = subprocess.run([sys.executable, ROOT / 'scripts/graduation_evaluation_case.py',
                                 's3-step', '--mode', step, '--run-id', record['run_id'],
                                 '--lock-fd', str(self.lock.fileno())],
                                capture_output=True, text=True, timeout=1000, check=False,
                                pass_fds=(self.lock.fileno(),))
        self.record = json.loads(self.state.read_text())
        self.record.setdefault('runbook_steps', []).append({
            'step': step, 'started': started, 'finished': utc_now(), 'returncode': result.returncode,
            'operator': 'scripted explicit CLI; no human cognition/reaction time measured'})
        self.write(self.record['phase'])
        self.save('runbook-' + step + '.log', result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError('explicit runbook step failed: ' + step)

    def fence(self):
        if self.mode == 'runbook':
            return self.runbook_step('fence')
        if self.mode != 'fence-refusal':
            return super().fence()
        before = self.dbpod()
        rejected, detail = False, ''
        try:
            self.mark_out_of_service()
        except RuntimeError as exc:
            rejected, detail = 'fencing is unconfirmed' in str(exc), str(exc)
        source = self.record['source']
        server = self.admin_json('server', 'show', source['nova_id'])
        node = self.obj('node', source['node'], False)
        pvc = self.obj('pvc', 'data-db-0')
        pv = self.obj('pv', self.record['pv_name'], False)
        volume = self.admin_json('volume', 'show', self.record['volume_id'])
        volume_matches(pvc, pv, volume, self.record['pvc_uid'], source['nova_id'])
        self.save('negative-raw.json', {'before_pod': before, 'after_pod': self.dbpod(),
                                        'server': server, 'node': node, 'pvc': pvc, 'pv': pv, 'volume': volume})
        checked_rejection(self, 'fence-refusal', {
            'action_rejected': rejected, 'vm_still_active': server['status'] == 'ACTIVE',
            'no_out_of_service_taint': not any(t['key'] == OUT for t in node['spec'].get('taints', [])),
            'pod_uid_unchanged': self.dbpod()['metadata']['uid'] == before['metadata']['uid'],
            'volume_still_exclusively_on_source': True,
            'no_fence_request': not self.record.get('fence_requested_at'),
        }, detail)

    def activate_recovery(self):
        if self.mode == 'runbook':
            return self.runbook_step('recover')
        return super().activate_recovery()


class EvaluationS4Preparation(S4Preparation):
    def verify_http(self, workers):
        if self.read().get('phase') == 'app-applied':
            lab = RecoveryLab('s3')
            nodes = self.client.get('w', 'nodes')['items']
            bindings = [lab.binding(n) for n in nodes if 'node-role.kubernetes.io/control-plane' not in n['metadata'].get('labels', {})]
            choices = [w for w in bindings if w['host'] == SOURCE_HOST]
            if len(choices) != 1:
                raise RuntimeError('S4 evaluation source compute is ambiguous')
            hostname = choices[0]['node']
            # Soft preference allows recovery on the surviving worker.
            preferred = [{'weight': 100, 'preference': {'matchExpressions': [
                {'key': 'kubernetes.io/hostname', 'operator': 'In', 'values': [hostname]}]}}]
            patch = {'spec': {'template': {'spec': {'affinity': {'nodeAffinity': {
                'preferredDuringSchedulingIgnoredDuringExecution': preferred}}}}}}
            self.k('w', '-n', 'graduation-s4', 'patch', 'deployment', 'http', '--type=merge', '-p', json.dumps(patch))
            self.k('w', '-n', 'graduation-s4', 'rollout', 'status', 'deployment/http', '--timeout=5m', timeout=330)
            result = super().verify_http(workers)
            if result[0]['node'] != hostname:
                raise RuntimeError('S4 HTTP Pod did not start on frozen source compute')
            return result
        return super().verify_http(workers)


def s4_runner(args, timeout):
    if args[-1] == 'graduation-s4-prepare':
        return json.dumps(EvaluationS4Preparation().prepare())
    if args[-1] == 'graduation-s4-inject':
        return json.dumps(S4Run().run())
    return command(args, timeout=timeout)


def run_s3_step(mode, run_id, lock_fd):
    runner = S3()
    if lock_fd is None:
        raise RuntimeError('runbook command requires the owning evaluation lock')
    inherited = os.fstat(lock_fd)
    original = (runner.client.state / 'graduation-recovery.lock').stat()
    if (inherited.st_dev, inherited.st_ino) != (original.st_dev, original.st_ino):
        raise RuntimeError('runbook lock identity mismatch')
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if not runner.record or runner.record['run_id'] != run_id:
        raise RuntimeError('runbook step run identity mismatch')
    expected = {'fence': 'diagnosed', 'recover': 'fenced'}
    if runner.record['phase'] != expected[mode] or runner.record.get('evaluation_mode') != 'runbook':
        raise RuntimeError('runbook step phase/mode mismatch')
    runner.ownership()
    runner.fence() if mode == 'fence' else runner.activate_recovery()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', choices=('s1', 's2', 's3', 's4', 's3-step'))
    parser.add_argument('--mode', required=True)
    parser.add_argument('--run-id')
    parser.add_argument('--lock-fd', type=int)
    args = parser.parse_args()
    if args.scenario == 's3-step':
        if args.mode not in ('fence', 'recover'):
            parser.error('invalid runbook step')
        run_s3_step(args.mode, args.run_id, args.lock_fd)
        return
    if args.scenario == 's4':
        result = Workflow(runner=s4_runner).run()
        print(json.dumps(result, indent=2))
        return
    allowed = {'s1': {'automatic', 'no-action', 'no-destination'},
               's2': {'fixed-first', 'dynamic-first', 'qos-rejection'},
               's3': {'automatic', 'runbook', 'fence-refusal'}}
    if args.mode not in allowed[args.scenario]:
        parser.error('invalid evaluation mode')
    runner = {'s1': EvaluationS1, 's2': EvaluationS2, 's3': EvaluationS3}[args.scenario](args.mode)
    try:
        result = runner.run(seconds=1080) if args.scenario == 's1' else runner.run()
        print(json.dumps(result, indent=2))
        good = result.get('state') in ('passed', 'control_valid') if args.scenario == 's1' else result['passed']
        if not good:
            raise SystemExit(2)
    except ExpectedRejection:
        print('Expected live rejection confirmed; cleanup is required.', flush=True)
        raise SystemExit(20)


if __name__ == '__main__':
    main()
