#!/usr/bin/env bash
# Start only the current CAPI workload Machines after the GCE hosts reboot.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${ROOT}/scripts/lib/common.sh"

ensure_management_api_access
server_ids=()
while IFS= read -r server_id; do
  server_ids+=("${server_id}")
done < <(
  kubectl --kubeconfig "${STATE_DIR}/kubeconfigs/management.yaml" \
    -n "${WORKLOAD_NAMESPACE}" get machines \
    -l "cluster.x-k8s.io/cluster-name=${WORKLOAD_CLUSTER_NAME}" -o json |
    python3 -c '
import json, sys
for machine in json.load(sys.stdin)["items"]:
    if machine["metadata"].get("deletionTimestamp"):
        continue
    provider_id = machine.get("spec", {}).get("providerID") or machine.get("status", {}).get("providerID") or ""
    if provider_id.startswith("openstack:///"):
        print(provider_id.removeprefix("openstack:///"))
')
(( ${#server_ids[@]} > 0 )) || die "no current workload Machine has an OpenStack provider ID"

server_state() {
  local server_id="$1"
  run_on "${CONTROLLER_NAME}" sudo env \
    OS_CLIENT_CONFIG_FILE=/etc/kolla/clouds.yaml \
    /opt/kolla-venv/bin/openstack --os-cloud kolla-admin \
    server show "${server_id}" -f value -c status
}

for server_id in "${server_ids[@]}"; do
  stable=0
  for attempt in 1 2; do
    state="$(server_state "${server_id}")"
    case "${state}" in
      ACTIVE) ;;
      SHUTOFF)
        run_on "${CONTROLLER_NAME}" sudo env \
          OS_CLIENT_CONFIG_FILE=/etc/kolla/clouds.yaml \
          /opt/kolla-venv/bin/openstack --os-cloud kolla-admin \
          server start "${server_id}"
        log "started workload guest: ${server_id} (attempt ${attempt})"
        ;;
      *) die "workload guest ${server_id} has unexpected state: ${state}" ;;
    esac
    stable=0
    for _ in {1..12}; do
      sleep 5
      state="$(server_state "${server_id}")"
      case "${state}" in
        ACTIVE)
          ((stable += 1))
          [[ "${stable}" -ge 3 ]] && break
          ;;
        SHUTOFF) stable=0; break ;;
        BUILD|REBOOT|HARD_REBOOT) stable=0 ;;
        *) die "workload guest ${server_id} has unexpected state: ${state}" ;;
      esac
    done
    if [[ "${stable}" -ge 3 ]]; then
      log "workload guest stably ACTIVE: ${server_id}"
      break
    fi
    [[ "${state}" == SHUTOFF ]] ||
      die "workload guest ${server_id} left ACTIVE with unexpected state: ${state}"
  done
  [[ "${stable}" -ge 3 ]] || die "workload guest did not remain ACTIVE: ${server_id}"
done
