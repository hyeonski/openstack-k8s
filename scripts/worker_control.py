#!/usr/bin/env python3
"""Local operator ownership of the workload worker MachineDeployment."""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time

from workload_state import Client, now
import workload_state


class WorkerControl:
    def __init__(self, client: Client):
        self.client = client
        self.state_path = client.state / 'worker-control.json'
        self.journal_path = client.state / 'worker-operation.json'
        self.lock_path = client.state / 'worker-operation.lock'
        self.lock = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.lock = self.lock_path.open('a+')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.lock.close()
            raise
        self.previous_command_lock = workload_state.COMMAND_LOCK_FD
        workload_state.COMMAND_LOCK_FD = self.lock.fileno()
        return self

    def __exit__(self, *_):
        workload_state.COMMAND_LOCK_FD = self.previous_command_lock
        self.lock.close()

    def read(self, path):
        return json.loads(path.read_text()) if path.exists() else None

    def write(self, path, data):
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def clear_journal(self):
        self.journal_path.unlink(missing_ok=True)
        directory = os.open(self.journal_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def observe(self):
        cluster = self.client.get('m', 'cluster', self.client.cluster, '-n', self.client.ns)
        md = self.client.get('m', 'machinedeployment', self.client.cluster + '-md-0', '-n', self.client.ns)
        ca = self.client.get('m', 'deployment', 'cluster-autoscaler', '-n', os.environ['CLUSTER_AUTOSCALER_NAMESPACE'])
        ca_pods = self.client.get('m', 'pods', '-n', os.environ['CLUSTER_AUTOSCALER_NAMESPACE'],
                                  '-l', 'app.kubernetes.io/name=cluster-autoscaler')['items']
        desired = md['spec']['replicas']
        if desired not in (1, 2, 3):
            raise RuntimeError(f'worker desired replicas outside 1:3: {desired}')
        ca_replicas = ca['spec'].get('replicas', 1)
        if ca_replicas not in (0, 1):
            raise RuntimeError(f'unexpected Cluster Autoscaler replicas: {ca_replicas}')
        return {'cluster_uid': cluster['metadata']['uid'], 'md_uid': md['metadata']['uid'],
                'ca_uid': ca['metadata']['uid'], 'md': md, 'ca': ca,
                'workers': desired, 'ca_replicas': ca_replicas, 'ca_pods': ca_pods}

    @staticmethod
    def identity(observed):
        return {key: observed[key] for key in ('cluster_uid', 'md_uid', 'ca_uid')}

    @staticmethod
    def stable_workers(observed):
        md = observed['md']
        desired = observed['workers']
        status = md.get('status', {})
        return (all(status.get(key, 0) == desired for key in ('replicas', 'readyReplicas', 'availableReplicas'))
                and status.get('observedGeneration', md['metadata'].get('generation', 0)) >= md['metadata'].get('generation', 0))

    def require_identity(self, record, observed):
        if record['identity'] != self.identity(observed):
            raise RuntimeError('worker control state belongs to different cluster/MD/CA UIDs; inspect before adopting')

    def mode(self, observed):
        record = self.read(self.state_path)
        if record:
            self.require_identity(record, observed)
            if record.get('version') != 1 or record['mode'] not in ('auto', 'fixed'):
                raise RuntimeError('invalid worker control mode')
            return record['mode']
        if observed['ca_replicas'] != 1 or observed['ca'].get('status', {}).get('availableReplicas', 0) != 1:
            raise RuntimeError('unrecorded CA state is ambiguous; inspect and restore it before selecting a worker mode')
        self.record_mode('auto', observed)
        return 'auto'

    def record_mode(self, mode, observed):
        self.write(self.state_path, {'version': 1, 'mode': mode, 'identity': self.identity(observed), 'updated': now()})

    def require_mode_state(self, mode, observed):
        if mode not in ('auto', 'fixed'):
            raise RuntimeError('invalid worker control mode')
        ca = observed['ca']
        if mode == 'auto':
            if observed['ca_replicas'] != 1 or ca.get('status', {}).get('availableReplicas', 0) != 1:
                raise RuntimeError('auto mode requires one Available Cluster Autoscaler replica')
        elif observed['ca_replicas'] != 0 or observed['ca_pods'] or ca.get('status', {}).get('replicas', 0) != 0:
            raise RuntimeError('fixed mode requires Cluster Autoscaler to be stopped')

    def scale_ca(self, replicas):
        self.client.k('m', 'scale', 'deployment', 'cluster-autoscaler', '-n',
                      os.environ['CLUSTER_AUTOSCALER_NAMESPACE'], '--replicas=' + str(replicas))
        deadline = time.monotonic() + (300 if replicas else 120)
        while time.monotonic() < deadline:
            observed = self.observe()
            if replicas and observed['ca_replicas'] == 1 and observed['ca'].get('status', {}).get('availableReplicas', 0) == 1:
                return
            if (not replicas and observed['ca_replicas'] == 0 and not observed['ca_pods']
                    and observed['ca'].get('status', {}).get('replicas', 0) == 0):
                return
            time.sleep(3)
        raise TimeoutError('Cluster Autoscaler did not settle after mode change')

    def recover(self):
        journal = self.read(self.journal_path)
        if not journal:
            return
        observed = self.observe()
        self.require_identity(journal, observed)
        recorded = self.read(self.state_path)
        if not recorded:
            raise RuntimeError('worker mode record is missing during interrupted operation')
        self.require_identity(recorded, observed)
        if journal['kind'] == 'mode' and recorded['mode'] == journal.get('target_mode'):
            if not self.stable_workers(observed):
                raise RuntimeError('completed mode transition has an unstable MachineDeployment')
            self.require_mode_state(recorded['mode'], observed)
            self.clear_journal()
            return
        expected_mode = journal['mode'] if journal['kind'] == 'manual' else journal.get('from_mode')
        if recorded['mode'] != expected_mode:
            raise RuntimeError('worker mode record changed during interrupted operation')
        if not self.stable_workers(observed):
            raise RuntimeError('worker operation interrupted while MD is not stable; retry recovery after convergence')
        if journal['kind'] == 'manual':
            if observed['workers'] not in (journal['from'], journal['target']):
                raise RuntimeError('MD desired replicas changed outside interrupted manual operation')
            if observed['ca_replicas'] not in (0, journal['ca_before']):
                raise RuntimeError('CA replicas changed outside interrupted manual operation')
            if observed['ca_replicas'] != journal['ca_before']:
                self.scale_ca(journal['ca_before'])
            observed = self.observe()
            self.require_mode_state(journal['mode'], observed)
        elif journal['kind'] == 'mode':
            requested = journal['target_mode']
            target = 1 if requested == 'auto' else 0
            if observed['ca_replicas'] != target:
                self.scale_ca(target)
            observed = self.observe()
            if not self.stable_workers(observed):
                raise RuntimeError('worker MachineDeployment changed during mode transition; retry after convergence')
            self.require_mode_state(requested, observed)
            self.record_mode(requested, observed)
        else:
            raise RuntimeError('unknown worker operation journal kind')
        self.clear_journal()

    def preflight(self, expected_mode=None):
        self.recover()
        observed = self.observe()
        mode = self.mode(observed)
        self.require_mode_state(mode, observed)
        if expected_mode and mode != expected_mode:
            raise RuntimeError(f'worker mode is {mode}; expected {expected_mode}')
        return mode, observed

    def preflight_install(self, existing):
        self.recover()
        recorded = self.read(self.state_path)
        if not existing:
            if recorded:
                raise RuntimeError('CA is missing but worker control state exists; inspect before reinstalling')
            return
        observed = self.observe()
        if recorded:
            self.require_identity(recorded, observed)
            if recorded['mode'] != 'auto':
                raise RuntimeError('CA installation would override fixed worker mode')
        if observed['ca_replicas'] != 1:
            raise RuntimeError('CA installation would start an intentionally stopped or interrupted CA')

    def switch_mode(self, target):
        if target not in ('auto', 'fixed'):
            raise ValueError('mode must be auto or fixed')
        mode, observed = self.preflight()
        if not self.stable_workers(observed):
            raise RuntimeError('worker MachineDeployment must be stable before switching modes')
        if mode == target:
            return
        from test_resources import residues
        if residues(self.client):
            raise RuntimeError('owned test resources remain; run cluster-autoscaler-test-cleanup first')
        self.write(self.journal_path, {'version': 1, 'kind': 'mode', 'identity': self.identity(observed),
                                       'from_mode': mode, 'target_mode': target, 'started': now()})
        self.scale_ca(1 if target == 'auto' else 0)
        observed = self.observe()
        if not self.stable_workers(observed):
            raise RuntimeError('worker MachineDeployment changed during mode transition; operation journal preserved')
        self.require_mode_state(target, observed)
        self.record_mode(target, observed)
        self.clear_journal()

    def begin_manual(self, target):
        mode, observed = self.preflight()
        if not self.stable_workers(observed):
            raise RuntimeError('worker MachineDeployment must be stable before manual scaling')
        self.write(self.journal_path, {'version': 1, 'kind': 'manual', 'identity': self.identity(observed),
                                       'mode': mode, 'ca_before': observed['ca_replicas'],
                                       'from': observed['workers'], 'target': int(target), 'started': now()})

    def finish_manual(self):
        journal = self.read(self.journal_path)
        observed = self.observe()
        self.require_identity(journal, observed)
        if observed['workers'] != journal['target'] or not self.stable_workers(observed):
            raise RuntimeError('manual worker target has not converged; operation journal preserved')
        if observed['ca_replicas'] != 0:
            raise RuntimeError('CA changed during manual scaling; operation journal preserved')
        if journal['ca_before']:
            self.scale_ca(journal['ca_before'])
        observed = self.observe()
        self.require_mode_state(journal['mode'], observed)
        self.clear_journal()
