"""Shared environment, worker, and OpenStack access for all scenarios.

This module must not import S1/S2/S3/S4 or the optional evaluation package.
"""
import base64
import json
import os
import shlex

from worker_control import WorkerControl
from workload_state import ROOT, command

LABEL = 'openstack-k8s.dev/experiment'


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 3)


def host_cpu_utilization(before, after):
    deltas = [end - start for start, end in zip(before['cpu_ticks'], after['cpu_ticks'])]
    total = sum(deltas)
    if len(deltas) != 8 or total <= 0 or any(value < 0 for value in deltas):
        raise RuntimeError('invalid compute host CPU counter delta')
    return round((total - deltas[3] - deltas[4]) / total, 5)


class LabRuntime:
    def __init__(self, client):
        self.client = client

    def environment(self):
        path = self.client.state / 'graduation-environment.json'
        if not path.exists():
            raise RuntimeError('run graduation-env-ensure first')
        data = json.loads(path.read_text())
        profile = {'environment': os.environ['ENVIRONMENT_NAME'],
                   'project': os.environ['GCP_PROJECT_ID'], 'zone': os.environ['GCP_ZONE'],
                   'cluster': self.client.cluster}
        if data.get('phase') != 'ready' or data.get('profile') != profile:
            raise RuntimeError('environment is not Ready for the selected profile')
        return data

    def worker(self):
        with WorkerControl(self.client) as control:
            mode, observed = control.preflight()
            if not control.stable_workers(observed):
                raise RuntimeError('worker MachineDeployment is unstable')
            return mode, observed

    @staticmethod
    def host_stat(host):
        return json.loads(command([ROOT / 'scripts/host-stat.sh', host], timeout=90))

    def remote(self, script, *, host=None, timeout=120, data=None):
        args = ['gcloud', 'compute', 'ssh', os.environ['TARGET_SSH_USER'] + '@' + (host or os.environ['CONTROLLER_NAME']),
                '--project=' + os.environ['GCP_PROJECT_ID'], '--zone=' + os.environ['GCP_ZONE'], '--quiet']
        if os.environ.get('GCP_USE_IAP_TUNNEL') == 'yes':
            args.append('--tunnel-through-iap')
        return command([*args, '--command=' + shlex.join(['bash', '-lc', script])], timeout=timeout, data=data)

    def admin(self, *args, timeout=60, user_data=None):
        cloud = ('set -euo pipefail; source /opt/kolla-venv/bin/activate; '
                 'export OS_CLIENT_CONFIG_FILE=/etc/kolla/clouds.yaml; ')
        if user_data is not None:
            encoded = base64.b64encode(user_data.encode()).decode()
            cloud += ("file=$(mktemp); trap 'rm -f \"$file\"' EXIT; "
                      f'printf %s {shlex.quote(encoded)} | base64 -d >"$file"; ')
            args = tuple('$file' if arg == '@user-data' else arg for arg in args)
            quoted = ' '.join('"$file"' if arg == '$file' else shlex.quote(str(arg))
                              for arg in args)
        else:
            quoted = shlex.join(map(str, args))
        cloud += 'openstack --os-cloud kolla-admin ' + quoted
        return self.remote(cloud, timeout=timeout)

    def admin_json(self, *args, **kwargs):
        return json.loads(self.admin(*args, '-f', 'json', **kwargs))
