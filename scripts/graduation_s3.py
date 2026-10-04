#!/usr/bin/env python3
"""Fence a control-disconnected worker before recovering PostgreSQL on its Cinder volume."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import secrets
import shlex
import time

from graduation_env import utc_now
from graduation_recovery import RecoveryLab, wait_for
from graduation_s1 import LABEL
from workload_state import condition

SKIP = 'cluster.x-k8s.io/skip-remediation'
OUT = 'node.kubernetes.io/out-of-service'
FLAG = '--disable-force-detach-on-timeout=true'


def require_fenced(server, expected_id, hypervisor_state):
    if server.get('id') != expected_id or server.get('status') != 'SHUTOFF' or\
            server.get('OS-EXT-STS:task_state') is not None or\
            server.get('OS-EXT-STS:power_state') != 4 or hypervisor_state.strip() != 'shut off':
        raise RuntimeError('fencing is unconfirmed; no Pod deletion or volume detach is permitted')


def volume_matches(pvc, pv, volume, uid, source=None):
    if pvc['metadata']['uid'] != uid or pvc['spec']['volumeName'] != pv['metadata']['name'] or\
            pv['spec']['claimRef']['uid'] != uid or pv['spec']['csi']['driver'] != 'cinder.csi.openstack.org' or\
            pv['spec']['csi']['volumeHandle'] != volume['id']:
        raise RuntimeError('PVC/PV/Cinder identity mismatch')
    if source and (len(volume['attachments']) != 1 or volume['attachments'][0]['server_id'] != source):
        raise RuntimeError('unexpected Cinder attachment')


class S3(RecoveryLab):
    def __init__(self):
        super().__init__('s3')

    def guest(self, binding, script, timeout=120):
        router = self.record['router_id']
        key = '/home/' + __import__('os').environ['TARGET_SSH_USER'] + '/.ssh/openstack_k8s'
        known_hosts = '/var/lib/openstack-k8s-graduation/' + self.record['run_id'] + '/known_hosts'
        args = ['sudo', 'ip', 'netns', 'exec', 'qrouter-' + router, 'ssh', '-i', key,
                '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=10',
                '-o', 'UserKnownHostsFile=' + known_hosts,
                'ubuntu@' + binding['ip'], 'sudo bash -s']
        return self.remote('sudo install -d -m 700 ' + shlex.quote(str(Path(known_hosts).parent)) +
                           ' && ' + shlex.join(args), data=script, timeout=timeout)

    def controller_policy(self):
        cp = self.record['control_plane']
        path = '/etc/kubernetes/manifests/kube-controller-manager.yaml'
        original = self.guest(cp, 'cat ' + path)
        if '--disable-force-detach-on-timeout' in original and FLAG not in original:
            raise RuntimeError('conflicting controller-manager force detach policy')
        configured = original if FLAG in original else original.replace('    - kube-controller-manager\n', '    - kube-controller-manager\n    - ' + FLAG + '\n')
        if FLAG not in configured:
            raise RuntimeError('controller-manager manifest format not recognized')
        self.save('controller-manager-before.yaml', original)
        self.write('controller-policy-intent', controller_original_sha256=hashlib.sha256(original.encode()).hexdigest(),
                   controller_configured_sha256=hashlib.sha256(configured.encode()).hexdigest())
        self.guest(cp, "python3 - <<'PYCODE'\nimport base64,os\nfrom pathlib import Path\np=Path('" + path + "')\ntmp=Path('/etc/kubernetes/s3-controller-manager.tmp')\ntmp.write_bytes(base64.b64decode('" + base64.b64encode(configured.encode()).decode() + "'))\nos.replace(tmp,p)\nPYCODE\n")
        def active():
            pods = self.client.get('w', 'pods', '-n', 'kube-system', '-l', 'component=kube-controller-manager')['items']
            return len(pods) == 1 and condition(pods[0], 'Ready') and FLAG in pods[0]['spec']['containers'][0]['command']
        wait_for(active, seconds=180)
        self.write('controller-policy-ready')

    def sql(self, sql, timeout=30):
        return self.k('-n', self.ns, 'exec', 'probe', '--', 'psql', '-X', '-A', '-t', '-v', 'ON_ERROR_STOP=1',
                      '-h', 'db', '-U', 'postgres', '-d', 'postgres', '-c', sql, timeout=timeout).strip()

    def dbpod(self):
        return self.obj('pod', 'db-0')

    def build_database(self, workers, cp):
        password = secrets.token_urlsafe(32)
        self.apply({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'db-auth', 'namespace': self.ns},
                    'stringData': {'password': password}})
        env = [{'name': 'PGPASSWORD', 'valueFrom': {'secretKeyRef': {'name': 'db-auth', 'key': 'password'}}}]
        self.apply({'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': 'db', 'namespace': self.ns},
                    'spec': {'selector': {'app': 'db'}, 'ports': [{'port': 5432}]}})
        spec = {'serviceName': 'db', 'replicas': 1, 'selector': {'matchLabels': {'app': 'db'}},
                'template': {'metadata': {'labels': {'app': 'db'}}, 'spec': {
                    'terminationGracePeriodSeconds': 30,
                    'affinity': {'nodeAffinity': {
                        'requiredDuringSchedulingIgnoredDuringExecution': {'nodeSelectorTerms': [{'matchExpressions': [
                            {'key': 'node-role.kubernetes.io/control-plane', 'operator': 'DoesNotExist'}]}]},
                        'preferredDuringSchedulingIgnoredDuringExecution': [{'weight': 100, 'preference': {
                            'matchExpressions': [{'key': 'kubernetes.io/hostname', 'operator': 'In', 'values': [workers[0]['node']]}]}}]}},
                    'tolerations': [{'key': key, 'operator': 'Exists', 'effect': 'NoExecute', 'tolerationSeconds': 3600}
                                    for key in ('node.kubernetes.io/not-ready', 'node.kubernetes.io/unreachable')],
                    'containers': [{'name': 'db', 'image': 'postgres:16.10-alpine',
                        'env': [{'name': 'POSTGRES_PASSWORD', 'valueFrom': {'secretKeyRef': {'name': 'db-auth', 'key': 'password'}}},
                                {'name': 'PGDATA', 'value': '/var/lib/postgresql/data/pgdata'}],
                        'resources': {'requests': {'cpu': '100m', 'memory': '128Mi'}, 'limits': {'memory': '512Mi'}},
                        'readinessProbe': {'exec': {'command': ['pg_isready', '-U', 'postgres']}, 'periodSeconds': 3},
                        'volumeMounts': [{'name': 'data', 'mountPath': '/var/lib/postgresql/data'}]}]}},
                'volumeClaimTemplates': [{'metadata': {'name': 'data'}, 'spec': {
                    'accessModes': ['ReadWriteOnce'], 'storageClassName': 'graduation-cinder',
                    'resources': {'requests': {'storage': '1Gi'}}}}]}
        self.apply({'apiVersion': 'apps/v1', 'kind': 'StatefulSet', 'metadata': {'name': 'db', 'namespace': self.ns}, 'spec': spec})
        self.apply({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'probe', 'namespace': self.ns},
                    'spec': {'nodeName': cp['node'], 'tolerations': [{'key': 'node-role.kubernetes.io/control-plane',
                        'operator': 'Exists', 'effect': 'NoSchedule'}],
                        'containers': [{'name': 'probe', 'image': 'postgres:16.10-alpine', 'env': env,
                            'command': ['sleep', '7200'], 'resources': {'requests': {'cpu': '25m', 'memory': '32Mi'}}}]}})
        wait_for(lambda: condition(self.dbpod() or {}, 'Ready'), seconds=600)
        wait_for(lambda: condition(self.obj('pod', 'probe') or {}, 'Ready'), seconds=300)
        self.save('statefulset.json', self.obj('statefulset', 'db'))
        pod = self.dbpod()
        source = next(w for w in workers if w['node'] == pod['spec']['nodeName'])
        target = next(w for w in workers if w != source)
        pvc = self.obj('pvc', 'data-db-0')
        pv = self.obj('pv', pvc['spec']['volumeName'], False)
        volume = self.admin_json('volume', 'show', pv['spec']['csi']['volumeHandle'])
        volume_matches(pvc, pv, volume, pvc['metadata']['uid'], source['nova_id'])
        self.save('volume-before.json', volume)
        self.write('database-ready', source=source, target=target, pod_before=pod,
                   pvc_uid=pvc['metadata']['uid'], pv_name=pv['metadata']['name'], volume_id=volume['id'])

    def sample(self, name, seconds=30):
        # The client stays on the unaffected control-plane VM; every attempt is retained.
        raw = self.k('-n', self.ns, 'exec', 'probe', '--', 'sh', '-c',
            'i=0; while [ "$i" -lt ' + str(seconds) + ' ]; do '
            'stamp=$(date -u +%Y-%m-%dT%H:%M:%SZ); '
            'PGCONNECT_TIMEOUT=2 psql -X -At -h db -U postgres -d postgres -c "select count(*) from evidence" >/dev/null 2>&1; '
            'rc=$?; printf "%s %s\\n" "$stamp" "$rc"; i=$((i+1)); sleep 1; done', timeout=seconds * 4 + 30)
        rows = [{'time': line.split()[0], 'ok': line.split()[1] == '0'} for line in raw.splitlines()]
        self.save(name + '.json', rows)
        return rows

    def fence(self):
        source = self.record['source']
        self.write('fence-intent', fence_requested_at=utc_now())
        self.admin('server', 'stop', source['nova_id'])
        def stopped():
            server = self.admin_json('server', 'show', source['nova_id'])
            if server.get('OS-EXT-SRV-ATTR:host') != source['host']:
                raise RuntimeError('source VM moved to another hypervisor during fencing')
            if server.get('status') != 'SHUTOFF' or server.get('OS-EXT-STS:task_state') is not None:
                return False
            hypervisor = self.remote('sudo docker exec nova_libvirt virsh domstate ' + shlex.quote(source['instance_name']), host=source['host'])
            require_fenced(server, source['nova_id'], hypervisor)
            self.save('fence.json', {'time': utc_now(), 'server': server, 'hypervisor_state': hypervisor.strip()})
            return True
        wait_for(stopped, seconds=180)
        self.write('fenced', fenced_at=utc_now())

    def mark_out_of_service(self):
        source = self.record['source']
        # Re-read fencing immediately before the first destructive recovery action.
        server = self.admin_json('server', 'show', source['nova_id'])
        if server.get('OS-EXT-SRV-ATTR:host') != source['host']:
            raise RuntimeError('source VM hypervisor mapping changed')
        hypervisor = self.remote('sudo docker exec nova_libvirt virsh domstate ' + shlex.quote(source['instance_name']), host=source['host'])
        require_fenced(server, source['nova_id'], hypervisor)
        node = self.obj('node', source['node'], False)
        if node['metadata']['uid'] != source['node_uid']:
            raise RuntimeError('source Node identity changed')
        taints = node['spec'].get('taints', [])
        if any(t['key'] == OUT for t in taints):
            raise RuntimeError('out-of-service taint is owned by another actor')
        patch = [{'op': 'test', 'path': '/metadata/uid', 'value': source['node_uid']},
                 {'op': 'test', 'path': '/metadata/resourceVersion', 'value': node['metadata']['resourceVersion']},
                 {'op': 'add', 'path': '/spec/taints', 'value': taints + [{'key': OUT, 'value': self.record['run_id'], 'effect': 'NoExecute'}]}]
        self.write('out-of-service-intent', out_of_service_at=utc_now())
        self.k('patch', 'node', source['node'], '--type=json', '-p', json.dumps(patch))

    def activate_recovery(self):
        self.mark_out_of_service()
        timeline = []
        def recovered():
            pod = self.dbpod()
            attachments = self.client.get('w', 'volumeattachments')['items']
            relevant = [v for v in attachments if v['spec']['source'].get('persistentVolumeName') == self.record['pv_name']]
            timeline.append({'time': utc_now(), 'pod': pod, 'attachments': relevant})
            self.save('recovery-timeline.json', timeline)
            return pod and pod['metadata']['uid'] != self.record['pod_before']['metadata']['uid'] and\
                pod['spec'].get('nodeName') == self.record['target']['node'] and condition(pod, 'Ready')
        wait_for(recovered, seconds=600, interval=5)
        self.write('database-recovered', pod_after=self.dbpod(), recovered_at=utc_now())

    def run(self):
        workers = self.start()
        try:
            nodes = self.client.get('w', 'nodes')['items']
            cpnode = next(n for n in nodes if 'node-role.kubernetes.io/control-plane' in n['metadata'].get('labels', {}))
            cp = self.binding(cpnode)
            interfaces = self.admin_json('port', 'list', '--network', workers[0]['port']['network_id'], '--device-owner', 'network:router_interface')
            if len(interfaces) != 1:
                raise RuntimeError('one tenant router required for independent SSH access')
            router_port = self.admin_json('port', 'show', interfaces[0]['ID'])
            self.write('management-path-ready', router_id=router_port['device_id'], control_plane=cp)
            self.controller_policy()
            self.build_database(workers, cp)
            source = self.record['source']
            machine = self.obj('machine', source['machine'], plane='m')
            if SKIP in machine['metadata'].get('annotations', {}) or machine['metadata'].get('deletionTimestamp'):
                raise RuntimeError('source Machine already controlled by another recovery')
            self.write('ownership-intent')
            self.k('-n', self.client.ns, 'annotate', 'machine', source['machine'], SKIP + '=' + self.record['run_id'], plane='m')
            seed = self.record['run_id']
            self.sql("create table evidence(id integer primary key, value text not null); insert into evidence select i, md5(i::text || '" + seed + "') from generate_series(1,1000) i;")
            rows_query = 'select json_agg(t order by t.id) from (select id,value from evidence where id<=1000) t'
            committed_rows = json.loads(self.sql(rows_query))
            expected_rows = [{'id': i, 'value': hashlib.md5((str(i) + seed).encode()).hexdigest()}
                             for i in range(1, 1001)]
            if committed_rows != expected_rows:
                raise RuntimeError('committed baseline records differ from the seed')
            self.save('committed-records-before.json', committed_rows)
            query = "select count(*)::text || ':' || md5(string_agg(id::text || ':' || value, ',' order by id)) from evidence where id<=1000"
            digest = self.sql(query)
            durability = self.sql("select current_setting('fsync') || ':' || current_setting('synchronous_commit') || ':' || current_setting('full_page_writes') || ':' || current_setting('data_directory')")
            if not durability.startswith('on:on:on:/var/lib/postgresql/data/pgdata'):
                raise RuntimeError('DB durability settings differ from the experiment contract')
            baseline = self.sample('baseline')
            if len(baseline) != 30 or not all(r['ok'] for r in baseline):
                raise RuntimeError('invalid DB baseline')
            self.write('baseline-ready', committed_digest=digest, durability=durability)
            # Scoped transient rules: old PostgreSQL remains running, its client path and
            # kubelet API traffic fail. Rules disappear on VM restart and have owned chains.
            self.write('fault-intent', fault_at=utc_now())
            fault = '''set -Eeuo pipefail
! iptables -S OSK8S_S3_OUT >/dev/null 2>&1
! iptables -S OSK8S_S3_DB >/dev/null 2>&1
test ! -e /run/osk8s-s3-owner
echo RUN_ID >/run/osk8s-s3-owner
iptables -N OSK8S_S3_OUT
iptables -A OSK8S_S3_OUT -p tcp --dport 6443 -j DROP
iptables -I OUTPUT -j OSK8S_S3_OUT
iptables -N OSK8S_S3_DB
iptables -A OSK8S_S3_DB -p tcp --dport 5432 -j DROP
iptables -I FORWARD -j OSK8S_S3_DB
crictl ps --name db -o json
'''.replace('RUN_ID', shlex.quote(self.record['run_id']))
            process = self.guest(source, fault)
            running = json.loads(process)
            self.save('old-db-running-after-fault.json', running)
            old_pod = self.record['pod_before']
            expected_container = old_pod['status']['containerStatuses'][0]['containerID'].split('://', 1)[-1]
            matching = [c for c in running.get('containers', []) if
                        c.get('id') == expected_container and
                        c.get('labels', {}).get('io.kubernetes.pod.uid') == old_pod['metadata']['uid'] and
                        c.get('state') == 'CONTAINER_RUNNING']
            if len(matching) != 1:
                raise RuntimeError('old DB process was not running after fault')
            wait_for(lambda: not condition(self.obj('node', source['node'], False), 'Ready'), seconds=180)
            impact = self.sample('fault-impact', seconds=15)
            if len(impact) != 15 or any(r['ok'] for r in impact):
                raise RuntimeError('sustained DB client impact not established')
            self.write('diagnosed', node_not_ready_at=utc_now())
            # Capture a real ACTIVE response and show that the fencing guard refuses it.
            active = self.admin_json('server', 'show', source['nova_id'])
            try:
                require_fenced(active, source['nova_id'], 'running')
            except RuntimeError:
                self.save('fence-negative-check.json', {'status': active['status'], 'rejected': True,
                                                       'pod_unchanged': self.dbpod()['metadata']['uid'] == self.record['pod_before']['metadata']['uid']})
            else:
                raise RuntimeError('fencing guard accepted a running VM')
            self.fence()
            self.activate_recovery()
            pvc = self.obj('pvc', 'data-db-0')
            pv = self.obj('pv', self.record['pv_name'], False)
            volume = self.admin_json('volume', 'show', self.record['volume_id'])
            volume_matches(pvc, pv, volume, self.record['pvc_uid'], self.record['target']['nova_id'])
            self.save('volume-after.json', volume)
            after = self.sql(query)
            recovered_rows = json.loads(self.sql(rows_query))
            self.save('committed-records-after.json', recovered_rows)
            self.sql("begin; insert into evidence values (1001, 'after-recovery'); commit;")
            new = self.sql('select value from evidence where id=1001')
            self.save('new-transaction.json', {'time': utc_now(), 'id': 1001, 'value': new,
                                             'operation': 'COMMIT completed, followed by a separate SELECT'})
            stable = self.sample('stabilization', seconds=60)
            source_final = self.admin_json('server', 'show', source['nova_id'])
            hypervisor = self.remote('sudo docker exec nova_libvirt virsh domstate ' + shlex.quote(source['instance_name']), host=source['host'])
            require_fenced(source_final, source['nova_id'], hypervisor)
            checks = {'committed_data_preserved': after == digest, 'new_transaction_readable': new == 'after-recovery',
                      'every_committed_record_preserved': recovered_rows == committed_rows,
                      'database_image_unchanged': self.dbpod()['status']['containerStatuses'][0]['imageID'] ==
                          self.record['pod_before']['status']['containerStatuses'][0]['imageID'],
                      'same_volume': volume['id'] == self.record['volume_id'],
                      'stable_service': len(stable) == 60 and all(r['ok'] for r in stable),
                      'old_vm_fenced': True, 'different_worker': self.dbpod()['spec']['nodeName'] == self.record['target']['node']}
            summary = {'passed': all(checks.values()), 'checks': checks, 'committed_before': digest, 'committed_after': after,
                       'volume_id': volume['id'], 'source': source['nova_id'], 'target': self.record['target']['nova_id'],
                       'fault_at': self.record['fault_at'], 'fenced_at': self.record['fenced_at'], 'recovered_at': self.record['recovered_at'],
                       'in_flight_transactions': 'not injected; only acknowledged commits are claimed preserved'}
            self.save('summary.json', summary)
            self.write('completed' if summary['passed'] else 'needs_review', result=summary)
            return summary
        except Exception as exc:
            self.write('failed', error=f'{type(exc).__name__}: {exc}')
            raise

    def clear_fault(self, source):
        clear = """set -Eeuo pipefail
