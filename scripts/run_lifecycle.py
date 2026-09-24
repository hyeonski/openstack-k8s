"""Durable, single-client lifecycle for the infrastructure autoscaler experiment.

Resume reconciles and cleans the previous attempt, then repeats measurement from
baseline. It never pretends an interrupted measurement was continuous.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import signal
import time
import uuid

from workload_state import ROOT, artifact_dir, command, now, save
from test_resources import RUN, cleanup, residues

TERMINAL = {'passed', 'cleaned'}


class Cancelled(Exception):
    pass


def install_signal_handlers():
    # InterruptedError can be swallowed by selector/waitpid EINTR retry loops.
    # A separate exception escapes those loops and reaches durable cleanup.
    def interrupted(signum, _frame):
        raise Cancelled(f'interrupted by signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)


def read_record(client):
    pointer = client.state / 'experiment-run.json'
    if not pointer.exists():
        return None, None
    ref = json.loads(pointer.read_text())
    path = Path(ref['path']).resolve()
    root = (ROOT / 'artifacts' / os.environ['ENVIRONMENT_NAME']).resolve()
    if path.parent != root or not path.name.startswith('autoscaler-run-'):
        raise RuntimeError('invalid experiment evidence path')
    record = json.loads((path / 'run.json').read_text())
    if record['run_id'] != ref['run_id'] or record['version'] != 1:
        raise RuntimeError('experiment registry identity mismatch')
    return path, record


def local_action(client, action, expected):
    path, record = read_record(client)
    if action == 'test-status':
        print(json.dumps({'record': record, 'evidence': str(path) if path else None,
                          'live_state_checked': False}, indent=2))
        return
    if not record or not expected or expected != record['run_id']:
        raise RuntimeError('cancel requires RUN_ID matching the current experiment')
    if record['state'] in TERMINAL:
        raise RuntimeError('experiment is already terminal')
    # Separate file: cancellation cannot race a runner update to run.json.
    from worker_control import WorkerControl
    WorkerControl(client).write(path / 'cancel.json', {'run_id': expected, 'time': now()})
    print('cancellation requested for ' + expected + '; resources are preserved until cleanup/resume')


def host_budget(client):
    names = [os.environ['CONTROLLER_NAME'], *os.environ['COMPUTE_NODE_NAMES'].split()]
    rows = json.loads(command(['gcloud', 'compute', 'instances', 'list',
                              '--project=' + os.environ['GCP_PROJECT_ID'],
                              '--filter=zone:(' + os.environ['GCP_ZONE'] + ')', '--format=json'], timeout=45))
    rows = {row['name']: row for row in rows if row['name'] in names}
    if len(rows) != len(names):
        raise RuntimeError('cannot establish runtime budget for every GCP host')
    deadlines = []
    for name in names:
        row = rows[name]
        seconds = int(row.get('scheduling', {}).get('maxRunDuration', {}).get('seconds', 0))
        if row.get('status') != 'RUNNING' or seconds <= 0 or not row.get('lastStartTimestamp'):
            raise RuntimeError('host is stopped or its automatic STOP deadline is unknown: ' + name)
        started = dt.datetime.fromisoformat(row['lastStartTimestamp'].replace('Z', '+00:00')).timestamp()
        deadlines.append(started + seconds)
    return min(deadlines), rows


def cleanup_integrity(baseline, before, after):
    """Allow cancellation during VM creation, but reject leaked or shared resources."""
    from autoscaler_cycle import identities
    old, new = identities(before), identities(after)
    cp = lambda rows: [r for r in rows if r['control_plane']]
    if cp(identities(baseline)) != cp(new):
        raise RuntimeError('control plane identity changed during cleanup')
    for kind in ('networks', 'subnets', 'routers', 'security_groups'):
        if not {r['id'] for r in baseline['nova'][kind]} <= {r['id'] for r in after['nova'][kind]}:
            raise RuntimeError('shared OpenStack resource disappeared: ' + kind)
    retained_servers = {row['server'] for row in new}
    old_servers = {row['server'] for row in identities(baseline) + old if row['server']}
    retired_port_ids = {p['id'] for source in (baseline, before) for p in source['nova']['ports']
                        if p.get('device_id') in old_servers - retained_servers}
    if retired_port_ids & {p['id'] for p in after['nova']['ports']}:
        raise RuntimeError('retired worker port remains after cleanup')
    baseline_ports = {row['id'] for row in baseline['nova']['ports']}
    extra_ports = [row['id'] for row in after['nova']['ports']
                   if row['id'] not in baseline_ports and row.get('device_id') not in retained_servers]
    if extra_ports:
        raise RuntimeError('unaccounted ports after cleanup: ' + ','.join(extra_ports))
    # Existing endpoint/shared FIPs must survive; new unowned FIPs must not leak.
    initial_fips = {row['id'] for row in baseline['nova']['floating_ips']}
    if {row['id'] for row in after['nova']['floating_ips']} != initial_fips:
        raise RuntimeError('floating IP inventory changed during cleanup')
    removed = [row for row in old if row['machine_uid'] not in {r['machine_uid'] for r in new}]
    for row in removed:
        if any(o['metadata']['name'] == row['osmachine'] for o in after['osmachines']['items']):
            raise RuntimeError('removed worker OpenStackMachine remains')
        if row['server'] and any(s['id'] == row['server'] for s in after['nova']['servers']):
            raise RuntimeError('removed worker Nova server remains')
        if row['server'] and any(p.get('device_id') == row['server'] for p in after['nova']['ports']):
            raise RuntimeError('removed worker port remains')
    return removed


class RunLifecycle:
    def __init__(self, client, control):
        self.client, self.control = client, control
        self.path, self.record = read_record(client)

    def active(self):
        return self.record is not None and self.record['state'] not in TERMINAL

    def require_idle(self):
        if self.active():
            raise RuntimeError('unfinished experiment ' + self.record['run_id'] +
                               '; use test-status, test-reconcile, test-resume or test-cleanup')

    def update(self, state, **fields):
        self.record.update(fields, state=state, updated=now())
        self.record.setdefault('history', []).append({'time': now(), 'state': state,
                                                      'attempt': self.record['attempt']})
        self.control.write(self.path / 'run.json', self.record)

    def check(self):
        if (self.path / 'cancel.json').exists():
            raise Cancelled('operator requested cancellation')
        remaining = self.record['deadline_epoch'] - time.time()
        if remaining <= 0:
            raise TimeoutError('whole experiment deadline exceeded; cleanup remains available')
        return remaining

    def archive_interrupted(self):
        """Fill crash evidence without overwriting an earlier attempt's result."""
        attempt = self.path / ('autoscaler-cycle-attempt-' + str(self.record['attempt']).zfill(3))
        if not attempt.is_dir():
            return
        if not (attempt / 'result.json').exists():
            save(attempt / 'result.json', {'state': 'interrupted', 'time': now(),
                                          'reason': 'runner lost; recovered under exclusive lock',
                                          'cleanup': 'not attempted; reconcile actual resources'})
        if not (attempt / 'observability-manifest.json').exists():
            command(['python3', ROOT / 'observability/build-run-manifest.py', attempt], timeout=30)

    def identity(self):
        _, observed = self.control.preflight('auto')
        if self.record and self.record['identity'] != self.control.identity(observed):
            raise RuntimeError('experiment cluster/MD/CA identity changed; refusing adoption or deletion')
        return observed

    def inspect(self, destination):
        observed = self.identity()
        snapshot = self.client.snapshot(destination / 'snapshot.json')
        if self.client.run_check:
            self.client.run_check()
        if snapshot['errors']:
            raise RuntimeError('resource reconciliation unavailable: ' + ','.join(snapshot['errors']))
        owned = residues(self.client)
        save(destination / 'resources.json', [{'plane': p, 'object': o} for p, o in owned])
        foreign = [o['metadata']['name'] for _, o in owned
                   if o['metadata'].get('labels', {}).get(RUN) != self.record['owner_id']]
        if foreign:
            raise RuntimeError('other experiment resources exist; preserve them: ' + ','.join(foreign))
        known = {}
        for entry in sorted(self.path.glob('autoscaler-cycle-attempt-*/**/*created*.json')):
            obj = json.loads(entry.read_text())
            if 'metadata' in obj:
                meta = obj['metadata']
                known[(obj['kind'], meta['namespace'], meta['name'])] = meta['uid']
        for _, obj in owned:
            meta = obj['metadata']
            original = known.get((obj['kind'], meta['namespace'], meta['name']))
            if original and original != meta['uid']:
                raise RuntimeError('owned resource UID changed: ' + meta['name'])
        if snapshot['md']['spec']['replicas'] not in (1, 2, 3):
            raise RuntimeError('worker resource ceiling exceeded')
        baseline = self.path / 'baseline.json'
        if baseline.exists():
            old = json.loads(baseline.read_text())
            from autoscaler_cycle import identities
            cp = lambda s: [r for r in identities(s) if r['control_plane']]
            if cp(snapshot) != cp(old):
                raise RuntimeError('control plane identity changed during experiment')
        return snapshot, observed

    def clean(self):
        from autoscaler_cycle import stage
        folder = self.path / ('cleanup-' + uuid.uuid4().hex[:8])
        self.update('cleaning', runner_pid=os.getpid())
        self.client.deadline = None
        try:
            stop, _ = host_budget(self.client)
            # Cleanup has an independent bound and must finish before host STOP.
            deadline = min(time.time() + 2400, stop - 120)
            def check_cleanup():
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError('cleanup deadline exceeded; resources and evidence preserved')
                return remaining
            self.client.run_check = check_cleanup
            before, _ = self.inspect(folder / 'before')
            cleanup(self.client, folder, self.record['owner_id'])
            after = stage(self.client, folder / 'baseline', 1, None, 0)
            baseline_path = self.path / 'baseline.json'
            baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else before
            removed = cleanup_integrity(baseline, before, after)
            if residues(self.client):
                raise RuntimeError('test resources remain after cleanup')
            save(folder / 'result.json', {'state': 'cleaned', 'time': now(), 'removed': removed})
            self.update('cleaned', cleanup_evidence=str(folder))
            save(self.path / 'result.json', {'state': 'cleaned', 'time': now(),
                                           'run_id': self.record['run_id'], 'attempt': self.record['attempt']})
        except BaseException as exc:
            save(folder / 'result.json', {'state': 'cleanup_failed', 'time': now(), 'reason': str(exc)})
            self.update('cleanup_failed', reason=str(exc), cleanup_evidence=str(folder))
            save(self.path / 'result.json', {'state': 'cleanup_failed', 'time': now(),
                                           'run_id': self.record['run_id'], 'reason': str(exc)})
            raise
        finally:
            self.client.run_check = None
            self.client.deadline = None

    def execute(self, action):
        from autoscaler_cycle import run
        if action != 'test':
            if not self.active():
                raise RuntimeError('no unfinished experiment to reconcile, resume or clean')
            expected = os.environ.get('RUN_ID', '')
            if not expected or expected != self.record['run_id']:
                raise RuntimeError('RUN_ID must match the unfinished experiment')
            self.identity()
            self.archive_interrupted()
            if action == 'test-reconcile':
                destination = self.path / ('reconcile-' + uuid.uuid4().hex[:8])
                self.inspect(destination)
                self.update('interrupted', reconciliation=str(destination))
                print(json.dumps(self.record, indent=2))
                return
            if action == 'cleanup':
                self.clean()
                return
            # Reject expired resumption before deleting or clearing cancellation.
            if time.time() >= self.record['deadline_epoch']:
                raise TimeoutError('experiment deadline expired; cleanup then start a new run')
            self.clean()
            if time.time() >= self.record['deadline_epoch']:
                raise TimeoutError('deadline expired during cleanup; start a new run')
            if (self.path / 'cancel.json').exists():
                (self.path / 'cancel.json').rename(self.path / ('cancel-' + uuid.uuid4().hex[:8] + '.json'))
        else:
            self.require_idle()
            # A completed prior run must not restrict the identity of a new run.
            self.record = None
            observed = self.identity()
            if residues(self.client):
                raise RuntimeError('previous test resources exist; inspect and clean them before starting')
            seconds = int(os.environ.get('RUN_TIMEOUT_SECONDS', '14400'))
            if not 60 <= seconds <= 28800:
                raise ValueError('RUN_TIMEOUT_SECONDS must be 60..28800')
            stop, hosts = host_budget(self.client)
            if stop - time.time() < seconds + 900:
                raise RuntimeError('insufficient host runtime for the requested run plus 15 minute reserve')
            self.path = artifact_dir('autoscaler-run')
            self.record = {'version': 1, 'run_id': self.path.name, 'owner_id': uuid.uuid4().hex[:12],
                           'identity': self.control.identity(observed), 'attempt': 0, 'created': now(),
                           'deadline_epoch': time.time() + seconds, 'timeout_seconds': seconds,
                           'limits': {'workers': 3, 'load_pods': 3, 'load_memory_mib': 96},
                           'retention': 'retain local evidence indefinitely; no automatic evidence deletion',
                           'resume_policy': 'reconcile, clean owned resources, repeat from baseline'}
            self.update('created')
            self.control.write(self.client.state / 'experiment-run.json',
                               {'run_id': self.record['run_id'], 'path': str(self.path)})
            save(self.path / 'host-budget.json', hosts)
        self.record['attempt'] += 1
        attempt = self.path / ('autoscaler-cycle-attempt-' + str(self.record['attempt']).zfill(3))
        attempt.mkdir(mode=0o700)
        self.update('running', attempt_evidence=str(attempt), runner_pid=os.getpid(), reason=None)
        print('run_id=' + self.record['run_id'] + '\nevidence=' + str(attempt), flush=True)
        self.client.run_check = self.check
        try:
            self.check()
            snapshot, _ = self.inspect(attempt / 'admission')
            if not (self.path / 'baseline.json').exists():
                save(self.path / 'baseline.json', snapshot)
            # Use command() so a cancellation/signal terminates its process group.
            save(attempt / 'verify.log', command([ROOT / 'scripts/cluster-autoscaler.sh', 'verify'],
                                                timeout=min(300, self.check())))
            run(self.client, attempt, owner_id=self.record['owner_id'])
            self.check()
            self.update('passed')
        except BaseException as exc:
            if isinstance(exc, (Cancelled, KeyboardInterrupt, InterruptedError)):
                state = 'cancelled'
            elif isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
                state = 'timed_out'
            else:
                state = 'failed'
            self.update(state, reason=str(exc))
            save(attempt / 'result.json', {'state': state, 'time': now(), 'reason': str(exc),
                                          'cleanup': 'not attempted; owned resources preserved'})
            raise
        finally:
            self.client.run_check = None
            self.client.deadline = None
            try:
                command(['python3', ROOT / 'observability/build-run-manifest.py', attempt], timeout=30)
            except BaseException as exc:
                save(attempt / 'manifest-error.txt', str(exc))
            save(self.path / 'result.json', {'state': self.record['state'], 'time': now(),
                                           'run_id': self.record['run_id'], 'attempt': self.record['attempt']})
