#!/usr/bin/env python3
"""Prepare two compute placements by live-migrating only a new, empty test worker."""
import fcntl
import json
from pathlib import Path

from graduation_env import atomic_json, utc_now
from graduation_recovery import RecoveryLab, wait_for
from graduation_s1_contention import epoch
from worker_control import WorkerControl
from workload_state import artifact_dir, condition


def eligible(binding, machine, pods, preparation):
    if machine['metadata']['uid'] != binding['machine_uid'] or machine['metadata'].get('deletionTimestamp'):
        return False
    if epoch(machine['metadata']['creationTimestamp']) < epoch(preparation['created']):
        return False
    return not any(p['spec'].get('nodeName') == binding['node'] and
                   p.get('status', {}).get('phase') not in ('Succeeded', 'Failed') and
                   not any(o['kind'] == 'DaemonSet' for o in p['metadata'].get('ownerReferences', []))
                   for p in pods)


def validate_server(server, binding):
    if server.get('id') != binding['nova_id'] or server.get('status') != 'ACTIVE' or\
            server.get('OS-EXT-STS:task_state') is not None or\
            server.get('OS-EXT-SRV-ATTR:host') != binding['host'] or\
            server.get('volumes_attached') != []:
        raise RuntimeError('worker identity/state changed or it has attached volumes')


def main():
    lab = RecoveryLab('s3')
    s1 = lab.s1
    with s1.lock_path.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preparation = s1.read()
        s1.verify()
        for name in ('s1-auto.json', 's1-contention.json'):
            path = lab.client.state / name
            if path.exists() and json.loads(path.read_text()).get('phase') != 'completed':
                raise RuntimeError('finish the active S1 experiment before changing preparation placement')
        with WorkerControl(lab.client) as control:
            mode, observed = control.preflight(expected_mode='fixed')
            if observed['md_uid'] != preparation['md_uid'] or observed['workers'] != 2 or\
                    not control.stable_workers(observed):
                raise RuntimeError('two stable fixture workers required')
            nodes = lab.client.get('w', 'nodes')['items']
            workers = [lab.binding(n) for n in nodes if
                       'node-role.kubernetes.io/control-plane' not in n['metadata'].get('labels', {})]
            cp = [lab.binding(n) for n in nodes if
                  'node-role.kubernetes.io/control-plane' in n['metadata'].get('labels', {})]
            if len(workers) != 2 or len(cp) != 1:
                raise RuntimeError('one control plane and two workers required')
            if len({w['host'] for w in workers}) == 2 and cp[0]['host'] in {w['host'] for w in workers}:
                print('S1 workers already span two computes; no placement change.')
                return
            if any(w['host'] != cp[0]['host'] for w in workers):
                raise RuntimeError('unexpected compute topology; inspect before changing placement')
            machines = lab.client.get('m', 'machines', '-n', lab.client.ns)['items']
            pods = lab.client.get('w', 'pods', '-A')['items']
            candidates = [w for w in workers if any(eligible(w, m, pods, preparation)
                          for m in machines if m['metadata']['name'] == w['machine'])]
            if len(candidates) != 1:
                raise RuntimeError('one newly created worker with only node agents is required')
            source = candidates[0]
            env = s1.environment()
            services = lab.admin_json('compute', 'service', 'list', '--service', 'nova-compute')
            hosts = [v['Host'] for v in services if v['Host'] != source['host'] and
                     v['Host'] in env['initial_hosts'] and v['Status'] == 'enabled' and v['State'] == 'up']
            if len(hosts) != 1:
                raise RuntimeError('one enabled alternate compute required')
            before = lab.admin_json('server', 'show', source['nova_id'])
            validate_server(before, source)
            evidence = artifact_dir('graduation-s1-placement')
            state = lab.client.state / 's1-placement.json'
            record = {'preparation_id': preparation['run_id'], 'environment_run_id': env['run_id'],
                      'created': utc_now(), 'source': source, 'target_host': hosts[0],
                      'server_before': before, 'evidence': str(evidence), 'phase': 'migration-intent'}
            def save(phase, **values):
                record.update(values, phase=phase, updated=utc_now())
                atomic_json(state, record)
                atomic_json(evidence / 'run.json', record)
            save('migration-intent')
            try:
                # This is fixture preparation, before the request Job and CPU fault.
                lab.admin('--os-compute-api-version', '2.30', 'server', 'migrate', '--live-migration',
                          '--host', hosts[0], '--block-migration', '--wait', source['nova_id'], timeout=900)
                def moved():
                    server = lab.admin_json('server', 'show', source['nova_id'])
                    node = lab.obj('node', source['node'], False)
                    if node['metadata']['uid'] != source['node_uid']:
                        raise RuntimeError('worker Node identity changed during migration')
                    if server['status'] == 'ACTIVE' and server.get('OS-EXT-STS:task_state') is None and\
                            server['OS-EXT-SRV-ATTR:host'] == hosts[0] and condition(node, 'Ready'):
                        return server
                    return False
                after = wait_for(moved, seconds=300)
                save('completed', server_after=after)
            except Exception as exc:
                save('failed', error=f'{type(exc).__name__}: {exc}')
                raise
        s1.verify()
        print('S1 worker placement prepared: ' + source['host'] + ' -> ' + hosts[0])


if __name__ == '__main__':
    main()
