#!/usr/bin/env python3
"""Compose environment and S4 scenario stages without rebuilding ready infrastructure."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import sys
import uuid

from graduation_env import atomic_json, utc_now
from graduation_s4_analyze import analyze
from workload_state import Client, ROOT, command


TERMINAL = {'completed', 'failed'}


class Workflow:
    def __init__(self, client=None, runner=None):
        self.client = client or Client()
        self.state = self.client.state
        self.path = self.state / 's4-workflow.json'
        self.lock_path = self.state / 's4-workflow.lock'
        self.runner = runner or command

    def read(self):
        return json.loads(self.path.read_text()) if self.path.exists() else None

    def write(self, data, phase, **values):
        data.update(values)
        data['phase'] = phase
        data['updated'] = utc_now()
        atomic_json(self.path, data)
        print('S4 workflow: ' + phase, flush=True)

    def step(self, target, timeout):
        return self.runner(['make', '--no-print-directory', '-C', ROOT, target], timeout=timeout)

    def environment(self):
        path = self.state / 'graduation-environment.json'
        if not path.is_file():
            raise RuntimeError('run graduation-env-ensure first')
        record = json.loads(path.read_text())
        expected = {'environment': os.environ['ENVIRONMENT_NAME'],
                    'project': os.environ['GCP_PROJECT_ID'],
                    'zone': os.environ['GCP_ZONE'], 'cluster': self.client.cluster}
        if record.get('phase') != 'ready' or record.get('profile') != expected:
            raise RuntimeError('S4 workflow requires a Ready environment for this profile')
        return record

    def experiment(self):
        path = self.state / 's4-experiment.json'
        return json.loads(path.read_text()) if path.exists() else None

    def fixture(self):
        path = self.state / 's4-preparation.json'
        return json.loads(path.read_text()) if path.exists() else None

    def safe_to_cleanup(self, environment_run_id):
        fixture = self.fixture()
        if not fixture or fixture.get('environment_run_id') != environment_run_id:
            return False
        if fixture.get('phase') not in ('prepared', 'cleanup-failed'):
            return False
        experiment = self.experiment()
        if experiment and experiment.get('environment_run_id') == environment_run_id:
            if experiment.get('stop_intent_at') and experiment.get('phase') not in ('completed', 'completed_with_gap'):
                return False
        return True

    def run(self, include_environment=False):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            previous = self.read()
            if previous and previous['phase'] not in TERMINAL:
                raise RuntimeError('unfinished S4 workflow exists; inspect and reconcile before a new run')
            data = {'version': 1, 'run_id': 's4-workflow-' + uuid.uuid4().hex[:12],
                    'created': utc_now(), 'mode': 'e2e' if include_environment else 'scenario'}
            self.write(data, 'starting')
            environment_run_id = None
            cleanup_done = False
            try:
                if include_environment:
                    self.write(data, 'ensuring-environment')
                    self.step('graduation-env-ensure', 2400)
                environment = self.environment()
                environment_run_id = environment['run_id']
                self.write(data, 'preparing', environment_run_id=environment_run_id)
                self.step('graduation-s4-prepare', 4800)
                self.write(data, 'injecting')
                self.step('graduation-s4-inject', 3600)
                experiment = self.experiment()
                if not experiment or experiment.get('environment_run_id') != environment_run_id or\
                        experiment.get('phase') not in ('completed', 'completed_with_gap'):
                    raise RuntimeError('S4 fault run did not complete for this environment')
                self.write(data, 'analyzing', experiment_run_id=experiment['run_id'],
                           evidence=experiment['evidence'])
                analysis = analyze(Path(experiment['evidence']))
                if analysis['state'] != 'complete':
                    raise RuntimeError('S4 analysis is incomplete; inspect gaps and raw evidence')
                self.write(data, 'cleaning', analysis_state=analysis['state'])
                self.step('graduation-s4-cleanup', 4800)
                cleanup_done = True
                if include_environment:
                    self.write(data, 'stopping-environment')
                    self.step('graduation-env-down', 1800)
                fixture = self.fixture()
                environment_path = self.state / 'graduation-environment.json'
                final_environment = json.loads(environment_path.read_text())
                worker_path = self.state / 'worker-control.json'
                worker = json.loads(worker_path.read_text())
                if fixture.get('phase') != 'restored' or final_environment.get('phase') != (
                        'stopped' if include_environment else 'ready') or\
                        worker.get('mode') != fixture.get('original_mode'):
                    raise RuntimeError('S4 final fixture/environment/worker state did not match the workflow')
                atomic_json(Path(experiment['evidence']) / 'finalization.json',
                            {'time': utc_now(), 'workflow_run_id': data['run_id'],
                             'fixture_phase': fixture['phase'],
                             'worker_mode': worker['mode'],
                             'worker_count': fixture['restored_workers'],
                             'environment_phase': final_environment['phase'],
                             'gcp_host_statuses': {name: host['status'] for name, host in
                                                   final_environment.get('final_hosts', {}).items()}})
                analysis = analyze(Path(experiment['evidence']))
                self.write(data, 'completed', result={'analysis': str(Path(experiment['evidence']) /
                                                    'analysis/summary.json'),
                                                       'experiment_run_id': experiment['run_id'],
                                                       'http': analysis['service'],
                                                       'durations_seconds': analysis['durations_seconds']})
                return data
            except BaseException as exc:
                cleanup_error = None
                if environment_run_id and not cleanup_done and self.safe_to_cleanup(environment_run_id):
                    try:
                        self.step('graduation-s4-cleanup', 4800)
                        cleanup_done = True
                    except BaseException as failure:
                        cleanup_error = f'{type(failure).__name__}: {failure}'
                down_error = None
                if include_environment:
                    env_path = self.state / 'graduation-environment.json'
                    current = json.loads(env_path.read_text()) if env_path.exists() else None
                    fixture = self.fixture()
                    # Environment.down checks exact host ownership and IDs. Do
                    # not ask it to stop hosts while a current S4 fixture is
                    # still active or an injected fault is uncertain.
                    fixture_safe = not current or not fixture or\
                        fixture.get('environment_run_id') != current.get('run_id') or\
                        fixture.get('phase') == 'restored'
                    if current and fixture_safe:
                        try:
                            self.step('graduation-env-down', 1800)
                        except BaseException as failure:
                            down_error = f'{type(failure).__name__}: {failure}'
                self.write(data, 'failed', error=f'{type(exc).__name__}: {exc}',
                           cleanup_error=cleanup_error, down_error=down_error,
                           recovery_hint='Inspect s4-experiment/s4-preparation state; observe without reinjection if needed')
                raise


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    workflow = Workflow()
    if action == 'scenario':
        print(json.dumps(workflow.run(), indent=2, ensure_ascii=False))
    elif action == 'e2e':
        print(json.dumps(workflow.run(include_environment=True), indent=2, ensure_ascii=False))
    elif action == 'status':
        print(json.dumps(workflow.read(), indent=2, ensure_ascii=False))
    else:
        raise SystemExit('usage: graduation-s4-workflow.sh scenario|e2e|status')


if __name__ == '__main__':
    main()
