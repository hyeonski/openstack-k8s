#!/usr/bin/env python3
"""S2 shared egress experiment and bounded Neutron QoS controller."""
import argparse
import json
from pathlib import Path
import shlex
import time

from graduation_env import utc_now
from graduation_recovery import RecoveryLab, wait_for
from graduation_s1 import LABEL, percentile, host_cpu_utilization
from workload_state import ROOT, condition

RATES = [6000, 10000, 14000, 18000]
BURST_KBITS = 250


def analyze(sample):
    rows = sample['rows']
    indexes = [r['index'] for r in rows]
    success = [r for r in rows if r['ok']]
    before, after = sample['qdisc_before'][0], sample['qdisc_after'][0]
    return {'requests': len(rows), 'failures': len(rows) - len(success),
            'complete': len(rows) == 120 and set(indexes) == set(range(120)) and len(set(indexes)) == 120,
            'p95_ms': percentile([r['latency_ms'] for r in success], .95),
            'upload_bytes': sample['progress_after']['bytes'] - sample['progress_before']['bytes'],
            'egress_bps': (after['bytes'] - before['bytes']) * 8 / sample['elapsed'],
            'overlimits': after['overlimits'] - before['overlimits'],
            'drops': after['drops'] - before['drops']}


def impacted(base, metric):
    return metric['complete'] and (metric['failures'] > 0 or
           (metric['p95_ms'] is not None and metric['p95_ms'] > base * 1.5))


def stable(base, metric):
    return metric['complete'] and metric['failures'] == 0 and metric['p95_ms'] is not None and metric['p95_ms'] <= base * 1.3 and metric['upload_bytes'] > 0


def next_rate(current, healthy):
    index = RATES.index(current)
    return RATES[min(len(RATES) - 1, index + 1)] if healthy else RATES[max(0, index - 1)]


