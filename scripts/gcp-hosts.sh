#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

[[ "${HOST_PROVIDER}" == "gcp" ]] || die "gcp-hosts requires a GCP profile"
require_command gcloud

action="${1:-}"
nodes=("${CONTROLLER_NAME}" "${COMPUTE_NAMES[@]}")

case "${action}" in
  status)
    gcloud compute instances list --project="${GCP_PROJECT_ID}" \
      --filter="zone:(${GCP_ZONE}) AND labels.env=cloud-gcp-amd64" \
      --format='table(name,status,machineType.basename(),networkInterfaces[0].networkIP,scheduling.maxRunDuration.seconds:label=MAX_RUN_SECONDS)'
    ;;
  start)
    targets=()
    for node in "${nodes[@]}"; do
      if ! instance_running "${node}"; then
        targets+=("${node}")
      fi
    done
    if [[ "${#targets[@]}" -eq 0 ]]; then
      log "All GCP hosts are already running"
      exit 0
    fi
    gcloud compute instances start "${targets[@]}" \
      --project="${GCP_PROJECT_ID}" --zone="${GCP_ZONE}" --quiet
    ;;
  stop)
    targets=()
    for node in "${nodes[@]}"; do
      if instance_running "${node}"; then
        targets+=("${node}")
      fi
    done
    if [[ "${#targets[@]}" -eq 0 ]]; then
      log "All GCP hosts are already stopped"
      exit 0
    fi
    gcloud compute instances stop "${targets[@]}" \
      --project="${GCP_PROJECT_ID}" --zone="${GCP_ZONE}" --quiet
    ;;
  verify)
    roles=(controller "${COMPUTE_INVENTORY_NAMES[@]}")
    [[ "${#roles[@]}" -eq "${#nodes[@]}" ]] ||
      die "verify role list and node list differ"
    for ((index = 0; index < ${#nodes[@]}; index++)); do
      instance_running "${nodes[index]}" || die "${nodes[index]} is not running"
      remote_script="/tmp/verify-gcp-host.sh"
      copy_to "${PROJECT_ROOT}/scripts/verify-gcp-host.sh" \
        "${nodes[index]}" "${remote_script}"
      run_on "${nodes[index]}" sudo bash "${remote_script}" \
        "${roles[index]}" \
        "${EXTERNAL_INTERFACE}" \
        "${EXTERNAL_GATEWAY_INTERFACE}" \
        "${EXTERNAL_GATEWAY}/${EXTERNAL_CIDR#*/}"
      run_on "${nodes[index]}" rm -f "${remote_script}"
    done
    ;;
  *)
    die "usage: gcp-hosts.sh {status|start|stop|verify}"
    ;;
esac
