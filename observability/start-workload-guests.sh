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

for server_id in "${server_ids[@]}"; do
  state="$(run_on "${CONTROLLER_NAME}" sudo env \
    OS_CLIENT_CONFIG_FILE=/etc/kolla/clouds.yaml \
    /opt/kolla-venv/bin/openstack --os-cloud kolla-admin \
    server show "${server_id}" -f value -c status)"
  case "${state}" in
    ACTIVE) log "workload guest already ACTIVE: ${server_id}" ;;
    SHUTOFF)
      run_on "${CONTROLLER_NAME}" sudo env \
        OS_CLIENT_CONFIG_FILE=/etc/kolla/clouds.yaml \
        /opt/kolla-venv/bin/openstack --os-cloud kolla-admin \
        server start "${server_id}"
      log "started workload guest: ${server_id}"
      ;;
    *) die "workload guest ${server_id} has unexpected state: ${state}" ;;
  esac
done
