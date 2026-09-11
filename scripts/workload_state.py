#!/usr/bin/env python3
"""Read-only snapshots and convergence checks; also used by the CA cycle runner."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def command(args, *, data=None, timeout=60):
    # Kill the process group too (gcloud/SSH grandchildren must not outlive a deadline).
    with subprocess.Popen([str(a) for a in args], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, start_new_session=True) as proc:
        try:
            out, err = proc.communicate(data, timeout=timeout)
        except BaseException:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            raise
        if proc.returncode:
            raise RuntimeError(f"command failed ({proc.returncode}): {args[0]}: {err.strip()}")
        return out


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    text = value if isinstance(value, str) else json.dumps(value, indent=2) + '\n'
    # Reuse the repository's redaction contract for all durable evidence.
    text = command(['python3', ROOT / 'scripts/redact-output.py'], data=text)
    path.write_text(text)
    path.chmod(0o600)


def artifact_dir(prefix):
    path = ROOT / 'artifacts' / os.environ['ENVIRONMENT_NAME'] / (
        prefix + '-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    path.mkdir(parents=True, mode=0o700)
    return path


class Client:
    def __init__(self):
        self.cluster = os.environ['WORKLOAD_CLUSTER_NAME']
        self.ns = os.environ['WORKLOAD_NAMESPACE']
        self.state = ROOT / '.state' / os.environ['ENVIRONMENT_NAME']
        self.deadline = None

    def remaining(self, limit):
        if self.deadline is None:
            return limit
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('stage deadline exceeded')
        return min(limit, remaining)

    def k(self, plane, *args, data=None):
        config = 'management' if plane == 'm' else self.cluster
        return command(['kubectl', '--kubeconfig', self.state / 'kubeconfigs' / (config + '.yaml'),
                        '--request-timeout=15s', *args], data=data, timeout=self.remaining(30))

    def get(self, plane, resource, *args):
        return json.loads(self.k(plane, 'get', resource, *args, '-o', 'json'))

    def snapshot(self, path):
        s = {'time': now(), 'errors': {}}
        selector = 'cluster.x-k8s.io/cluster-name=' + self.cluster
        queries = {
            'cluster': ('m', 'cluster', self.cluster, '-n', self.ns),
            'kcp': ('m', 'kubeadmcontrolplane', self.cluster + '-control-plane', '-n', self.ns),
            'md': ('m', 'machinedeployment', self.cluster + '-md-0', '-n', self.ns),
            'machinesets': ('m', 'machinesets', '-n', self.ns, '-l', selector),
            'machines': ('m', 'machines', '-n', self.ns, '-l', selector),
            'osmachines': ('m', 'openstackmachines', '-n', self.ns, '-l', selector),
            'oscluster': ('m', 'openstackcluster', self.cluster, '-n', self.ns),
            'nodes': ('w', 'nodes'), 'pods': ('w', 'pods', '-A'),
            'calico': ('w', 'daemonset', 'calico-node', '-n', 'kube-system'),
        }
        for key, args in queries.items():
            try:
                s[key] = self.get(*args)
            except (RuntimeError, subprocess.TimeoutExpired, TimeoutError, ValueError) as exc:
                s['errors'][key] = str(exc)
        try:
            s['nova'] = json.loads(command([ROOT / 'scripts/workload-inventory.sh'], timeout=self.remaining(210)))
        except (RuntimeError, subprocess.TimeoutExpired, TimeoutError, ValueError) as exc:
            s['errors']['nova'] = str(exc)
        save(path, s)
        return s


def items(s, key):
    return s[key].get('items', [])


def condition(obj, name):
    status = obj.get('status', {})
    conditions = status.get('conditions', status.get('v1beta2', {}).get('conditions', []))
    return any(c['type'] == name and c['status'] == 'True' for c in conditions)


def provider(obj):
    return obj.get('spec', {}).get('providerID') or ''


def evaluate(s, expected, env):
    if s.get('errors'):
        return 'unavailable', list(s['errors'])
    mismatch, pending = [], []
    containers = s['calico']['spec']['template']['spec']['containers']
    calico = next((c for c in containers if c['name'] == 'calico-node'), {})
    timeout = int(env['WORKLOAD_CALICO_PROBE_TIMEOUT_SECONDS'])
    for probe in ('startupProbe', 'readinessProbe', 'livenessProbe'):
        p = calico.get(probe, {})
        threshold = int(env['WORKLOAD_CALICO_STARTUP_FAILURE_THRESHOLD']) if probe == 'startupProbe' else 12
        if p.get('timeoutSeconds') != timeout or p.get('failureThreshold') != threshold:
            mismatch.append('Calico ' + probe + ' configuration drift; run explicit prepare')
    startup = calico.get('startupProbe', {})
    if startup.get('exec', {}).get('command') != ['/bin/calico-node', '-felix-live', '-bird-live'] or startup.get('periodSeconds') != 10:
        mismatch.append('Calico startup command/period drift')
    nodes, machines, osmachines = (items(s, k) for k in ('nodes', 'machines', 'osmachines'))
    cp = [n for n in nodes if 'node-role.kubernetes.io/control-plane' in n['metadata'].get('labels', {})]
    if len(cp) != 1 or len(nodes) != expected + 1:
        pending.append(f'Node count CP={len(cp)} total={len(nodes)} expected={expected+1}')
    md = s['md']
    for key in ('replicas', 'readyReplicas', 'availableReplicas'):
        if md.get('status', {}).get(key, 0) != expected:
            pending.append('MachineDeployment status.' + key)
    if md['spec'].get('replicas') != expected:
        pending.append('MachineDeployment desired replicas')
    for obj in (s['cluster'], s['kcp']):
        if not condition(obj, 'Available'):
            pending.append(obj['kind'] + ' Available')
    if s['cluster'].get('status', {}).get('controlPlane', {}).get('desiredReplicas') != 1:
        pending.append('Cluster control plane desired replicas')
    if s['kcp']['spec'].get('replicas') != 1:
        mismatch.append('control plane must stay at one')
    for status in (s['kcp'].get('status', {}), s['cluster'].get('status', {}).get('controlPlane', {})):
        for key in ('readyReplicas', 'availableReplicas'):
            if status.get(key) != 1:
                pending.append('control plane ' + key)
    if len(machines) != expected + 1 or len(osmachines) != expected + 1:
        pending.append('Machine/OpenStackMachine count (including deleting resources)')
    node_by_name = {n['metadata']['name']: n for n in nodes}
    osm_by_name = {o['metadata']['name']: o for o in osmachines}
    ids = set()
    for machine in machines:
        name = machine['metadata']['name']
        if not condition(machine, 'Ready'):
            pending.append(name + ' Machine not Ready')
        pid = provider(machine)
        node = node_by_name.get(machine.get('status', {}).get('nodeRef', {}).get('name'), {})
        osm = osm_by_name.get(machine['spec'].get('infrastructureRef', {}).get('name'), {})
        if not condition(osm, 'Ready') and osm.get('status', {}).get('ready') is not True:
            pending.append(name + ' OpenStackMachine not Ready')
        if machine['metadata'].get('deletionTimestamp') or osm.get('metadata', {}).get('deletionTimestamp'):
            pending.append(name + ' deleting')
        if not pid.startswith('openstack:///') or not any(a['type'] == 'InternalIP' and a.get('address') for a in machine.get('status', {}).get('addresses', [])):
            pending.append(name + ' providerID/InternalIP')
        elif provider(node) != pid or provider(osm) != pid:
            pending.append(name + ' Machine/Node/OpenStackMachine identity not converged')
        else:
            ids.add(pid.removeprefix('openstack:///'))
    servers = s['nova']['servers']
    relevant = [v for v in servers if v['id'] in ids or v['name'].startswith(env['WORKLOAD_CLUSTER_NAME'] + '-')]
    if len(ids) != expected + 1 or {v['id'] for v in relevant} != ids:
        pending.append('Nova server IDs/count do not match Machines')
    if any(v['status'] != 'ACTIVE' for v in relevant):
        pending.append('Nova not ACTIVE: ' + repr([(v['id'], v['status']) for v in relevant]))
    for node in nodes:
        info = node.get('status', {}).get('nodeInfo', {})
        if not info.get('kubeletVersion') or not info.get('architecture'):
            pending.append(node['metadata']['name'] + ' nodeInfo not populated yet')
        elif info.get('kubeletVersion') != env['KUBERNETES_VERSION'] or info.get('architecture') != env['WORKLOAD_KUBERNETES_ARCHITECTURE']:
            mismatch.append(node['metadata']['name'] + ' version/architecture')
        if not condition(node, 'Ready') or node.get('spec', {}).get('unschedulable'):
            pending.append(node['metadata']['name'] + ' not Ready/schedulable')
    pods = items(s, 'pods')
    for app in ('calico-node', 'calico-kube-controllers', 'kube-dns'):
        selected = [p for p in pods if p['metadata']['namespace'] == 'kube-system' and p['metadata'].get('labels', {}).get('k8s-app') == app and not p['metadata'].get('deletionTimestamp')]
        if not selected or any(not condition(p, 'Ready') for p in selected):
            pending.append(app + ' pods not Ready')
        if app == 'calico-node' and {p['spec'].get('nodeName') for p in selected} != set(node_by_name):
            pending.append('Calico coverage of all nodes')
    ds = s['calico']
    if ds.get('status', {}).get('observedGeneration', 0) < ds['metadata'].get('generation', 1) or ds.get('status', {}).get('updatedNumberScheduled') != len(nodes):
        pending.append('Calico rollout in progress')
    return ('mismatch', mismatch + pending) if mismatch else (('preparing', pending) if pending else ('ready', []))


def wait_ready(client, path, expected, timeout, stable=0):
    deadline = time.monotonic() + timeout
    client.deadline = deadline
    since = None
    index = 0
    last = None
    while time.monotonic() < deadline:
        snapshot = client.snapshot(path / f'{index:04d}.json')
        state, reasons = evaluate(snapshot, expected, os.environ)
        last = {'time': now(), 'state': state, 'reasons': reasons}
        save(path / 'result.json', last)
        print(f'{state}: workers={expected} {"; ".join(reasons)}', flush=True)
        if state == 'mismatch':
            raise RuntimeError('; '.join(reasons))
        if state == 'ready':
            since = since or time.monotonic()
            if time.monotonic() - since >= stable:
                client.deadline = None
                return snapshot
        else:
            since = None
        index += 1
        time.sleep(min(10, max(0, deadline-time.monotonic())))
    client.deadline = None
    save(path / 'result.json', {'state': 'timeout', 'last_observation': last, 'time': now()})
    raise TimeoutError(f'convergence timeout; last observation={last}')


def diagnostics(path):
    try:
        save(path / 'diagnostics.log', command([ROOT / 'scripts/workload-diagnostics.sh', 'status-failed'], timeout=180))
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        save(path / 'diagnostics-error.txt', str(exc))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('workers', type=int, choices=range(1, 4))
    parser.add_argument('--wait', type=int, default=0)
    args = parser.parse_args()
    path = artifact_dir('workload-status')
    print(f'evidence={path}', flush=True)
    client = Client()
    try:
        if args.wait:
            wait_ready(client, path, args.workers, args.wait)
        else:
            s = client.snapshot(path / 'snapshot.json')
            state, reasons = evaluate(s, args.workers, os.environ)
            save(path / 'result.json', {'state': state, 'reasons': reasons, 'time': now()})
            print(state + ': ' + '; '.join(reasons))
            return {'ready': 0, 'preparing': 10, 'mismatch': 20, 'unavailable': 30}[state]
    except TimeoutError as exc:
        print(exc)
        diagnostics(path)
        return 40
    except (RuntimeError, ValueError) as exc:
        print(exc)
        diagnostics(path)
        return 20
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