if test -f /run/osk8s-s3-owner; then
  test "$(cat /run/osk8s-s3-owner)" = RUN_ID
else
  ! iptables -S OSK8S_S3_OUT >/dev/null 2>&1
  ! iptables -S OSK8S_S3_DB >/dev/null 2>&1
  exit 0
fi
for pair in 'OUTPUT OSK8S_S3_OUT' 'FORWARD OSK8S_S3_DB'; do
  read -r parent chain <<<"$pair"
  if iptables -S "$chain" >/dev/null 2>&1; then
    if iptables -C "$parent" -j "$chain" >/dev/null 2>&1; then iptables -D "$parent" -j "$chain"; fi
    iptables -F "$chain"
    iptables -X "$chain"
  fi
done
rm /run/osk8s-s3-owner
""".replace('RUN_ID', shlex.quote(self.record['run_id']))
        self.guest(source, clear, timeout=30)

    def cleanup(self):
        self.acquire()
        if not self.record or self.record['phase'] == 'cleaned':
            return self.record
        self.ownership()
        r = self.record
        source = r.get('source')
        # If fencing never happened, restore communications so the original DB
        # can terminate gracefully. Never unblock/restart a fenced VM with a live PVC.
        if source:
            server = self.admin_json('server', 'show', source['nova_id'])
            if server['status'] == 'ACTIVE':
                if r.get('fenced_at') and not r.get('source_restore_started'):
                    raise RuntimeError('fenced VM restarted externally; inspect attachments before cleanup')
                self.clear_fault(source)
                wait_for(lambda: condition(self.obj('node', source['node'], False), 'Ready'), seconds=180)
            elif server['status'] == 'SHUTOFF':
                node = self.obj('node', source['node'], False)
                existing = [t for t in node['spec'].get('taints', []) if t['key'] == OUT]
                if not existing:
                    self.mark_out_of_service()
                elif any(t.get('value') != r['run_id'] for t in existing):
                    raise RuntimeError('out-of-service taint ownership changed')
        self.delete_namespace()
        if r.get('volume_id'):
            wait_for(lambda: not any(v['ID'] == r['volume_id'] for v in self.admin_json('volume', 'list', '--all-projects')), seconds=300)
        if source:
            server = self.admin_json('server', 'show', source['nova_id'])
            if server['status'] == 'SHUTOFF':
                self.k('cordon', source['node'])
                self.write('source-restore-intent', source_restore_started=True)
                self.admin('server', 'start', source['nova_id'])
                wait_for(lambda: self.admin_json('server', 'show', source['nova_id'])['status'] == 'ACTIVE', seconds=180)
            def clear():
                try:
                    self.clear_fault(source)
                    return True
                except RuntimeError:
                    return False
            wait_for(clear, seconds=180)
            node = self.obj('node', source['node'], False)
            owned = [t for t in node['spec'].get('taints', []) if t['key'] == OUT]
            if owned and any(t.get('value') != r['run_id'] for t in owned):
                raise RuntimeError('out-of-service taint ownership changed')
            if owned:
                self.k('taint', 'node', source['node'], OUT + ':NoExecute-')
            wait_for(lambda: condition(self.obj('node', source['node'], False), 'Ready'), seconds=300)
            self.k('uncordon', source['node'])
            machine = self.obj('machine', source['machine'], plane='m')
            if machine and machine['metadata']['uid'] == source['machine_uid']:
                value = machine['metadata'].get('annotations', {}).get(SKIP)
                if value == r['run_id']:
                    self.k('-n', self.client.ns, 'annotate', 'machine', source['machine'], SKIP + '-', plane='m')
                elif value is not None:
                    raise RuntimeError('remediation annotation ownership changed')
        if r.get('controller_original_sha256'):
            cp = r['control_plane']
            path = '/etc/kubernetes/manifests/kube-controller-manager.yaml'
            current = self.guest(cp, 'cat ' + path)
            current_hash = hashlib.sha256(current.encode()).hexdigest()
            if current_hash not in (r['controller_original_sha256'], r['controller_configured_sha256']):
                raise RuntimeError('controller-manager configuration changed externally')
            original = (Path(r['evidence']) / 'controller-manager-before.yaml').read_bytes()
            code = "import os,base64; from pathlib import Path; p=Path(" + repr(path) + "); t=Path('/etc/kubernetes/s3-restore.tmp'); t.write_bytes(base64.b64decode(" + repr(base64.b64encode(original).decode()) + ")); os.replace(t,p)"
            self.guest(cp, 'python3 -c ' + shlex.quote(code))
            def restored_policy():
                pods = self.client.get('w', 'pods', '-n', 'kube-system', '-l', 'component=kube-controller-manager')['items']
                if len(pods) != 1 or not condition(pods[0], 'Ready'):
                    return False
                if (FLAG in pods[0]['spec']['containers'][0]['command']) != (FLAG.encode() in original):
                    return False
                return pods[0]
            self.save('controller-manager-restored.json', wait_for(restored_policy, seconds=180))
            restored_manifest = self.guest(cp, 'cat ' + path)
            if hashlib.sha256(restored_manifest.encode()).hexdigest() != r['controller_original_sha256']:
                raise RuntimeError('controller-manager manifest did not restore byte-for-byte')
            self.save('controller-manager-after.yaml', restored_manifest)
        self.restore_workers()
        self.write('cleaned')
        return r


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'cleanup', 'status'))
    args = parser.parse_args()
    runner = S3()
    result = runner.run() if args.action == 'run' else runner.cleanup() if args.action == 'cleanup' else runner.record
    print(json.dumps(result, indent=2))
    if args.action == "run" and not result["passed"]:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
