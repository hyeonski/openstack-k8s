#!/usr/bin/env python3
"""Frozen, sequential live evaluation with durable evidence and explicit cleanup."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid

from graduation_env import atomic_json, utc_now
from graduation_recovery import RecoveryLab, wait_for
from graduation_s1_spread import eligible, validate_server
from workload_state import ROOT, command, condition
from worker_control import WorkerControl

PROFILE = ROOT / 'config/graduation-evaluation.json'


def read(path):
    return json.loads(Path(path).read_text()) if Path(path).is_file() else None


def source_files():
    files = [ROOT / 'Makefile', PROFILE, ROOT / 'config/environments/cloud-gcp-amd64.env']
    for directory in ('scripts', 'kubernetes', 'observability', 'infra/gcp', 'kolla', 'ansible', 'systemd'):
        files += [p for p in (ROOT / directory).rglob('*') if p.is_file() and
                  '__pycache__' not in p.parts and '.terraform' not in p.parts and
                  p.suffix in ('.py', '.sh', '.yaml', '.yml', '.tpl', '.tf', '.json', '.j2', '.service') and
                  'terraform.tfstate' not in p.name]
    return sorted(set(files))


def hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files()}


def interruption_ready(record, previous_run_id, environment_run_id, started):
    """Do not interrupt a new process using a prior trial's persistent record."""
    if not record or not record.get('run_id') or record['run_id'] == previous_run_id or\
            record.get('environment_run_id') != environment_run_id or\
            record.get('phase') not in ('injected', 'observing') or not record.get('injected_at'):
        return False
    try:
        if dt.datetime.fromisoformat(record['created']) < dt.datetime.fromisoformat(started):
            return False
    except (KeyError, TypeError, ValueError):
        return False
    observations = Path(record['evidence']) / 'observations'
    return observations.exists() and bool(list(observations.glob('[0-9][0-9][0-9][0-9].json')))


def schedule(profile):
    cases = []
    for i in range(profile['repetitions']):
        s1 = ['automatic', 'no-action'] if i % 2 == 0 else ['no-action', 'automatic']
        s3 = ['automatic', 'runbook'] if i % 2 == 0 else ['runbook', 'automatic']
        for scenario, modes in [('s1', s1), ('s2', [profile['s2']['comparison_orders'][i % 2]]), ('s3', s3), ('s4', ['normal'])]:
            for mode in modes:
                cases.append({'id': f'{scenario}-{mode}-{i + 1:02d}', 'scenario': scenario, 'mode': mode,
                              'repetition': i + 1, 'negative': False, 'status': 'pending'})
    for name in profile['negative_cases']:
        scenario, mode = name.split(':')
        cases.append({'id': f'{scenario}-{mode}', 'scenario': scenario, 'mode': mode,
                      'negative': True, 'status': 'pending'})
    qualification = ['s4-normal-01', 's4-interrupt-resume', 's1-no-destination', 's2-qos-rejection', 's3-fence-refusal']
    by_id = {c['id']: c for c in cases}
    return [by_id[name] for name in qualification] + [c for c in cases if c['id'] not in qualification]


def freeze(destination=None):
    profile = read(PROFILE)
    if any(os.environ.get(key) != profile[value] for key, value in (
            ('ENVIRONMENT_NAME', 'environment'), ('GCP_PROJECT_ID', 'project'), ('GCP_ZONE', 'zone'))):
        raise RuntimeError('evaluation requires the explicit greenfield profile override')
    name = 'graduation-evaluation-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    dest = Path(destination) if destination else ROOT / 'artifacts' / profile['environment'] / name
    dest.mkdir(parents=True, exist_ok=False, mode=0o700)
    source = hashes()
    for relative in source:
        target = dest / 'source' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    manifest = {'version': 1, 'id': name, 'created': utc_now(), 'profile': profile,
                'git_head': command(['git', '-C', ROOT, 'rev-parse', 'HEAD']).strip(),
                'source_sha256': source, 'cases': schedule(profile), 'status': 'frozen'}
    override = os.environ.get('ENV_OVERRIDE_FILE')
    if override:
        manifest['override_sha256'] = hashlib.sha256(Path(override).read_bytes()).hexdigest()
    atomic_json(dest / 'campaign.json', manifest)
    print(dest)
    return dest


