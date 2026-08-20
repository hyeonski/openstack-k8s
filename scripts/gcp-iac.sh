#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

[[ "${HOST_PROVIDER}" == "gcp" ]] || die "gcp-iac requires a GCP environment profile"

action="${1:-}"
iac_dir="${PROJECT_ROOT}/infra/gcp"

if [[ -n "${IAC_ENGINE:-}" ]]; then
  engine="${IAC_ENGINE}"
elif command -v tofu >/dev/null 2>&1; then
  engine="tofu"
elif command -v terraform >/dev/null 2>&1; then
  engine="terraform"
else
  die "OpenTofu or Terraform is required"
fi

run_iac() {
  "${engine}" -chdir="${iac_dir}" "$@"
}

import_if_missing() {
  local address="$1"
  local resource_id="$2"
  if run_iac state show "${address}" >/dev/null 2>&1; then
    log "Already imported: ${address}"
    return
  fi
  log "Importing existing resource: ${address}"
  run_iac import -input=false "${address}" "${resource_id}"
}

case "${action}" in
  init)
    run_iac init -input=false
    ;;
  validate)
    run_iac validate
    ;;
  import)
    run_iac init -input=false
    import_if_missing google_compute_network.management \
      "projects/${GCP_PROJECT_ID}/global/networks/${GCP_NETWORK_NAME}"
    import_if_missing google_compute_subnetwork.seoul \
      "projects/${GCP_PROJECT_ID}/regions/${GCP_REGION}/subnetworks/${GCP_SUBNETWORK_NAME}"
    import_if_missing google_compute_firewall.iap_ssh \
      "projects/${GCP_PROJECT_ID}/global/firewalls/osk8s-allow-iap-ssh"
    import_if_missing google_compute_firewall.internal \
      "projects/${GCP_PROJECT_ID}/global/firewalls/osk8s-allow-internal"

    for key in controller compute01 compute02 kolla_vip; do
      if [[ "${key}" == "kolla_vip" ]]; then
        name="osk8s-kolla-vip"
      else
        name="osk8s-${key}-ip"
      fi
      import_if_missing "google_compute_address.internal[\"${key}\"]" \
        "projects/${GCP_PROJECT_ID}/regions/${GCP_REGION}/addresses/${name}"
    done

    for key in controller compute01 compute02; do
      import_if_missing "google_compute_instance.hosts[\"${key}\"]" \
        "projects/${GCP_PROJECT_ID}/zones/${GCP_ZONE}/instances/osk8s-${key}"
    done

    import_if_missing google_compute_resource_policy.daily_snapshots \
      "projects/${GCP_PROJECT_ID}/regions/${GCP_REGION}/resourcePolicies/default-schedule-1"
    import_if_missing google_compute_disk_resource_policy_attachment.controller_snapshots \
      "projects/${GCP_PROJECT_ID}/zones/${GCP_ZONE}/disks/osk8s-controller/default-schedule-1"
    ;;
  plan)
    ensure_state_dirs
    set +e
    run_iac plan -input=false -detailed-exitcode \
      -out="${STATE_DIR}/gcp-adoption.tfplan"
    plan_status=$?
    set -e
    case "${plan_status}" in
      0) log "Adoption plan is empty: existing GCP state matches the declaration" ;;
      2) log "Adoption plan contains differences; inspect with make gcp-iac-show-plan" ;;
      *) exit "${plan_status}" ;;
    esac
    ;;
  show-plan)
    [[ -f "${STATE_DIR}/gcp-adoption.tfplan" ]] || die "run gcp-iac plan first"
    run_iac show "${STATE_DIR}/gcp-adoption.tfplan"
    ;;
  *)
    die "usage: gcp-iac.sh {init|validate|import|plan|show-plan}"
    ;;
esac
