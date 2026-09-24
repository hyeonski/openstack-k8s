#!/usr/bin/env python3
"""Bounded requests/replica driven CA 1→2→3→2→1→2→1 acceptance test."""
from __future__ import annotations
import json
import os
import datetime as dt
import importlib.util
import subprocess
import sys
import time
import uuid
from workload_state import Client, ROOT, artifact_dir, command, condition, evaluate, items, now, provider, save
from test_resources import OWNER, RUN, cleanup, delete_owned, probe, residues
from worker_control import WorkerControl
spec = importlib.util.spec_from_file_location('cpu_selection', ROOT / 'scripts/select-autoscaler-cpu.py')
cpu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cpu)


def identities(s):
    rows = []
    node_uids = {n['metadata']['name']: n['metadata']['uid'] for n in items(s, 'nodes')}
    osm_uids = {o['metadata']['name']: o['metadata']['uid'] for o in items(s, 'osmachines')}
    for m in items(s, 'machines'):
        rows.append({'machine': m['metadata']['name'], 'machine_uid': m['metadata']['uid'],
                     'osmachine': m['spec']['infrastructureRef']['name'],
                     'osmachine_uid': osm_uids.get(m['spec']['infrastructureRef']['name']),
                     'node_uid': node_uids.get(m.get('status', {}).get('nodeRef', {}).get('name')),
                     'node': m.get('status', {}).get('nodeRef', {}).get('name'),
                     'server': provider(m).removeprefix('openstack:///'),
                     'control_plane': 'cluster.x-k8s.io/control-plane' in m['metadata'].get('labels', {})})
    return rows


def retirement(before, after):
    """Identity-based deletion, plus shared-resource preservation (never delete here)."""
    old = identities(before)
    new = identities(after)
    old_cp = {r['machine_uid'] for r in old if r['control_plane']}
    new_cp = {r['machine_uid'] for r in new if r['control_plane']}
    if len(old_cp) != 1 or new_cp != old_cp:
        raise RuntimeError('control plane identity changed')
    removed = [r for r in old if r['machine_uid'] not in {n['machine_uid'] for n in new}]
    for row in removed:
        if row['control_plane']:
            raise RuntimeError('control plane deleted')
        for key, field, expected in [('osmachines', 'name', row['osmachine']), ('nodes', 'name', row['node'])]:
            if any(o['metadata'][field] == expected for o in items(after, key)):
                raise RuntimeError('removed worker still has ' + key + ': ' + str(expected))
        if any(v['id'] == row['server'] for v in after['nova']['servers']):
            raise RuntimeError('removed worker Nova server remains: ' + row['server'])
        old_ports = {p['id'] for p in before['nova']['ports'] if p.get('device_id') == row['server']}
        if not old_ports:
            raise RuntimeError('missing baseline worker port ownership evidence')
        if old_ports & {p['id'] for p in after['nova']['ports']}:
            raise RuntimeError('removed worker Neutron port remains')
        old_fips = {f['id'] for f in before['nova']['floating_ips'] if f.get('port') in old_ports or f.get('port_id') in old_ports}
        if old_fips & {f['id'] for f in after['nova']['floating_ips']}:
            raise RuntimeError('removed worker owned Floating IP remains')
        row['deleted_ports'] = sorted(old_ports)
        row['deleted_floating_ips'] = sorted(old_fips)
    for kind in ('networks', 'subnets', 'routers', 'security_groups'):
        if not {r['id'] for r in before['nova'][kind]} <= {r['id'] for r in after['nova'][kind]}:
            raise RuntimeError('shared OpenStack resource disappeared: ' + kind)
    # Retained nodes/VMs must retain identity, including the CP endpoint's FIP.
    removed_servers = {r['server'] for r in removed}
    for row in old:
        if row['server'] not in removed_servers and row not in new:
            raise RuntimeError('retained Machine identity changed')
    deleted_fips = {x for row in removed for x in row['deleted_floating_ips']}
    if not {f['id'] for f in before['nova']['floating_ips']} - deleted_fips <= {f['id'] for f in after['nova']['floating_ips']}:
        raise RuntimeError('retained/shared Floating IP disappeared')
    return removed


