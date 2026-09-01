#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

action="${1:-}"
foundation_plan="${STATE_DIR}/gcp-foundation.tfplan"
route_plan="${STATE_DIR}/gcp-floating-ip-route.tfplan"
adoption_plan="${STATE_DIR}/gcp-adoption.tfplan"
controller_management_plan="${STATE_DIR}/gcp-controller-management.tfplan"

require_confirmation() {
  local confirmation="${1:-}"
  [[ "${confirmation}" == "${ENV}" ]] ||
    die "refusing infrastructure apply; pass CONFIRM=${ENV}"
}

plan_with_status() {
  local plan_file="$1"
  shift
  local status
  ensure_private_directory "$(dirname "${IAC_STATE_FILE}")"
  set +e
  run_gcp_iac plan -input=false -detailed-exitcode \
    -state="${IAC_STATE_FILE}" "$@" -out="${plan_file}"
  status=$?
  set -e
  case "${status}" in
    0) log "Plan is empty: infrastructure already matches the requested stage" ;;
    2) return 2 ;;
    *) return "${status}" ;;
  esac
}

validate_saved_plan() {
  local plan_file="$1"
  local validator="$2"
  run_gcp_iac show -json "${plan_file}" |
    python3 "${PROJECT_ROOT}/scripts/${validator}"
}

import_if_missing() {
  local address="$1"
  local resource_id="$2"
  if run_gcp_iac state show -state="${IAC_STATE_FILE}" "${address}" >/dev/null 2>&1; then
    log "Already imported: ${address}"
    return
  fi
  log "Importing existing resource: ${address}"
  run_gcp_iac import -input=false -state="${IAC_STATE_FILE}" \
    "${address}" "${resource_id}"
}

