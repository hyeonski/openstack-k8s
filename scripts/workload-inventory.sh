#!/usr/bin/env bash
# Read-only OpenStack inventory. No recovery, boot or deletion path.
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"
run_on "${CONTROLLER_NAME}" bash -s <<'REMOTE'
set -Eeuo pipefail
source /opt/kolla-venv/bin/activate
export OS_CLIENT_CONFIG_FILE=/etc/kolla/capi-clouds.yaml
python3 - <<'PY'
import json, subprocess
resources = {'servers': ['server', 'list', '--long'], 'ports': ['port', 'list', '--long'],
             'networks': ['network', 'list'], 'subnets': ['subnet', 'list'],
             'routers': ['router', 'list'], 'security_groups': ['security', 'group', 'list'],
             'floating_ips': ['floating', 'ip', 'list']}
result = {}
for name, args in resources.items():
    raw = subprocess.check_output(['openstack', '--os-cloud', 'capi', *args, '-f', 'json'], timeout=25)
    result[name] = [{k.lower().replace(' ', '_'): v for k, v in row.items()} for row in json.loads(raw)]
# Port ownership is not available in every openstackclient list column set.
result['ports'] = [json.loads(subprocess.check_output(
    ['openstack', '--os-cloud', 'capi', 'port', 'show', p['id'], '-f', 'json',
     '-c', 'id', '-c', 'device_id', '-c', 'network_id', '-c', 'security_group_ids'], timeout=20))
    for p in result['ports']]
result['capacity'] = {}
for name, args in {'quota': ['quota', 'show'], 'limits': ['limits', 'show', '--absolute']}.items():
    try:
        result['capacity'][name] = json.loads(subprocess.check_output(
            ['openstack', '--os-cloud', 'capi', *args, '-f', 'json'], timeout=20, stderr=subprocess.PIPE))
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        result['capacity'][name] = {'query_error': str(exc)}
print(json.dumps(result))
PY
REMOTE