class Campaign:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        if not self.directory.is_relative_to((ROOT / 'artifacts').resolve()):
            raise RuntimeError('evaluation must be stored inside repository artifacts')
        self.path = self.directory / 'campaign.json'
        self.data = read(self.path)
        if not self.data:
            raise RuntimeError('campaign does not exist; freeze first')
        self.profile = self.data['profile']
        self.state = Path(os.environ['STATE_DIR'])
        self.lab = RecoveryLab('s3')

    def save(self):
        self.data['updated'] = utc_now()
        atomic_json(self.path, self.data)

    def check_source(self):
        current = hashes()
        if current != self.data['source_sha256']:
            changed = sorted(k for k in set(current) | set(self.data['source_sha256']) if current.get(k) != self.data['source_sha256'].get(k))
            raise RuntimeError('frozen evaluation source changed: ' + ', '.join(changed))
        override = os.environ.get('ENV_OVERRIDE_FILE')
        if not override or hashlib.sha256(Path(override).read_bytes()).hexdigest() != self.data.get('override_sha256'):
            raise RuntimeError('environment override changed')

    def call(self, args, log, timeout=5400, allowed=(0,)):
        destination = self.directory / log
        destination.parent.mkdir(parents=True, exist_ok=True)
        print('Evaluation command: ' + ' '.join(map(str, args)), flush=True)
        with destination.open('a') as stream:
            stream.write('\n' + utc_now() + '\n'); stream.flush()
            with subprocess.Popen(list(map(str, args)), stdout=stream, stderr=subprocess.STDOUT,
                                  start_new_session=True, cwd=ROOT) as proc:
                try:
                    rc = proc.wait(timeout=timeout)
                except BaseException:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL); proc.wait()
                    raise
        if rc not in allowed:
            raise RuntimeError(f'evaluation command exited {rc}; inspect {destination}')
        return rc

    def make(self, target, log, *variables, timeout=5400, allowed=(0,)):
        return self.call(['make', '--no-print-directory', target, *variables], log, timeout, allowed)

    def environment(self, fresh=False):
        record = read(self.state / 'graduation-environment.json')
        if fresh and record and record['phase'] == 'ready':
            self.make('graduation-env-down', 'environment.log', timeout=1800)
        self.make('graduation-env-ensure', 'environment.log', timeout=3000)
        record = read(self.state / 'graduation-environment.json')
        deadlines = [dt.datetime.fromisoformat(h['last_start']).timestamp() + int(h['max_run_seconds'])
                     for h in record['final_hosts'].values()]
        if min(deadlines) - time.time() < self.profile['host_headroom_seconds']:
            self.make('graduation-env-down', 'environment.log', timeout=1800)
            self.make('graduation-env-ensure', 'environment.log', timeout=3000)
            record = read(self.state / 'graduation-environment.json')
        # The tunnel processes must survive the environment command's lifetime.
        for script in ('gcp-management-cluster.sh', 'gcp-workload-api-tunnel.sh'):
            action = 'tunnel' if 'management' in script else 'ensure'
            self.call([ROOT / 'scripts' / script, action], 'tunnels.log', timeout=180)
        rows = json.loads(command(['gcloud', 'compute', 'instances', 'list', '--project=' + self.profile['project'], '--format=json']))
        selected = {r['name']: r for r in rows if r['name'] in self.profile['hosts']}
        if set(selected) != set(self.profile['hosts']):
            raise RuntimeError('frozen GCP hosts missing')
        observed = {}
        for name, expected in self.profile['hosts'].items():
            row = selected[name]
            observed[name] = {k: row.get(k) for k in ('id', 'status', 'cpuPlatform', 'lastStartTimestamp')}
            observed[name]['machine_type'] = row['machineType'].split('/')[-1]
            if observed[name]['machine_type'] != expected or row['status'] != 'RUNNING':
                raise RuntimeError('frozen host configuration differs: ' + name)
        identity = {n: {'id': str(v['id']), 'machine_type': v['machine_type'], 'cpuPlatform': v['cpuPlatform']} for n, v in observed.items()}
        if self.data.get('host_identity') and identity != self.data['host_identity']:
            raise RuntimeError('host identity/platform changed between evaluation trials')
        self.data['host_identity'] = identity
        self.data.setdefault('environments', {})[record['run_id']] = {'observed': utc_now(), 'hosts': observed}
        self.save()
        atomic_json(self.directory / ('environment-' + record['run_id'] + '.json'), record)
        self.call(['kubectl', '--kubeconfig', self.state / 'kubeconfigs' / (self.lab.client.cluster + '.yaml'),
                   '-n', 'kube-system', 'rollout', 'status', 'deployment/csi-cinder-controllerplugin', '--timeout=5m'], 'environment.log', timeout=330)
        services = self.lab.admin_json('volume', 'service', 'list')
        required = [r for r in services if r.get('Binary') in ('cinder-volume', 'cinder-scheduler')]
        if len(required) < 2 or any(r.get('Status') != 'enabled' or r.get('State') != 'up' for r in required):
            raise RuntimeError('Cinder services are not enabled/up')
        flavors = {}
        for variable in ('KUBERNETES_CONTROL_PLANE_FLAVOR', 'KUBERNETES_WORKER_FLAVOR'):
            flavor = self.lab.admin_json('flavor', 'show', os.environ[variable])
            flavors[variable] = {k: flavor[k] for k in ('id', 'name', 'vcpus', 'ram', 'disk')}
            if tuple(int(flavor[k]) for k in ('vcpus', 'ram', 'disk')) != (2, 2048, 20):
                raise RuntimeError('frozen workload VM flavor differs')
        if self.data.get('flavors') and self.data['flavors'] != flavors:
            raise RuntimeError('workload VM flavor identity changed')
        self.data['flavors'] = flavors; self.save()
        return record

    def prepare_workers(self, case):
        prefix = 'cases/' + case['id']
        case['preparation_started'] = utc_now()
        mode, observed = self.lab.s1.worker()
        case['original_worker'] = {'mode': mode, 'count': observed['workers'], 'cluster_uid': observed['cluster_uid'], 'md_uid': observed['md_uid']}
        if (mode, observed['workers']) != ('auto', 1):
            raise RuntimeError('each evaluation trial starts from auto/1; inspect preceding cleanup')
        self.save()
        self.make('cluster-autoscaler-mode', prefix + '/prepare.log', 'MODE=fixed')
        self.make('workload-cluster-scale', prefix + '/prepare.log', 'WORKERS=2')
        with WorkerControl(self.lab.client) as control:
            mode, current = control.preflight('fixed')
            if not control.stable_workers(current) or current['workers'] != 2:
                raise RuntimeError('trial workers did not stabilize')
            nodes = self.lab.client.get('w', 'nodes')['items']
            workers = [self.lab.binding(n) for n in nodes if 'node-role.kubernetes.io/control-plane' not in n['metadata'].get('labels', {})]
            cp = [self.lab.binding(n) for n in nodes if 'node-role.kubernetes.io/control-plane' in n['metadata'].get('labels', {})]
            if len(cp) != 1 or cp[0]['host'] != self.profile['control_plane_compute']:
                raise RuntimeError('control-plane placement differs from the frozen profile')
            if len({w['host'] for w in workers}) == 1:
                machines = self.lab.client.get('m', 'machines', '-n', self.lab.client.ns)['items']
                pods = self.lab.client.get('w', 'pods', '-A')['items']
                preparation = {'created': case['preparation_started']}
                candidates = [w for w in workers if any(eligible(w, m, pods, preparation) for m in machines if m['metadata']['name'] == w['machine'])]
                if len(candidates) != 1:
                    raise RuntimeError('placement requires exactly one newly created empty worker')
                source = candidates[0]
                destination = next(h for h in (self.profile['source_compute'], self.profile['target_compute']) if h != source['host'])
                before = self.lab.admin_json('server', 'show', source['nova_id'])
                validate_server(before, source)
                case['migration'] = {'source': source, 'target_host': destination, 'phase': 'intent'}; self.save()
                self.lab.admin('--os-compute-api-version', '2.30', 'server', 'migrate', '--live-migration',
                               '--host', destination, '--block-migration', '--wait', source['nova_id'], timeout=900)
                def moved():
                    server = self.lab.admin_json('server', 'show', source['nova_id'])
                    node = self.lab.obj('node', source['node'], False)
                    if node['metadata']['uid'] != source['node_uid']:
                        raise RuntimeError('worker Node UID changed during trial preparation')
                    return server['status'] == 'ACTIVE' and server.get('OS-EXT-STS:task_state') is None and\
                        server['OS-EXT-SRV-ATTR:host'] == destination and condition(node, 'Ready')
                wait_for(moved, seconds=300)
                case['migration']['phase'] = 'completed'; self.save()
            nodes = self.lab.client.get('w', 'nodes')['items']
            workers = [self.lab.binding(n) for n in nodes if 'node-role.kubernetes.io/control-plane' not in n['metadata'].get('labels', {})]
            if len(workers) != 2 or {w['host'] for w in workers} != {self.profile['source_compute'], self.profile['target_compute']}:
                raise RuntimeError('trial compute roles do not match')
            if any(n['status']['nodeInfo']['kubeletVersion'] != self.profile['kubernetes_version'] for n in nodes):
                raise RuntimeError('Kubernetes version changed')
            case['placement'] = {'control_plane': cp[0], 'workers': workers}
            atomic_json(self.directory / prefix / 'placement.json', case['placement'])
        self.save()

    def state_record(self, scenario):
        return read(self.state / ('s1-auto.json' if scenario == 's1' else scenario + '-experiment.json'))

    def cleanup_case(self, case):
        scenario, prefix = case['scenario'], 'cases/' + case['id']
        record = self.state_record(scenario)
        if scenario == 's1':
            if record and record.get('phase') != 'completed':
                self.make('graduation-s1-auto-cleanup', prefix + '/cleanup.log')
            prep = read(self.state / 's1-preparation.json')
            if prep and prep.get('phase') != 'restored':
                self.make('graduation-s1-cleanup', prefix + '/cleanup.log')
        elif scenario in ('s2', 's3'):
            if record and record.get('phase') != 'cleaned':
                self.make('graduation-' + scenario + '-cleanup', prefix + '/cleanup.log')
        else:
            prep = read(self.state / 's4-preparation.json')
            if prep and prep.get('phase') != 'restored':
                if record and record.get('stop_intent_at') and record['phase'] not in ('completed', 'completed_with_gap'):
                    raise RuntimeError('S4 interrupted recovery must be resumed before cleanup')
                self.make('graduation-s4-cleanup', prefix + '/cleanup.log')
        if case.get('original_worker'):
            original = case['original_worker']
            mode, state = self.lab.s1.worker()
            if state['cluster_uid'] != original['cluster_uid'] or state['md_uid'] != original['md_uid']:
                raise RuntimeError('trial cluster identity changed before worker restoration')
            if state['workers'] != original['count']:
                self.make('workload-cluster-scale', prefix + '/cleanup.log', 'WORKERS=' + str(original['count']))
            if mode != original['mode']:
                self.make('cluster-autoscaler-mode', prefix + '/cleanup.log', 'MODE=' + original['mode'])
        self.verify_cleanup(case)

    def verify_cleanup(self, case):
        checks = {}
        for name in ('graduation-s1', 'graduation-s2', 'graduation-s3', 'graduation-s4'):
            checks[name + '_absent'] = self.lab.obj('namespace', name, False) is None
        mode, current = self.lab.s1.worker()
        checks['worker_auto_one'] = mode == 'auto' and current['workers'] == 1
        nodes = self.lab.client.get('w', 'nodes')['items']
        checks['no_trial_taints'] = all(not any(t['key'] in ('openstack-k8s.dev/evaluation-unavailable', 'node.kubernetes.io/out-of-service')
                                     for t in n['spec'].get('taints', [])) for n in nodes)
        record = self.state_record(case['scenario'])
        if record and case.get('run_id') == record.get('run_id'):
            if case['scenario'] == 's1':
                checks['competitor_absent'] = not any(v['Name'] == record.get('server_name') for v in self.lab.admin_json('server', 'list'))
                checks['competitor_flavor_absent'] = not any(v['Name'] == record.get('flavor_name') for v in self.lab.admin_json('flavor', 'list'))
            elif case['scenario'] == 's2':
                checks['qos_absent'] = not any(v['ID'] == record.get('policy_id') for v in self.lab.admin_json('network', 'qos', 'policy', 'list'))
                checks['fip_absent'] = not any(v['ID'] == record.get('fip', {}).get('id') for v in self.lab.admin_json('floating', 'ip', 'list'))
                checks['security_group_absent'] = not any(v['ID'] == record.get('security_group_id') for v in self.lab.admin_json('security', 'group', 'list'))
                checks['egress_removed'] = self.lab.remote('if ip link show s2-egress >/dev/null 2>&1; then echo present; else echo absent; fi').strip() == 'absent'
            elif case['scenario'] == 's3':
                checks['volume_absent'] = not any(v['ID'] == record.get('volume_id') for v in self.lab.admin_json('volume', 'list', '--all-projects'))
                checks['pv_absent'] = not any(v['metadata']['name'] == record.get('pv_name') for v in self.lab.client.get('w', 'pv')['items'])
                checks['controller_policy_restored'] = (Path(record['evidence']) / 'controller-manager-before.yaml').read_bytes() == (Path(record['evidence']) / 'controller-manager-after.yaml').read_bytes()
                machines = self.lab.client.get('m', 'machines', '-n', self.lab.client.ns)['items']
                checks['remediation_skip_removed'] = not any(m['metadata'].get('annotations', {}).get('cluster.x-k8s.io/skip-remediation') == record['run_id'] for m in machines)
        proof = {'time': utc_now(), 'checks': checks, 'passed': all(checks.values())}
        atomic_json(self.directory / 'cases' / case['id'] / 'cleanup-verification.json', proof)
        if not proof['passed']:
            raise RuntimeError('trial cleanup verification failed: ' + json.dumps(checks))
        case['cleanup_verified'] = True; self.save()

    def execute(self, case):
        prefix = 'cases/' + case['id']
        directory = self.directory / prefix
        directory.mkdir(parents=True, exist_ok=True)
        self.check_source()
        case.update(status='preparing', started=utc_now()); self.save()
        env = self.environment()
        case['environment_run_id'] = env['run_id']; self.save()
        self.prepare_workers(case)
        if case['scenario'] == 's1':
            self.make('graduation-s1-prepare', prefix + '/prepare.log')
        case['status'] = 'running'; self.save()
        args = [sys.executable, ROOT / 'scripts/graduation_evaluation_case.py', case['scenario'], '--mode', case['mode']]
        if case['mode'] == 'interrupt-resume':
            rc = self.interrupt_s4(case, args)
        else:
            rc = self.call(args, prefix + '/run.log', timeout=self.profile['max_case_seconds'], allowed=(0, 1, 2, 20))
        record = self.state_record(case['scenario'])
        if not record or record.get('environment_run_id') != case['environment_run_id']:
            raise RuntimeError('trial produced no matching experiment record')
        case.update(returncode=rc, run_id=record['run_id'], evidence=record['evidence'], status='measured')
        self.save()
        atomic_json(directory / 'record-before-cleanup.json', record)
        if case['negative'] and case['scenario'] != 's4':
            proof = read(Path(record['evidence']) / 'expected-rejection.json')
            case['accepted'] = rc == 20 and bool(proof and proof['passed'])
        elif case['mode'] == 'interrupt-resume':
            case['accepted'] = bool(case.get('resume_checks') and all(case['resume_checks'].values()))
        else:
            case['accepted'] = rc == 0
        self.cleanup_case(case)
        evidence = Path(case['evidence'])
        case['evidence_sha256'] = {str(p.relative_to(evidence)): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in evidence.rglob('*') if p.is_file()}
        self.check_source()
        case.update(status='complete' if case['accepted'] else 'needs_review', finished=utc_now())
        self.save()
        print('Evaluation case finished: ' + case['id'] + ' ' + case['status'], flush=True)
        if not case['accepted']:
            # A measured non-success is preserved, not replaced or reclassified.
            print('Non-success retained in the cohort; continuing only after verified cleanup.', flush=True)

    def interrupt_s4(self, case, args):
        path = self.directory / 'cases' / case['id'] / 'run.log'
        previous = self.state_record('s4')
        previous_run_id = previous.get('run_id') if previous else None
        started = utc_now()
        with path.open('a') as stream:
            with subprocess.Popen(list(map(str, args)), stdout=stream, stderr=subprocess.STDOUT,
                                  start_new_session=True, cwd=ROOT) as proc:
                deadline = time.monotonic() + 1200
                target = None
                while time.monotonic() < deadline and proc.poll() is None:
                    record = self.state_record('s4')
                    if interruption_ready(record, previous_run_id, case['environment_run_id'], started):
                        target = record; break
                    time.sleep(2)
                if not target:
                    if proc.poll() is None:
                        os.killpg(proc.pid, signal.SIGTERM); proc.wait(timeout=60)
                    raise RuntimeError('S4 never reached the recorded interruption point')
                case['interruption'] = {'time': utc_now(), 'pid': proc.pid, 'signal': 'SIGKILL',
                                        'run_id': target['run_id'], 'stop_intent_at': target['stop_intent_at'],
                                        'injected_at': target['injected_at'], 'target': target['target']}
                self.save()
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=30)
                case['interruption']['returncode'] = proc.returncode; self.save()
        time.sleep(20)
        rc = self.make('graduation-s4-resume', 'cases/' + case['id'] + '/resume.log', allowed=(0, 2))
        record = self.state_record('s4')
        workflow = read(self.state / 's4-workflow.json')
        analysis = read(Path(record['evidence']) / 'analysis/summary.json')
        case['resume_checks'] = {
            'process_killed': case['interruption']['returncode'] == -signal.SIGKILL,
            'same_run': record['run_id'] == target['run_id'],
            'same_stop_intent': record['stop_intent_at'] == target['stop_intent_at'],
            'same_target': record['target'] == target['target'],
            'gap_preserved': record.get('resumed_with_gap') is True and analysis['state'] == 'incomplete',
            'workflow_completed_with_gap': workflow['phase'] == 'completed_with_gap',
            'resume_command_succeeded': rc == 0,
        }
        atomic_json(self.directory / 'cases' / case['id'] / 'resume-verification.json', case['resume_checks'])
        self.save()
        return rc

    def run(self, limit=None):
        with (self.state / 'graduation-evaluation.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.check_source()
            unfinished = [c for c in self.data['cases'] if c['status'] not in ('pending', 'complete', 'needs_review')]
            if unfinished:
                raise RuntimeError('unfinished evaluation case requires explicit inspection: ' + unfinished[0]['id'])
            self.data['status'] = 'running'; self.save()
            count = 0
            try:
                for case in self.data['cases']:
                    if case['status'] != 'pending':
                        continue
                    self.execute(case)
                    count += 1
                    if limit and count >= limit:
                        break
                self.data['status'] = 'measured' if all(c['status'] != 'pending' for c in self.data['cases']) else 'batch-complete'
                self.save()
            except BaseException as exc:
                self.data.update(status='interrupted', error=f'{type(exc).__name__}: {exc}'); self.save()
                raise
            if self.data['status'] == 'measured':
                self.make('graduation-env-down', 'environment.log', timeout=1800)
                atomic_json(self.directory / 'environment-final.json', read(self.state / 'graduation-environment.json'))
                self.data['status'] = 'awaiting-independent-verification'; self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'run', 'status'))
    parser.add_argument('--campaign')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    if args.action == 'freeze':
        freeze(args.campaign)
        return
    campaign = Campaign(args.campaign)
    if args.action == 'run':
        campaign.run(args.limit)
    else:
        print(json.dumps({'id': campaign.data['id'], 'status': campaign.data['status'],
                          'counts': {s: sum(c['status'] == s for c in campaign.data['cases']) for s in sorted({c['status'] for c in campaign.data['cases']})},
                          'cases': [{k: c[k] for k in ('id', 'status', 'returncode', 'accepted', 'cleanup_verified') if k in c} for c in campaign.data['cases']]}, indent=2))


if __name__ == '__main__':
    main()
