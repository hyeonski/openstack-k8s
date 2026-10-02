#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"
[[ "${1:-}" == apply ]] || die 'usage: graduation-foundation.sh apply'
# In-flight experiments must finish before restarting networking/storage services.
python3 - "$STATE_DIR" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
for name in ('s1-contention.json', 's1-auto.json', 's2-experiment.json', 's3-experiment.json'):
    path = root / name
    if path.exists() and json.loads(path.read_text()).get('phase') not in ('completed', 'cleaned'):
        raise SystemExit('unfinished experiment: ' + name)
PY
copy_to "${PROJECT_ROOT}/scripts/graduation-foundation-remote.sh" "$CONTROLLER_NAME" /tmp/osk8s-graduation-foundation.sh
run_on "$CONTROLLER_NAME" sudo bash /tmp/osk8s-graduation-foundation.sh
# Kolla globals.d survives regular template rendering; enable the storage group
# in generated inventory on each application of this foundation.
bash "${PROJECT_ROOT}/scripts/run-controller.sh" kolla-ansible deploy \
  -i "${KOLLA_DEPLOY_DIR}/kolla/generated/multinode" --tags neutron,cinder,iscsi,haproxy,nova
# Confirm deployed capabilities rather than interpreting an Ansible exit code.
run_on "$CONTROLLER_NAME" bash -s <<'REMOTE'
set -Eeuo pipefail
source /opt/kolla-venv/bin/activate
export OS_CLIENT_CONFIG_FILE=/etc/kolla/clouds.yaml
python3 - <<'PY'
import json, subprocess, time

def query(*args):
    return json.loads(subprocess.check_output(['openstack', '--os-cloud', 'kolla-admin', *args, '-f', 'json'], timeout=45))

for attempt in range(12):
    rows = query('volume', 'service', 'list')
    up = {row['Binary'] for row in rows if row['State'] == 'up' and row['Status'] == 'enabled'}
    if {'cinder-scheduler', 'cinder-volume'} <= up:
        break
    time.sleep(5)
else:
    raise SystemExit('Cinder services did not become healthy')
extensions = query('extension', 'list', '--network')
if not any(row['Alias'] == 'qos' for row in extensions):
    raise SystemExit('Neutron QoS extension is missing')
print(json.dumps({'cinder_services': rows, 'qos_rule_types': query('network', 'qos', 'rule', 'type', 'list')}))
PY
REMOTE
