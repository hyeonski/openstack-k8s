#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

instance_running "${CONTROLLER_NAME}" || die "controller is not running"
instance_running "${COMPUTE_NAME}" || die "compute is not running"
scripts/sync-guest-clocks.sh --check-only

controller_ip="$(controller_ipv4)"
compute_ip="$(compute_ipv4)"
attempts="${LOCAL_HEALTH_ATTEMPTS:-30}"
delay="${LOCAL_HEALTH_DELAY_SECONDS:-2}"

wait_for_management_network() {
  local attempt
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if run_on "${CONTROLLER_NAME}" ping -q -c 1 -W 1 "${compute_ip}" >/dev/null 2>&1 &&
       run_on "${COMPUTE_NAME}" ping -q -c 1 -W 1 "${controller_ip}" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${delay}"
  done
  return 1
}

if ! wait_for_management_network; then
  die "management network is not passing traffic between ${controller_ip} and ${compute_ip}; stop both Lima instances and start them again"
fi
log "Management network is healthy in both directions"

# A newly created pair of Lima hosts has no OpenStack credentials yet. In that
# case the management-network gate above is the complete local readiness check.
if ! run_on "${CONTROLLER_NAME}" test -s /etc/kolla/clouds.yaml; then
  log "OpenStack is not deployed yet; host readiness checks passed"
  exit 0
fi

wait_for_openstack() {
  local attempt
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if run_on "${CONTROLLER_NAME}" env \
        KOLLA_INTERNAL_VIP_ADDRESS="${KOLLA_INTERNAL_VIP_ADDRESS}" \
        bash -lc '
          set -Eeuo pipefail
          export OS_CLIENT_CONFIG_FILE=/etc/kolla/clouds.yaml
          source /opt/kolla-venv/bin/activate
          curl --fail --silent --show-error --connect-timeout 3 \
            "http://${KOLLA_INTERNAL_VIP_ADDRESS}:5000/v3/" >/dev/null
          mapfile -t nova_states < <(openstack --os-cloud kolla-admin \
            compute service list --service nova-compute -f value -c State)
          mapfile -t hypervisor_states < <(openstack --os-cloud kolla-admin \
            hypervisor list -f value -c State)
          ((${#nova_states[@]} > 0 && ${#hypervisor_states[@]} > 0))
          for state in "${nova_states[@]}" "${hypervisor_states[@]}"; do
            [[ "${state}" == "up" ]]
          done
        ' >/dev/null 2>&1; then
      return 0
    fi
    sleep "${delay}"
  done
  return 1
}

if ! wait_for_openstack; then
  warn "OpenStack did not become ready after $((attempts * delay)) seconds"
  run_on "${CONTROLLER_NAME}" bash -lc '
    export OS_CLIENT_CONFIG_FILE=/etc/kolla/clouds.yaml
    source /opt/kolla-venv/bin/activate
    openstack --os-cloud kolla-admin compute service list || true
    openstack --os-cloud kolla-admin hypervisor list || true
  ' >&2
  exit 1
fi

log "OpenStack API, nova-compute and hypervisor are ready"
