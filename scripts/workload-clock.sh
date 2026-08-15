#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

is_epoch() {
  [[ "${1:-}" =~ ^[0-9]+$ ]]
}

absolute_delta() {
  local left="$1"
  local right="$2"
  local delta=$((left - right))
  (( delta < 0 )) && delta=$((-delta))
  printf '%s\n' "${delta}"
}

within_window() {
  local value="$1"
  local lower="$2"
  local upper="$3"
  (( value >= lower && value <= upper ))
}

self_test() {
  is_epoch 1704067200
  ! is_epoch invalid
  [[ "$(absolute_delta 20 5)" == "15" ]]
  [[ "$(absolute_delta 5 20)" == "15" ]]
  within_window 100 95 105
  ! within_window 106 95 105
  echo "Workload clock helper logic passed."
}

action="${1:-check}"
if [[ "${action}" == "--self-test" ]]; then
  self_test
  exit 0
fi
[[ "${action}" == "check" || "${action}" == "recover" ]] ||
  die "usage: $0 {check|recover|--self-test}"

[[ "${ENV}" == "local-arm64" ]] ||
  die "workload clock recovery is intentionally limited to local-arm64"
require_command kubectl
require_command limactl
is_epoch "${MAX_CLOCK_SKEW_SECONDS}" ||
  die "MAX_CLOCK_SKEW_SECONDS must be a non-negative integer"

management_kubeconfig="${STATE_DIR}/kubeconfigs/management.yaml"
[[ -f "${management_kubeconfig}" ]] ||
  die "management kubeconfig is missing: ${management_kubeconfig}"
instance_running "${CONTROLLER_NAME}" || die "${CONTROLLER_NAME} is not running"
instance_running "${COMPUTE_NAME}" || die "${COMPUTE_NAME} is not running"
kubectl --kubeconfig "${management_kubeconfig}" get nodes >/dev/null

machine_rows="$(kubectl --kubeconfig "${management_kubeconfig}" \
  -n "${WORKLOAD_NAMESPACE}" get machines \
  -l "cluster.x-k8s.io/cluster-name=${WORKLOAD_CLUSTER_NAME}" \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.addresses[?(@.type=="InternalIP")]}{.address}{end}{"\t"}{.spec.providerID}{"\n"}{end}')"
[[ -n "${machine_rows}" ]] ||
  die "no workload Machines found for ${WORKLOAD_NAMESPACE}/${WORKLOAD_CLUSTER_NAME}"