def verify_transition(before, after, direction, decisions):
    removed = retirement(before, after)
    old_uids = {r['machine_uid'] for r in identities(before)}
    added = [r for r in identities(after) if r['machine_uid'] not in old_uids]
    expected = {'up': (0, 1), 'down': (1, 0), None: (0, 0)}[direction]
    if (len(removed), len(added)) != expected:
        raise RuntimeError(f'unexpected worker replacement/change: removed={len(removed)} added={len(added)} expected={expected}')
    if direction == 'down' and not any(e.get('involvedObject', {}).get('uid') == removed[0]['node_uid'] for e in decisions):
        raise RuntimeError('missing CA ScaleDown event for the deleted Node UID')
    return removed


def choose_request(s):
    workers = [n for n in items(s, 'nodes') if 'node-role.kubernetes.io/control-plane' not in n['metadata'].get('labels', {})]
    if len(workers) != 1:
        raise RuntimeError('CPU selection requires exactly one worker')
    worker = workers[0]
    pods = {'items': [p for p in items(s, 'pods') if p['spec'].get('nodeName') == worker['metadata']['name']]}
    allocatable, requested, available, selected = cpu.select(worker, pods)
    # More than half of *allocatable*, including a fresh node without transient Pods.
    selected = max(selected, allocatable // 2 + 1)
    if selected > available:
        raise RuntimeError(f'capacity insufficient: allocatable={allocatable} requested={requested} required={selected}')
    return selected, {'allocatable_millicpu': allocatable, 'baseline_requested_millicpu': requested,
                      'available_millicpu': available, 'selected_request_millicpu': selected}


def deployment(name, ns, cluster, run, request, replicas):
    labels = {OWNER: cluster, RUN: run, 'app.kubernetes.io/name': name}
    return {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': name, 'namespace': ns, 'labels': labels},
            'spec': {'replicas': replicas, 'strategy': {'type': 'Recreate'}, 'selector': {'matchLabels': labels},
                     'template': {'metadata': {'labels': labels}, 'spec': {
                         'terminationGracePeriodSeconds': 0,
                         'affinity': {'nodeAffinity': {'requiredDuringSchedulingIgnoredDuringExecution': {'nodeSelectorTerms': [
                             {'matchExpressions': [{'key': 'node-role.kubernetes.io/control-plane', 'operator': 'DoesNotExist'}]}]}}},
                         'containers': [{'name': 'load', 'image': os.environ['CLUSTER_AUTOSCALER_TEST_IMAGE'],
                                         'command': ['sh', '-ceu', 'trap : TERM INT; sleep infinity & wait'],
                                         'resources': {'requests': {'cpu': f'{request}m', 'memory': '16Mi'},
                                                       'limits': {'cpu': f'{request}m', 'memory': '32Mi'}}}]}}}}


def pod_contract(s, name, request, replicas):
    pods = [p for p in items(s, 'pods') if p['metadata'].get('labels', {}).get('app.kubernetes.io/name') == name]
    # Include terminating Pods: old requests must actually leave scheduler accounting.
    if len(pods) != replicas or any(p['metadata'].get('deletionTimestamp') for p in pods):
        return False
    nodes = set()
    for pod in pods:
        if not condition(pod, 'Ready') or pod['spec']['containers'][0]['resources']['requests']['cpu'] != f'{request}m':
            return False
        nodes.add(pod['spec'].get('nodeName'))
    workers = {n['metadata']['name'] for n in items(s, 'nodes') if 'node-role.kubernetes.io/control-plane' not in n['metadata'].get('labels', {})}
    return len(nodes) == replicas and nodes == workers


def decision_evidence(client, path, started):
    failures = {}
    values = {}
    for key, args in {
        'workload-events': ('w', 'get', 'events', '-A', '-o', 'json'),
        'capi-events': ('m', 'get', 'events', '-n', client.ns, '-o', 'json'),
        'pdb': ('w', 'get', 'pdb', '-A', '-o', 'json'),
        'ca-status': ('w', 'get', 'configmap', 'cluster-autoscaler-status', '-n', os.environ['CLUSTER_AUTOSCALER_WORKLOAD_NAMESPACE'], '-o', 'json'),
        'ca-log': ('m', 'logs', 'deployment/cluster-autoscaler', '-n', os.environ['CLUSTER_AUTOSCALER_NAMESPACE'], '--since-time=' + started, '--timestamps=true'),
        'ca-deployment': ('m', 'get', 'deployment', 'cluster-autoscaler', '-n', os.environ['CLUSTER_AUTOSCALER_NAMESPACE'], '-o', 'json'),
    }.items():
        try:
            values[key] = client.k(*args)
            save(path / (key + '.txt'), values[key])
        except (RuntimeError, TimeoutError, subprocess.TimeoutExpired) as exc:
            failures[key] = str(exc)
    save(path / 'collection-errors.json', failures)
    return values, failures


def pending_cpu(s, name, events, old_uids=frozenset()):
    pod_uids = {p['metadata']['uid'] for p in items(s, 'pods') if p['metadata'].get('labels', {}).get('app.kubernetes.io/name') == name} - old_uids
    conditions = [c.get('message', '') for p in items(s, 'pods') if p['metadata']['uid'] in pod_uids for c in p.get('status', {}).get('conditions', []) if c['type'] == 'PodScheduled' and c['status'] == 'False']
    conditions += [e.get('message', '') for e in json.loads(events or '{"items":[]}')['items'] if e.get('involvedObject', {}).get('uid') in pod_uids and e.get('reason') == 'FailedScheduling']
    return [m for m in conditions if 'Insufficient cpu' in m]


def ca_decisions(events, direction, before, current, name, started):
    events = json.loads(events or '{"items": []}')['items']
    old_pods = {p['metadata']['uid'] for p in items(before, 'pods')} if before else set()
    new_pods = {p['metadata']['uid'] for p in items(current, 'pods') if p['metadata'].get('labels', {}).get('app.kubernetes.io/name') == name} - old_pods
    old_nodes = {n['metadata']['uid'] for n in items(before, 'nodes')} if before else set()
    found = []
    for event in events:
        timestamp = event.get('series', {}).get('lastObservedTime') or event.get('lastTimestamp') or event.get('eventTime') or event['metadata'].get('creationTimestamp')
        if not timestamp or dt.datetime.fromisoformat(timestamp.replace('Z', '+00:00')) < dt.datetime.fromisoformat(started):
            continue
        source = event.get('reportingComponent') or event.get('source', {}).get('component', '')
        if source != 'cluster-autoscaler':
            continue
        obj = event.get('involvedObject', {})
        if direction == 'up' and event.get('reason') == 'TriggeredScaleUp' and obj.get('uid') in new_pods:
            found.append(event)
        if direction == 'down' and event.get('reason') == 'ScaleDown' and obj.get('kind') == 'Node' and obj.get('uid') in old_nodes:
            found.append(event)
    return found


def stage(client, path, target, name, request, before=None, direction=None, started=None):
    timeout = int(os.environ['CLUSTER_AUTOSCALER_STAGE_TIMEOUT_SECONDS'])
    stable = int(os.environ['CLUSTER_AUTOSCALER_STABLE_SECONDS'])
    if timeout <= stable or stable <= 0:
        raise ValueError('stage timeout must exceed positive stabilization window')
    client.deadline = time.monotonic() + timeout
    since = None
    pending = []
    decision = []
    index = 0
    started = started or now()
    save(path / 'started.json', {'time': started, 'target_workers': target, 'replicas': target if name else 0,
                                'request_millicpu': request, 'timeout_seconds': timeout, 'stable_seconds': stable})
    while time.monotonic() < client.deadline:
        if getattr(client, 'run_check', None):
            client.run_check()
        poll = path / f'{index:04d}'
        s = client.snapshot(poll / 'snapshot.json')
        evidence, errors = decision_evidence(client, poll, started)
        state, reasons = evaluate(s, target, os.environ)
        if not s.get('errors'):
            if direction == 'up':
                pending += pending_cpu(s, name, evidence.get('workload-events', ''),
                                       {p['metadata']['uid'] for p in items(before, 'pods')})
            if direction:
                decision += ca_decisions(evidence.get('workload-events', ''), direction, before, s, name, started)
            if evidence.get('ca-deployment'):
                ca = json.loads(evidence['ca-deployment'])
                if ca['spec'].get('replicas') != 1 or ca.get('status', {}).get('availableReplicas') != 1:
                    raise RuntimeError('CA must remain single-replica Available throughout automatic test')
            if before:
                previous_count = before['md']['spec']['replicas']
                desired = s['md']['spec']['replicas']
                if not min(previous_count, target) <= desired <= max(previous_count, target):
                    raise RuntimeError(f'CA skipped requested transition: desired={desired} target={target}')
        if name and not s.get('errors') and not pod_contract(s, name, request, target):
            reasons.append('test Pod count/requests/Ready/termination/placement not converged')
        if direction == 'up' and not pending:
            reasons.append('awaiting current-stage Pending Insufficient cpu evidence')
        if direction and not decision:
            reasons.append('awaiting current-stage CA decision event')
        if errors:
            reasons.append('evidence query unavailable: ' + ','.join(errors))
        save(poll / 'result.json', {'time': now(), 'state': state, 'reasons': reasons})
        print(f'workers={target} {state}: {"; ".join(reasons)}', flush=True)
        if state == 'mismatch':
            raise RuntimeError('; '.join(reasons))
        passed = state == 'ready' and not errors and (not name or pod_contract(s, name, request, target))
        if direction:
            passed = passed and bool(decision) and (direction != 'up' or bool(pending))
        if passed and before:
            try:
                removed = verify_transition(before, s, direction, decision)
            except RuntimeError as exc:
                passed = False
                save(poll / 'deletion-pending.txt', str(exc))
        if passed:
            since = since or time.monotonic()
            if time.monotonic() - since >= stable:
                save(path / 'passed.json', {'time': now(), 'identities': identities(s), 'pending_cpu': sorted(set(pending)),
                                          'ca_decisions': list({e['metadata']['uid']: e for e in decision}.values()), 'removed': removed if before else []})
                client.deadline = None
                return s
        else:
            since = None
        index += 1
        time.sleep(min(10, max(0, client.deadline-time.monotonic())))
    client.deadline = None
    save(path / 'timeout.json', {'time': now(), 'state': 'timeout', 'last_state': state, 'last_reasons': reasons,
                               'pending_cpu': pending, 'ca_decisions': decision,
                               'note': 'Inspect PDB, Pod constraints, events, CA log, Machine deletion conditions and Nova capacity; no forced deletion.'})
    raise TimeoutError('automatic transition timed out; evidence=' + str(path))


def run(client, path, owner_id=None):
    if residues(client):
        raise RuntimeError('previous owned test resources exist; inspect evidence then run make cluster-autoscaler-test-cleanup')
    before = stage(client, path / '00-baseline', 1, None, 0)
    probe_args = {'owner_id': owner_id} if owner_id else {}
    probe(client, path / '00-probes', uuid.uuid4().hex[:12], **probe_args)
    request, selection = choose_request(before)
    save(path / 'cpu-selection.json', selection)
    run_id = owner_id or uuid.uuid4().hex[:12]
    name = 'ca-cycle-' + run_id
    ns = os.environ['CLUSTER_AUTOSCALER_TEST_NAMESPACE']
    save(path / 'ownership.json', {'run': run_id, 'deployment': name, 'namespace': ns})
    owned = None
    for index, target in enumerate((2, 3, 2, 1, 2, 1), start=1):
        stage_path = path / f'{index:02d}-workers-{target}'
        direction = 'up' if target > before['md']['spec']['replicas'] else 'down'
        transition_started = now()
        if owned is None:
            spec = deployment(name, ns, client.cluster, run_id, request, target)
            save(stage_path / 'requested-deployment.json', spec)
            owned = json.loads(client.k('w', 'create', '-f', '-', '-o', 'json', data=json.dumps(spec)))
            save(path / 'created-deployment.json', owned)
        else:
            # Mutate only the run-owned workload Deployment; never MachineDeployment/CA replicas.
            current = client.get('w', 'deployment', name, '-n', ns)
            if current['metadata']['uid'] != owned['metadata']['uid']:
                raise RuntimeError('test Deployment UID changed')
            patch = [{'op': 'test', 'path': '/metadata/uid', 'value': owned['metadata']['uid']},
                     {'op': 'replace', 'path': '/spec/replicas', 'value': target}]
            save(stage_path / 'replica-change.json', {'time': now(), 'patch': patch, 'cpu_requests_unchanged': request})
            client.k('w', 'patch', 'deployment', name, '-n', ns, '--type=json', '-p', json.dumps(patch))
        after = stage(client, stage_path, target, name, request, before, direction, started=transition_started)
        probe(client, stage_path / 'probes', uuid.uuid4().hex[:12], **probe_args)
        for row in identities(after):
            if row['machine_uid'] not in {r['machine_uid'] for r in identities(before)}:
                check_dir = stage_path / row['node']
                check_dir.mkdir(parents=True, mode=0o700)
                save(check_dir / 'ipam-check.log', command([ROOT / 'scripts/cluster-autoscaler.sh', 'ipam-check', row['node'], check_dir], timeout=180))
        before = after
    delete_owned(client, 'w', owned)
    client.k('w', 'wait', '--for=delete', 'deployment/' + name, '-n', ns, '--timeout=20s')
    if residues(client):
        raise RuntimeError('owned test Pods remain after final cleanup')
    final = stage(client, path / '07-final-clean', 1, None, 0, before)
    probe(client, path / '07-final-probes', uuid.uuid4().hex[:12], **probe_args)
    save(path / 'result.json', {'state': 'passed', 'time': now(), 'sequence': [1, 2, 3, 2, 1, 2, 1],
                              'identities': identities(final), 'http_continuity': 'not tested'})


def run_manual(target, control):
    import signal
    journal = control.read(control.journal_path)
    environment = {**os.environ, 'WORKER_CONTROL_LOCK_FD': str(control.lock.fileno()),
                   'WORKER_CONTROL_EXPECTED_FROM': str(journal['from'])}
    with subprocess.Popen([ROOT / 'scripts/workload-cluster.sh', 'scale-unlocked', target],
                          start_new_session=True, pass_fds=(control.lock.fileno(),), env=environment) as proc:
        try:
            status = proc.wait()
        except BaseException:
            # Give the shell EXIT trap time to restore CA before bounding termination.
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=330)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            raise
        if status:
            raise RuntimeError(f'manual scaling failed ({status}); inspect CA restoration artifacts')


