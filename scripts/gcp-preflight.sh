#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

action="${1:-foundation}"

require_gcp_context() {
  require_command gcloud
  active_account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -n 1)"
  [[ -n "${active_account}" ]] || die "gcloud has no active account"
  gcloud projects describe "${GCP_PROJECT_ID}" --format='value(projectId)' |
    grep -qx "${GCP_PROJECT_ID}" || die "GCP project is unavailable: ${GCP_PROJECT_ID}"
}

bootstrap_preflight() {
  require_command python3
  require_command rsync
  require_command ssh-keygen
  require_command tar
  require_command curl
  require_command kubectl
  require_gcp_context

  local iac_engine kubectl_version
  iac_engine="$(select_iac_engine)"
  kubectl_version="$(
    kubectl version --client -o json |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["clientVersion"]["gitVersion"])'
  )"
  log "Bootstrap client: ${iac_engine}, kubectl ${kubectl_version}"
  log "GCP account/project: ${active_account}/${GCP_PROJECT_ID}"
  log "Bootstrap preflight passed without requiring existing VPCs or VMs"
}

foundation_preflight() {
  require_command python3
  require_command rsync
  require_command ssh-keygen
  require_command tar
  require_gcp_context

  [[ "${#COMPUTE_NAMES[@]}" -eq "${#COMPUTE_MANAGEMENT_IPS[@]}" ]] ||
    die "compute instance and IP counts differ"
  [[ "${#COMPUTE_NAMES[@]}" -eq "${#COMPUTE_INVENTORY_NAMES[@]}" ]] ||
    die "compute instance and inventory counts differ"

  for name in "${CONTROLLER_NAME}" "${COMPUTE_NAMES[@]}"; do
    instance_exists "${name}" || die "GCE instance is missing: ${name}"
    log "${name}: $(instance_status "${name}")"
  done

  gcloud compute networks describe "${GCP_NETWORK_NAME}" \
    --project="${GCP_PROJECT_ID}" --format='value(name)' |
    grep -qx "${GCP_NETWORK_NAME}" || die "management VPC is unavailable"
  gcloud compute networks subnets describe "${GCP_SUBNETWORK_NAME}" \
    --project="${GCP_PROJECT_ID}" --region="${GCP_REGION}" \
    --format='value(ipCidrRange)' | grep -qx "${MANAGEMENT_CIDR}" ||
    die "management subnet CIDR does not match ${MANAGEMENT_CIDR}"

  log "GCP account: ${active_account}"
  log "GCP project/zone: ${GCP_PROJECT_ID}/${GCP_ZONE}"
  log "Management interface/CIDR: ${MANAGEMENT_INTERFACE}/${MANAGEMENT_CIDR}"
  log "Automatic STOP contract: 36000 seconds (declared in infra/gcp)"
}

case "${action}" in
  bootstrap) bootstrap_preflight ;;
  foundation) foundation_preflight ;;
  *) die "usage: gcp-preflight.sh {bootstrap|foundation}" ;;
esac