case "${action}" in
  init)
    run_gcp_iac init -input=false
    ;;
  validate)
    run_gcp_iac validate
    ;;
  import)
    ensure_state_dirs
    ensure_private_directory "$(dirname "${IAC_STATE_FILE}")"
    require_command gcloud
    run_gcp_iac init -input=false
    import_if_missing google_compute_network.management \
      "projects/${GCP_PROJECT_ID}/global/networks/${GCP_NETWORK_NAME}"
    import_if_missing google_compute_subnetwork.seoul \
      "projects/${GCP_PROJECT_ID}/regions/${GCP_REGION}/subnetworks/${GCP_SUBNETWORK_NAME}"
    import_if_missing google_compute_firewall.iap_ssh \
      "projects/${GCP_PROJECT_ID}/global/firewalls/osk8s-allow-iap-ssh"
    import_if_missing google_compute_firewall.internal \
      "projects/${GCP_PROJECT_ID}/global/firewalls/osk8s-allow-internal"
    if gcloud compute firewall-rules describe osk8s-allow-iap-management-api \
        --project="${GCP_PROJECT_ID}" >/dev/null 2>&1; then
      import_if_missing 'google_compute_firewall.iap_management_api[0]' \
        "projects/${GCP_PROJECT_ID}/global/firewalls/osk8s-allow-iap-management-api"
    fi

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
    if gcloud compute routes describe "${GCP_OPENSTACK_FLOATING_IP_ROUTE_NAME}" \
        --project="${GCP_PROJECT_ID}" >/dev/null 2>&1; then
      import_if_missing 'google_compute_route.openstack_floating_ips[0]' \
        "projects/${GCP_PROJECT_ID}/global/routes/${GCP_OPENSTACK_FLOATING_IP_ROUTE_NAME}"
    fi
    ;;
  plan)
    ensure_state_dirs
    ensure_private_directory "$(dirname "${IAC_STATE_FILE}")"
    set +e
    run_gcp_iac plan -input=false -detailed-exitcode \
      -state="${IAC_STATE_FILE}" \
      -out="${adoption_plan}"
    plan_status=$?
    set -e
    case "${plan_status}" in
      0) log "Adoption plan is empty: existing GCP state matches the declaration" ;;
      2) log "Adoption plan contains differences; inspect with make gcp-iac-show-plan" ;;
      *) exit "${plan_status}" ;;
    esac
    ;;
  show-plan)
    [[ -f "${adoption_plan}" ]] || die "run gcp-iac plan first"
    run_gcp_iac show "${adoption_plan}"
    ;;
  foundation-plan)
    ensure_state_dirs
    ensure_deployment_ssh_key
    require_command python3
    if plan_with_status "${foundation_plan}" \
        -var="enable_openstack_floating_ip_route=false" \
        -var="enable_image_builder=false"; then
      validate_saved_plan "${foundation_plan}" validate-foundation-plan.py
    else
      status=$?
      if [[ "${status}" -eq 2 ]]; then
        validate_saved_plan "${foundation_plan}" validate-foundation-plan.py
        log "Validated greenfield foundation plan; inspect it before apply"
      else
        exit "${status}"
      fi
    fi
    ;;
  foundation-show-plan)
    [[ -f "${foundation_plan}" ]] || die "run gcp-iac foundation-plan first"
    run_gcp_iac show "${foundation_plan}"
    ;;
  foundation-apply)
    ensure_deployment_ssh_key
    require_confirmation "${2:-}"
    [[ -f "${foundation_plan}" ]] || die "run gcp-iac foundation-plan first"
    validate_saved_plan "${foundation_plan}" validate-foundation-plan.py
    run_gcp_iac apply -input=false -state="${IAC_STATE_FILE}" \
      -var="enable_openstack_floating_ip_route=false" \
      -var="enable_image_builder=false" \
      "${foundation_plan}"
    ;;
  route-plan)
    ensure_state_dirs
    ensure_deployment_ssh_key
    require_command python3
    if plan_with_status "${route_plan}" \
        -var="enable_openstack_floating_ip_route=true" \
        -var="enable_image_builder=false"; then
      validate_saved_plan "${route_plan}" validate-floating-ip-route-plan.py
    else
      status=$?
      if [[ "${status}" -eq 2 ]]; then
        validate_saved_plan "${route_plan}" validate-floating-ip-route-plan.py
        log "Validated isolated Floating IP route plan"
      else
        exit "${status}"
      fi
    fi
    ;;
  route-show-plan)
    [[ -f "${route_plan}" ]] || die "run gcp-iac route-plan first"
    run_gcp_iac show "${route_plan}"
    ;;
  route-apply)
    ensure_deployment_ssh_key
    require_confirmation "${2:-}"
    [[ -f "${route_plan}" ]] || die "run gcp-iac route-plan first"
    validate_saved_plan "${route_plan}" validate-floating-ip-route-plan.py
    run_gcp_iac apply -input=false -state="${IAC_STATE_FILE}" \
      -var="enable_openstack_floating_ip_route=true" \
      -var="enable_image_builder=false" \
      "${route_plan}"
    ;;
  controller-management)
    ensure_state_dirs
    ensure_deployment_ssh_key
    require_command python3
    set +e
    ensure_private_directory "$(dirname "${IAC_STATE_FILE}")"
    run_gcp_iac plan -input=false -detailed-exitcode \
      -state="${IAC_STATE_FILE}" -out="${controller_management_plan}"
    plan_status="$?"
    set -e
    case "${plan_status}" in
      0)
        log "Controller management network already matches the declaration"
        ;;
      2)
        validate_saved_plan "${controller_management_plan}" \
          validate-controller-management-plan.py
        run_gcp_iac apply -input=false -state="${IAC_STATE_FILE}" \
          "${controller_management_plan}"
        ;;
      *)
        exit "${plan_status}"
        ;;
    esac
    ;;
  foundation-ready)
    expected=(
      'google_compute_address.internal["compute01"]'
      'google_compute_address.internal["compute02"]'
      'google_compute_address.internal["controller"]'
      'google_compute_address.internal["kolla_vip"]'
      google_compute_disk_resource_policy_attachment.controller_snapshots
      'google_compute_firewall.iap_management_api[0]'
      google_compute_firewall.iap_ssh
      google_compute_firewall.internal
      'google_compute_instance.hosts["compute01"]'
      'google_compute_instance.hosts["compute02"]'
      'google_compute_instance.hosts["controller"]'
      google_compute_network.management
      google_compute_resource_policy.daily_snapshots
      google_compute_subnetwork.seoul
    )
    state_list="$(run_gcp_iac state list -state="${IAC_STATE_FILE}" 2>/dev/null || true)"
    for address in "${expected[@]}"; do
      grep -Fxq "${address}" <<<"${state_list}" || exit 1
    done
    log "Persistent GCP foundation is present in OpenTofu state"
    ;;
  *)
    die "usage: gcp-iac.sh {init|validate|import|plan|show-plan|foundation-plan|foundation-show-plan|foundation-apply CONFIRM|foundation-ready|route-plan|route-show-plan|route-apply CONFIRM|controller-management}"
    ;;
esac
