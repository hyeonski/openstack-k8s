#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"
action="${1:?show, stop or list required}"
case "${action}" in
  show|stop)
    server_id="${2:?exact Nova UUID required}"
    [[ "${server_id}" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] ||
      die "invalid Nova UUID"
    if [[ "${action}" == show ]]; then
      run_on "${CONTROLLER_NAME}" sudo env OS_CLIENT_CONFIG_FILE=/etc/kolla/clouds.yaml \
        /opt/kolla-venv/bin/openstack --os-cloud kolla-admin server show "${server_id}" -f json -c id -c name -c status
    else
      run_on "${CONTROLLER_NAME}" sudo env OS_CLIENT_CONFIG_FILE=/etc/kolla/clouds.yaml \
        /opt/kolla-venv/bin/openstack --os-cloud kolla-admin server stop "${server_id}"
    fi
    ;;
  list)
    run_on "${CONTROLLER_NAME}" sudo env OS_CLIENT_CONFIG_FILE=/etc/kolla/clouds.yaml \
      /opt/kolla-venv/bin/openstack --os-cloud kolla-admin server list --all-projects --long -f json -c ID -c Name -c Status
    ;;
  *) die "unknown S4 Nova action: ${action}" ;;
esac