while IFS=$'\t' read -r machine_name machine_address provider_id; do
  [[ -n "${machine_name}" && -n "${machine_address}" ]] ||
    die "Machine is missing an InternalIP: ${machine_name:-unknown}"
  [[ "${provider_id}" == openstack:///* ]] ||
    die "Machine is missing an OpenStack providerID: ${machine_name}"
  server_id="${provider_id#openstack:///}"
  server_status="$(run_on "${CONTROLLER_NAME}" env SERVER_ID="${server_id}" bash -lc '
    set -Eeuo pipefail
    source /opt/kolla-venv/bin/activate
    export OS_CLIENT_CONFIG_FILE=/etc/kolla/capi-clouds.yaml
    openstack --os-cloud capi server show "${SERVER_ID}" -f value -c status
  ' </dev/null)"
  if [[ "${server_status}" == "SHUTOFF" && "${action}" == "recover" ]]; then
    log "Starting ${machine_name} after outer-host resume"
    run_on "${CONTROLLER_NAME}" env SERVER_ID="${server_id}" bash -lc '
      set -Eeuo pipefail
      source /opt/kolla-venv/bin/activate
      export OS_CLIENT_CONFIG_FILE=/etc/kolla/capi-clouds.yaml
      openstack --os-cloud capi server start "${SERVER_ID}"
    ' </dev/null
    for attempt in {1..60}; do
      server_status="$(run_on "${CONTROLLER_NAME}" env SERVER_ID="${server_id}" bash -lc '
        set -Eeuo pipefail
        source /opt/kolla-venv/bin/activate
        export OS_CLIENT_CONFIG_FILE=/etc/kolla/capi-clouds.yaml
        openstack --os-cloud capi server show "${SERVER_ID}" -f value -c status
      ' </dev/null)"
      [[ "${server_status}" == "ACTIVE" ]] && break
      sleep 2
    done
  fi
  [[ "${server_status}" == "ACTIVE" ]] ||
    die "Nova server for ${machine_name} is ${server_status}; run make resume-recover"
done <<<"${machine_rows}"

router_namespace="$(run_on "${CONTROLLER_NAME}" env \
  WORKLOAD_NETWORK_CIDR="${WORKLOAD_NETWORK_CIDR}" bash -lc '
    set -Eeuo pipefail
    for attempt in {1..60}; do
      while read -r namespace _; do
        [[ -n "${namespace}" ]] || continue
        route_entry="$(sudo ip netns exec "${namespace}" \
          ip -4 route show "${WORKLOAD_NETWORK_CIDR}")"
        if [[ -n "${route_entry}" ]]; then
          printf "%s\n" "${namespace}"
          exit 0
        fi
      done < <(sudo ip netns list)
      sleep 2
    done
    exit 1
  ' </dev/null || true)"
[[ -n "${router_namespace}" ]] ||
  die "Neutron router namespace for ${WORKLOAD_NETWORK_CIDR} was not found"

while IFS=$'\t' read -r machine_name machine_address provider_id; do
  [[ -n "${machine_name}" && -n "${machine_address}" ]] ||
    die "Machine is missing an InternalIP: ${machine_name:-unknown}"

  host_before="$(date -u +%s)"
  result="$(run_on "${CONTROLLER_NAME}" env \
    ROUTER_NAMESPACE="${router_namespace}" \
    MACHINE_ADDRESS="${machine_address}" \
    TARGET_SSH_USER="${TARGET_SSH_USER}" \
    RECOVERY_MODE="${action}" \
    MAX_CLOCK_SKEW_SECONDS="${MAX_CLOCK_SKEW_SECONDS}" \
    RTC_MINIMUM_EPOCH="${RTC_MINIMUM_EPOCH}" \
    bash -s <<'CONTROLLER_WORKLOAD_CLOCK'
set -Eeuo pipefail

deployment_key="/home/${TARGET_SSH_USER}/.ssh/openstack_k8s"
[[ -s "${deployment_key}" ]] || {
  echo "project workload SSH key is missing: ${deployment_key}" >&2
  exit 1
}

for attempt in {1..60}; do
  if sudo ip netns exec "${ROUTER_NAMESPACE}" ssh \
      -i "${deployment_key}" \
      -o BatchMode=yes \
      -o ConnectTimeout=5 \
      -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      "${TARGET_SSH_USER}@${MACHINE_ADDRESS}" true \
      </dev/null >/dev/null 2>&1; then
    break
  fi
  if [[ "${attempt}" == "60" ]]; then
    echo "workload SSH did not become ready: ${MACHINE_ADDRESS}" >&2
    exit 1
  fi
  sleep 2
done

host_epoch="$(date -u +%s)"
sudo ip netns exec "${ROUTER_NAMESPACE}" ssh \
  -i "${deployment_key}" \
  -o BatchMode=yes \
  -o ConnectTimeout=10 \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  "${TARGET_SSH_USER}@${MACHINE_ADDRESS}" env \
    RECOVERY_MODE="${RECOVERY_MODE}" \
    HOST_EPOCH="${host_epoch}" \
    MAX_CLOCK_SKEW_SECONDS="${MAX_CLOCK_SKEW_SECONDS}" \
    RTC_MINIMUM_EPOCH="${RTC_MINIMUM_EPOCH}" \
    bash -s <<'GUEST_WORKLOAD_CLOCK'
set -Eeuo pipefail

absolute_delta() {
  local left="$1"
  local right="$2"
  local delta=$((left - right))
  (( delta < 0 )) && delta=$((-delta))
  printf '%s\n' "${delta}"
}

chrony_source_ready() {
  local tracking leap reference_id stratum
  tracking="$(chronyc tracking 2>/dev/null || true)"
  leap="$(awk -F: '$1 ~ /Leap status/ { gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2; exit }' <<<"${tracking}")"
  reference_id="$(awk -F: '$1 ~ /Reference ID/ { gsub(/^[[:space:]]+/, "", $2); print $2; exit }' <<<"${tracking}")"
  stratum="$(awk -F: '$1 ~ /Stratum/ { gsub(/[[:space:]]/, "", $2); print $2; exit }' <<<"${tracking}")"
  [[ "${leap}" == "Normal" ]] || return 1
  [[ "${stratum}" =~ ^[1-9][0-9]*$ ]] || return 1
  [[ -n "${reference_id}" && "${reference_id}" != 00000000* ]]
}

current_epoch="$(date -u +%s)"
[[ "${current_epoch}" =~ ^[0-9]+$ ]] || {
  echo "invalid workload system epoch: ${current_epoch}" >&2
  exit 1
}
rtc_epoch_file=/sys/class/rtc/rtc0/since_epoch
[[ -r "${rtc_epoch_file}" ]] || {
  echo "workload RTC is unavailable: ${rtc_epoch_file}" >&2
  exit 1
}
rtc_epoch="$(tr -d '[:space:]' <"${rtc_epoch_file}")"
[[ "${rtc_epoch}" =~ ^[0-9]+$ && "${rtc_epoch}" -ge "${RTC_MINIMUM_EPOCH}" ]] || {
  echo "invalid workload RTC epoch: ${rtc_epoch}" >&2
  exit 1
}

method="check-only"
delta="$(absolute_delta "${current_epoch}" "${HOST_EPOCH}")"
if [[ "${RECOVERY_MODE}" == "recover" && "${delta}" -gt "${MAX_CLOCK_SKEW_SECONDS}" ]]; then
  if (( current_epoch > HOST_EPOCH + MAX_CLOCK_SKEW_SECONDS )); then
    echo "workload clock is ${delta}s ahead of the host; refusing an automatic backward step" >&2
    exit 1
  fi

  rtc_delta="$(absolute_delta "${rtc_epoch}" "${HOST_EPOCH}")"
  rtc_tolerance=$((MAX_CLOCK_SKEW_SECONDS + 10))
  (( rtc_delta <= rtc_tolerance )) || {
    echo "workload RTC differs from the host by ${rtc_delta}s" >&2
    exit 1
  }

  if command -v chronyc >/dev/null 2>&1 &&
      systemctl is-active --quiet chrony && chrony_source_ready; then
    sudo chronyc -a makestep >/dev/null
    sleep 2
    method="chrony"
  fi

  current_epoch="$(date -u +%s)"
  delta="$(absolute_delta "${current_epoch}" "${HOST_EPOCH}")"
  if (( delta > MAX_CLOCK_SKEW_SECONDS )); then
    sudo date -u -s "@${rtc_epoch}" >/dev/null
    current_epoch="$(date -u +%s)"
    method="rtc"
  fi
fi

printf '%s\t%s\t%s\n' "${method}" "$(date -u +%s)" "${rtc_epoch}"
GUEST_WORKLOAD_CLOCK
CONTROLLER_WORKLOAD_CLOCK
  )" || die "failed to ${action} ${machine_name} clock"

  IFS=$'\t' read -r method guest_epoch rtc_epoch <<<"${result}"
  is_epoch "${guest_epoch}" ||
    die "${machine_name} returned an invalid epoch: ${guest_epoch}"
  host_after="$(date -u +%s)"
  lower_bound=$((host_before - MAX_CLOCK_SKEW_SECONDS))
  upper_bound=$((host_after + MAX_CLOCK_SKEW_SECONDS))
  within_window "${guest_epoch}" "${lower_bound}" "${upper_bound}" || {
    skew="$(absolute_delta "${guest_epoch}" "${host_after}")"
    die "${machine_name} clock skew is ${skew}s; run make resume-recover after macOS sleep"
  }
  skew="$(absolute_delta "${guest_epoch}" "${host_after}")"
  log "${machine_name} clock is healthy: skew=${skew}s method=${method}"
done <<<"${machine_rows}"

log "All workload clocks passed the ${action} gate"