def prepare_transport(action):
    # The management/workload API tunnels must exist before WorkerControl's
    # first read; the shell wrappers otherwise establish them too late.
    subprocess.run([ROOT / 'scripts/gcp-management-cluster.sh', 'tunnel'],
                   check=True, timeout=180)
    if action in ('install', 'manual', 'test', 'cleanup', 'mode', 'probe', 'test-resume', 'test-reconcile'):
        subprocess.run([ROOT / 'scripts/gcp-workload-api-tunnel.sh', 'ensure'],
                       check=True, timeout=180)


def main():
    from run_lifecycle import RunLifecycle, install_signal_handlers, local_action
    install_signal_handlers()
    client = Client()
    action = sys.argv[1] if len(sys.argv) > 1 else 'test'
    if action in ('test-status', 'test-cancel'):
        local_action(client, action, os.environ.get('RUN_ID', ''))
        return
    with WorkerControl(client) as control:
        lifecycle = RunLifecycle(client, control)
        if action in ('test', 'manual', 'mode', 'install', 'create', 'destroy', 'probe'):
            lifecycle.require_idle()
        try:
            prepare_transport(action)
        except BaseException as exc:
            if action == 'cleanup' and lifecycle.active():
                failure = {'state': 'cleanup_failed', 'phase': 'transport', 'time': now(), 'reason': str(exc)}
                lifecycle.update('cleanup_failed', reason=str(exc))
                save(lifecycle.path / ('cleanup-transport-' + uuid.uuid4().hex[:8] + '.json'), failure)
                save(lifecycle.path / 'result.json', failure)
            raise
        if action in ('test', 'test-resume', 'test-reconcile') or (
                action == 'cleanup' and (lifecycle.active() or os.environ.get('RUN_ID'))):
            lifecycle.execute(action)
            return
        if action in ('create', 'destroy', 'probe'):
            control.recover()
            if action == 'create' and control.read(control.state_path):
                current = client.k('m', 'get', 'cluster', client.cluster, '-n', client.ns,
                                   '--ignore-not-found', '-o', 'json')
                current_object = json.loads(current) if current.strip() else None
                if current_object:
                    raise RuntimeError('worker control state exists; create cannot safely reapply the bootstrap worker count')
                control.state_path.unlink()
            environment = {**os.environ, 'WORKER_CONTROL_LOCK_FD': str(control.lock.fileno())}
            if action == 'probe':
                argv = [sys.executable, ROOT / 'scripts/test_resources.py', 'probe']
            else:
                argv = [ROOT / 'scripts/workload-cluster.sh', action + '-unlocked', *sys.argv[2:]]
            with subprocess.Popen(argv, pass_fds=(control.lock.fileno(),), env=environment) as proc:
                if proc.wait():
                    raise RuntimeError(action + ' operation failed')
            if action == 'destroy':
                control.state_path.unlink(missing_ok=True)
            return
        if action == 'status':
            observed = control.observe()
            print(json.dumps({'record': control.read(control.state_path),
                              'operation': control.read(control.journal_path),
                              'actual': {'identity': control.identity(observed), 'workers': observed['workers'],
                                         'worker_stable': control.stable_workers(observed),
                                         'ca_replicas': observed['ca_replicas'],
                                         'ca_available': observed['ca'].get('status', {}).get('availableReplicas', 0)}}, indent=2))
            return
        if action == 'recover':
            control.recover()
            print('worker control recovery complete')
            return
        if action == 'mode':
            if len(sys.argv) != 3:
                raise ValueError('usage: autoscaler_cycle.py mode {auto|fixed}')
            control.switch_mode(sys.argv[2])
            print('worker mode=' + sys.argv[2])
            return
        if action == 'install':
            existing = client.k('m', 'get', 'deployment', 'cluster-autoscaler', '-n',
                                os.environ['CLUSTER_AUTOSCALER_NAMESPACE'], '--ignore-not-found', '-o', 'json')
            existing_object = json.loads(existing) if existing.strip() else None
            control.preflight_install(bool(existing_object and existing_object.get('kind') == 'Deployment'))
            environment = {**os.environ, 'WORKER_CONTROL_LOCK_FD': str(control.lock.fileno())}
            with subprocess.Popen([ROOT / 'scripts/cluster-autoscaler.sh', 'install-unlocked'],
                                  pass_fds=(control.lock.fileno(),), env=environment) as proc:
                if proc.wait():
                    raise RuntimeError('Cluster Autoscaler installation failed')
            observed = control.observe()
            control.require_mode_state('auto', observed)
            control.record_mode('auto', observed)
            return
        path = artifact_dir('autoscaler-cycle')
        print('evidence=' + str(path), flush=True)
        try:
            if action == 'manual':
                if len(sys.argv) != 3 or sys.argv[2] not in ('1', '2', '3'):
                    raise ValueError('manual worker target must be 1, 2 or 3')
                control.begin_manual(sys.argv[2])
                run_manual(sys.argv[2], control)
                control.finish_manual()
            elif action == 'cleanup':
                control.preflight()
                client.deadline = time.monotonic() + 300
                cleanup(client, path)
            elif action == 'test':
                control.preflight('auto')
                with subprocess.Popen([ROOT / 'scripts/cluster-autoscaler.sh', 'verify'],
                                      pass_fds=(control.lock.fileno(),)) as proc:
                    if proc.wait():
                        raise RuntimeError('Cluster Autoscaler verification failed before automatic test')
                run(client, path)
            else:
                raise ValueError('unknown worker operation: ' + action)
        except BaseException as exc:
            client.deadline = None
            save(path / 'result.json', {'state': 'failed', 'time': now(), 'reason': str(exc), 'cleanup': 'not attempted; owned test resources preserved'})
            # Existing collectors preserve guest/Nova/compute details; bound the whole collector.
            try:
                save(path / 'diagnostics.log', command([ROOT / 'scripts/cluster-autoscaler-diagnostics.sh', 'cycle-failed'], timeout=180))
            except BaseException as diagnostic_error:
                save(path / 'diagnostics-error.txt', str(diagnostic_error))
            raise
        finally:
            # Keep the run/time/Machine/Node/Nova relation even on a failed stage.
            if action == 'test':
                try:
                    command([sys.executable, ROOT / 'observability/build-run-manifest.py', path], timeout=30)
                except BaseException as manifest_error:
                    print('WARN: observability manifest unavailable: ' + str(manifest_error), file=sys.stderr)


if __name__ == '__main__':
    main()
