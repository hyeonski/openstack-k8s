#!/usr/bin/env bash

set -Eeuo pipefail

KOLLA_INTERNAL_VIP_ADDRESS="${KOLLA_INTERNAL_VIP_ADDRESS:?}"
EXPECTED_COMPUTE_COUNT="${EXPECTED_COMPUTE_COUNT:?}"
timeout_seconds="${OPENSTACK_RUNTIME_TIMEOUT_SECONDS:-300}"
deadline=$((SECONDS + timeout_seconds))

wait_for_keystone() {
  while (( SECONDS < deadline )); do
    if curl --fail --silent --show-error --connect-timeout 3 \
        "http://${KOLLA_INTERNAL_VIP_ADDRESS}:5000/v3/" >/dev/null 2>&1; then
      return
    fi
    sleep 2
  done
  echo "Keystone did not become ready within ${timeout_seconds}s" >&2
  exit 1
}

placement_ready() {
  [[ "$(docker inspect placement_api --format '{{.State.Health.Status}}' 2>/dev/null)" == "healthy" ]] &&
    curl --fail --silent --show-error --connect-timeout 3 \
      "http://${KOLLA_INTERNAL_VIP_ADDRESS}:8780/" >/dev/null 2>&1
}

wait_for_placement() {
  while (( SECONDS < deadline )); do
    if placement_ready; then
      return
    fi
    sleep 2
  done
  docker inspect placement_api --format '{{json .State.Health}}' >&2 || true
  echo "Placement did not become ready within ${timeout_seconds}s" >&2
  exit 1
}

openstack_compute_ready() {
  local nova_states hypervisor_states nova_count hypervisor_count
  nova_states="$(openstack --os-cloud kolla-admin compute service list \
    --service nova-compute -f value -c State 2>/dev/null)" || return 1
  hypervisor_states="$(openstack --os-cloud kolla-admin hypervisor list \
    -f value -c State 2>/dev/null)" || return 1
  nova_count="$(sed '/^$/d' <<<"${nova_states}" | wc -l | tr -d ' ')"
  hypervisor_count="$(sed '/^$/d' <<<"${hypervisor_states}" | wc -l | tr -d ' ')"
  [[ "${nova_count}" == "${EXPECTED_COMPUTE_COUNT}" ]] || return 1
  [[ "${hypervisor_count}" == "${EXPECTED_COMPUTE_COUNT}" ]] || return 1
  ! grep -Ev '^up$' <<<"${nova_states}" | grep -q . || return 1
  ! grep -Ev '^up$' <<<"${hypervisor_states}" | grep -q . || return 1
}

wait_for_openstack_compute() {
  source /opt/kolla-venv/bin/activate
  export OS_CLIENT_CONFIG_FILE=/etc/kolla/clouds.yaml
  while (( SECONDS < deadline )); do
    if openstack --os-cloud kolla-admin token issue -f value -c expires \
        >/dev/null 2>&1 && openstack_compute_ready; then
      return
    fi
    sleep 2
  done
  openstack --os-cloud kolla-admin compute service list >&2 || true
  openstack --os-cloud kolla-admin hypervisor list >&2 || true
  echo "Nova compute and hypervisors did not become ready within ${timeout_seconds}s" >&2
  exit 1
}

wait_for_keystone
placement_restarted="no"
if ! placement_ready; then
  echo "Placement is unhealthy after database readiness; restarting placement_api"
  docker restart placement_api >/dev/null
  placement_restarted="yes"
fi
wait_for_placement

if [[ "${placement_restarted}" == "yes" ]]; then
  docker restart nova_scheduler >/dev/null
fi
wait_for_openstack_compute

echo "keystone=ready"
echo "placement=ready"
echo "placement_restarted=${placement_restarted}"
echo "nova_compute_count=${EXPECTED_COMPUTE_COUNT}"
echo "hypervisor_count=${EXPECTED_COMPUTE_COUNT}"
