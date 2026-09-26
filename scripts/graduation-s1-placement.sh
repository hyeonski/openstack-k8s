#!/usr/bin/env bash
# Read the Nova compute placement using admin visibility; the CAPI project hides Host.
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

server_id="${1:?Nova server UUID is required}"
[[ "${server_id}" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] ||
  die "invalid Nova server UUID"
run_on "${CONTROLLER_NAME}" env SERVER_ID="${server_id}" bash -lc '
  set -Eeuo pipefail
  source /opt/kolla-venv/bin/activate
  export OS_CLIENT_CONFIG_FILE=/etc/kolla/clouds.yaml
  openstack --os-cloud kolla-admin server show "${SERVER_ID}" -f json \
    -c id -c name -c status -c OS-EXT-SRV-ATTR:host \
    -c OS-EXT-SRV-ATTR:hypervisor_hostname
'