class S2(RecoveryLab):
    def __init__(self):
        super().__init__('s2')

    def deployment(self, name, node, args):
        return {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {
            'name': name, 'namespace': self.ns, 'labels': {LABEL: self.record['run_id']}},
            'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'},
                     'selector': {'matchLabels': {'app': name}},
                     'template': {'metadata': {'labels': {'app': name}}, 'spec': {
                         'nodeSelector': {'kubernetes.io/hostname': node},
                         'containers': [{'name': name, 'image': 'python:3.12-alpine',
                             'command': ['python', '-B', '/app/workload.py', *args],
                             'resources': {'requests': {'cpu': '100m', 'memory': '64Mi'},
                                           'limits': {'memory': '256Mi'}},
                             'volumeMounts': [{'name': 'code', 'mountPath': '/app', 'readOnly': True}]}],
                         'volumes': [{'name': 'code', 'configMap': {'name': 'code'}}]}}}}

    def pods(self, app):
        return self.client.get('w', 'pods', '-n', self.ns, '-l', 'app=' + app)['items']

    def ready(self, app, node):
        pods = self.pods(app)
        return len(pods) == 1 and pods[0]['spec']['nodeName'] == node and condition(pods[0], 'Ready')

    def set_rate(self, rate):
        r = self.record
        node = self.obj('node', r['workers'][1]['node'], False)
        if node['metadata']['uid'] != r['workers'][1]['node_uid'] or not condition(node, 'Ready') or node['spec'].get('unschedulable'):
            raise RuntimeError('destination worker identity/readiness changed')
        port = self.admin_json('port', 'show', r['workers'][1]['port']['id'])
        if port['device_id'] != r['workers'][1]['nova_id'] or port.get('qos_policy_id') not in (None, '', r['policy_id']):
            raise RuntimeError('destination port ownership/policy changed')
        self.write('qos-change-intent', desired_rate_kbps=rate)
        self.admin('network', 'qos', 'rule', 'set', '--max-kbps', str(rate), '--max-burst-kbits', str(BURST_KBITS),
                   r['policy_id'], r['rule_id'])
        self.admin('port', 'set', '--qos-policy', r['policy_id'], port['id'])
        observed = self.admin_json('network', 'qos', 'rule', 'show', r['policy_id'], r['rule_id'])
        updated = self.admin_json('port', 'show', port['id'])
        if int(observed['max_kbps']) != rate or observed['direction'] != 'egress' or updated['qos_policy_id'] != r['policy_id']:
            raise RuntimeError('QoS API readback mismatch')
        # Inspect the enforcing OVS interface, not just the Neutron database.
        def installed():
            out = self.remote('sudo docker exec openvswitch_vswitchd ovs-vsctl --format=json '
                              '--columns=name,ingress_policing_rate,ingress_policing_burst find Interface '
                              + shlex.quote('external_ids:iface-id=' + port['id']), host=r['workers'][1]['host'])
            rows = json.loads(out)['data']
            if len(rows) != 1 or (int(rows[0][1]) != rate or int(rows[0][2]) != BURST_KBITS):
                return False
            return rows
        enforcement = wait_for(installed, seconds=120, interval=5)
        self.record.setdefault('policy_changes', []).append({'time': utc_now(), 'kbps': rate, 'burst_kbits': BURST_KBITS,
                                                           'port_id': port['id'], 'ovs': enforcement})
        self.write('qos-installed', current_rate_kbps=rate)

    def window(self, name):
        r = self.record
        hosts = sorted({w['host'] for w in r['workers']})
        before = {h: self.s1.host_stat(h) for h in hosts}
        # All samples share the external receiver network namespace and path.
        code = '''import json, subprocess, time, urllib.request
from pathlib import Path
def progress():
 return json.load(urllib.request.urlopen('http://198.18.0.2:8090/progress', timeout=10))
def qdisc():
 return json.loads(subprocess.check_output(['tc','-s','-j','qdisc','show','dev','s2-egress']))
before, qb, begin = progress(), qdisc(), time.monotonic()
raw = subprocess.check_output(['ip','netns','exec','osk8s-s2','python3','/opt/openstack-k8s/graduation-s2-workload.py','probe','--url',URL,'--seconds','60','--rate','2'], timeout=115).decode()
print(json.dumps(dict(rows=[json.loads(line) for line in raw.splitlines()], progress_before=before, progress_after=progress(), qdisc_before=qb, qdisc_after=qdisc(), elapsed=time.monotonic()-begin)))
'''.replace('URL', repr('http://' + r['fip']['floating_ip_address'] + ':30080'))
        sample = json.loads(self.remote('sudo python3 -', data=code, timeout=150))
        after = {h: self.s1.host_stat(h) for h in hosts}
        sample['host_before'], sample['host_after'] = before, after
        sample['cpu_utilization'] = {h: host_cpu_utilization(before[h], after[h]) for h in hosts}
        self.save(name + '.json', sample)
        result = analyze(sample)
        result['cpu_utilization'] = sample['cpu_utilization']
        self.record.setdefault('windows', {})[name] = result
        self.write('measured-' + name)
        return result

    def run(self):
        workers = self.start()
        try:
            a, b = workers
            # Only node agents/system components may share the controlled worker.
            other = [p['metadata']['name'] for p in self.client.get('w', 'pods', '-A')['items']
                     if p['spec'].get('nodeName') == b['node'] and p['metadata']['namespace'] != 'kube-system'
                     and p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')
                     and not any(o['kind'] == 'DaemonSet' for o in p['metadata'].get('ownerReferences', []))]
            if other or b['port'].get('qos_policy_id'):
                raise RuntimeError('destination port is shared or has a preexisting QoS policy')
            extensions = self.admin_json('extension', 'list', '--network')
            if not any(e.get('Alias') == 'qos' for e in extensions):
                raise RuntimeError('Neutron QoS is not enabled')
            run = self.record['run_id']
            # Remote files contain source only, never cloud credentials.
            self.remote('sudo tee /opt/openstack-k8s/graduation-s2-workload.py >/dev/null',
                        data=(ROOT / 'kubernetes/graduation-s2/workload.py').read_text())
            self.remote('sudo tee /opt/openstack-k8s/graduation-s2-network.sh >/dev/null',
                        data=(ROOT / 'scripts/graduation-s2-network.sh').read_text())
            self.write('network-create-intent', network_attempted=True)
            self.remote('sudo bash /opt/openstack-k8s/graduation-s2-network.sh prepare ' + run)
            self.write('network-ready')
            sg = self.admin_json('security', 'group', 'create', '--project', a['project_id'], run)
            self.write('security-group-created', security_group_id=sg['id'])
            self.admin('security', 'group', 'rule', 'create', '--protocol', 'tcp', '--dst-port', '30080',
                       '--remote-ip', '198.18.0.2/32', sg['id'])
            # OSC appends these groups to the current set; repeating existing IDs is rejected.
            self.admin('port', 'set', '--security-group', sg['id'], a['port']['id'])
            updated_port = self.admin_json('port', 'show', a['port']['id'])
            if set(updated_port['security_group_ids']) != set(a['port']['security_group_ids']) | {sg['id']}:
                raise RuntimeError('source port security groups were not preserved')
            fip = self.admin_json('floating', 'ip', 'create', '--project', a['project_id'],
                                  '--description', run, '--port', a['port']['id'], 'public')
            self.write('fip-created', fip=fip)
            policy = self.admin_json('network', 'qos', 'policy', 'create', '--project', b['project_id'], run)
            self.write('policy-created', policy_id=policy['id'])
            rule = self.admin_json('network', 'qos', 'rule', 'create', '--type', 'bandwidth-limit',
                                   '--max-kbps', '6000', '--max-burst-kbits', '600', '--egress', policy['id'])
            self.write('rule-created', rule_id=rule['id'])
            self.apply({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'code', 'namespace': self.ns},
                        'data': {'workload.py': (ROOT / 'kubernetes/graduation-s2/workload.py').read_text()}})
            self.apply(self.deployment('api', a['node'], ['api']))
            self.apply({'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': 'api', 'namespace': self.ns},
                        'spec': {'type': 'NodePort', 'externalTrafficPolicy': 'Local', 'selector': {'app': 'api'},
                                 'ports': [{'port': 8080, 'targetPort': 8080, 'nodePort': 30080}]}})
            wait_for(lambda: self.ready('api', a['node']))
            baseline = self.window('baseline')
            if not baseline['complete'] or baseline['failures'] or not baseline['p95_ms']:
                raise RuntimeError('invalid S2 baseline')
            base = baseline['p95_ms']
            self.write('baseline-ready', api_before=self.pods('api')[0])
            self.apply(self.deployment('upload', a['node'], ['upload', '--url', 'http://198.18.0.2:8090', '--seconds', '3600']))
            wait_for(lambda: self.ready('upload', a['node']))
            self.write('colocated', upload_before=self.pods('upload')[0])
            stress = [self.window('uncontrolled-' + str(i)) for i in range(2)]
            diagnosis = all(impacted(base, m) and m['egress_bps'] >= 16_000_000 and m['overlimits'] > 0 and
                            m['upload_bytes'] > 0 and max(m['cpu_utilization'].values()) < .7 for m in stress)
            self.write('diagnosed' if diagnosis else 'deferred', diagnosis=diagnosis)
            if not diagnosis:
                raise RuntimeError('service impact and shared egress contention not established')
            self.set_rate(10000)
            old = self.pods('upload')[0]
            self.save('upload-before.jsonl', self.k('-n', self.ns, 'logs', old['metadata']['name']))
            progress = self.remote('curl -fsS http://198.18.0.2:8090/progress')
            self.write('relocation-intent', progress_before_relocation=json.loads(progress))
            self.k('-n', self.ns, 'patch', 'deployment', 'upload', '--type=merge', '-p',
                   json.dumps({'spec': {'template': {'spec': {'nodeSelector': {'kubernetes.io/hostname': b['node']}}}}}))
            wait_for(lambda: self.ready('upload', b['node']), seconds=300)
            if any(p['metadata']['uid'] == old['metadata']['uid'] for p in self.pods('upload')):
                raise RuntimeError('old uploader is still present')
            self.write('relocated', upload_after=self.pods('upload')[0])
            fixed = [self.window('fixed-' + str(i)) for i in range(2)]
            # Controlled comparison: separate ports with no QoS still use the same bottleneck.
            self.admin('port', 'unset', '--qos-policy', b['port']['id'])
            split = self.window('split-unlimited')
            current = RATES[0]
            history = []
            for i in range(5):
                self.set_rate(current)
                metric = self.window('dynamic-' + str(i))
                healthy = stable(base, metric)
                history.append({'rate': current, 'healthy': healthy})
                following = next_rate(current, healthy)
                if not healthy and current == RATES[0]:
                    raise RuntimeError('API did not recover at the minimum allowed upload rate')
                # A failed upward exploration backs off and stabilizes without another increase.
                if not healthy:
                    current = following
                    break
                if following == current:
                    break
                current = following
            self.set_rate(current)
            final = [self.window('stable-' + str(i)) for i in range(2)]
            api_after = self.pods('api')
            progress_after = json.loads(self.remote('curl -fsS http://198.18.0.2:8090/progress'))
            self.save('upload-after.jsonl', self.k('-n', self.ns, 'logs', 'deployment/upload'))
            integrity_code = '''import hashlib,json,sqlite3
from pathlib import Path
root=Path(ROOT)
with sqlite3.connect(root/'progress.db') as db:
 rows=db.execute('select id,size,sha from chunks order by id').fetchall()
valid=all((root/f'{i:06d}.chunk').stat().st_size == size and hashlib.sha256((root/f'{i:06d}.chunk').read_bytes()).hexdigest()==sha for i,size,sha in rows)
print(json.dumps({'rows':rows,'all_files_valid':valid,'bytes':sum(row[1] for row in rows)}))
'''.replace('ROOT', repr('/var/lib/openstack-k8s-graduation/' + self.record['run_id']))
            integrity = json.loads(self.remote('sudo python3 -', data=integrity_code))
            self.save('upload-integrity.json', integrity)
            checks = {'sustained_diagnosis': diagnosis, 'fixed_qos_recovers': all(stable(base, m) for m in fixed),
                      'split_alone_insufficient': impacted(base, split),
                      'dynamic_recovers_with_upload': all(stable(base, m) for m in final),
                      'upload_progress_preserved': progress_after['bytes'] > self.record['progress_before_relocation']['bytes'] and
                          progress_after['next'] >= self.record['progress_before_relocation']['next'],
                      'uploaded_files_valid': integrity['all_files_valid'] and integrity['bytes'] >= progress_after['bytes'],
                      'api_pod_unchanged': len(api_after) == 1 and api_after[0]['metadata']['uid'] == self.record['api_before']['metadata']['uid'] and
                          api_after[0]['spec']['nodeName'] == a['node'],
                      'old_uploader_terminated': not any(p['metadata']['uid'] == old['metadata']['uid'] for p in self.pods('upload'))}
            summary = {'checks': checks, 'passed': all(checks.values()), 'windows': self.record['windows'],
                       'dynamic_decisions': history, 'policy_changes': self.record['policy_changes'],
                       'progress': progress_after}
            self.save('summary.json', summary)
            self.write('completed' if summary['passed'] else 'needs_review', result=summary)
            return summary
        except Exception as exc:
            self.write('failed', error=f'{type(exc).__name__}: {exc}')
            raise

    def cleanup(self):
        self.acquire()
        if not self.record or self.record['phase'] == 'cleaned':
            return self.record
        self.ownership()
        r = self.record
        errors = []
        def attempt(name, fn):
            try:
                fn()
            except Exception as exc:
                errors.append(name + ': ' + str(exc))
        attempt('namespace', self.delete_namespace)
        if r.get('policy_id'):
            def restore_qos():
                port = self.admin_json('port', 'show', r['workers'][1]['port']['id'])
                if port.get('qos_policy_id') == r['policy_id']:
                    self.admin('port', 'unset', '--qos-policy', port['id'])
                elif port.get('qos_policy_id'):
                    raise RuntimeError('external policy change')
                restored = self.admin_json('port', 'show', port['id'])
                if restored.get('qos_policy_id'):
                    raise RuntimeError('original port policy was not restored')
                self.save('port-restored.json', restored)
                existing = self.admin_json('network', 'qos', 'policy', 'list')
                if any(p['ID'] == r['policy_id'] for p in existing):
                    self.admin('network', 'qos', 'policy', 'delete', r['policy_id'])
            attempt('qos', restore_qos)
        if r.get('fip'):
            def remove_fip():
                existing = self.admin_json('floating', 'ip', 'list')
                if any(p['ID'] == r['fip']['id'] for p in existing):
                    obj = self.admin_json('floating', 'ip', 'show', r['fip']['id'])
                    if obj.get('description') != r['run_id']:
                        raise RuntimeError('floating IP ownership changed')
                    self.admin('floating', 'ip', 'delete', obj['id'])
            attempt('floating-ip', remove_fip)
        if r.get('security_group_id'):
            def remove_sg():
                existing = self.admin_json('security', 'group', 'list')
                if any(p['ID'] == r['security_group_id'] for p in existing):
                    port = self.admin_json('port', 'show', r['workers'][0]['port']['id'])
                    if r['security_group_id'] in port['security_group_ids']:
                        self.admin('port', 'unset', '--security-group', r['security_group_id'], port['id'])
                    self.admin('security', 'group', 'delete', r['security_group_id'])
            attempt('security-group', remove_sg)
        if r.get('network_attempted'):
            attempt('network', lambda: self.remote('sudo bash /opt/openstack-k8s/graduation-s2-network.sh cleanup ' + r['run_id']))
        if not errors:
            attempt('workers', self.restore_workers)
        self.write('cleanup-failed' if errors else 'cleaned', cleanup_errors=errors)
        if errors:
            raise RuntimeError('; '.join(errors))
        return r


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'cleanup', 'status'))
    args = parser.parse_args()
    runner = S2()
    result = runner.run() if args.action == 'run' else runner.cleanup() if args.action == 'cleanup' else runner.record
    print(json.dumps(result, indent=2))
    if args.action == "run" and not result["passed"]:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
