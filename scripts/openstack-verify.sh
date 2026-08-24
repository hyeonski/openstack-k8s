#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

[[ -f "${SECRET_DIR}/capi-clouds.yaml" ]] ||
  die "CAPO credentials are missing; run make openstack-bootstrap"

require_command gcloud
route_name="${GCP_OPENSTACK_FLOATING_IP_ROUTE_NAME:?}"
route_destination="$(
  gcloud compute routes describe "${route_name}" \
    --project="${GCP_PROJECT_ID}" \
    --format='value(destRange)' 2>/dev/null || true
)"
route_next_hop="$(
  gcloud compute routes describe "${route_name}" \
    --project="${GCP_PROJECT_ID}" \
    --format='value(nextHopInstance)' 2>/dev/null || true
)"
[[ "${route_destination}" == "${EXTERNAL_CIDR}" ]] ||
  die "GCP Floating IP route is missing or has the wrong destination"
[[ "${route_next_hop##*/}" == "${CONTROLLER_NAME}" ]] ||
  die "GCP Floating IP route does not use the controller as next hop"

run_dir="$(current_or_new_run)"
log_file="${run_dir}/logs/openstack-verification.log"

log "Running OpenStack control-plane and guest verification"
set +e
run_on "${CONTROLLER_NAME}" env \
  KOLLA_DEPLOY_DIR="${KOLLA_DEPLOY_DIR}" \
  OPENSTACK_TEST_FLAVOR="${OPENSTACK_TEST_FLAVOR}" \
  CIRROS_IMAGE_NAME="${CIRROS_IMAGE_NAME}" \
  UBUNTU_IMAGE_NAME="${UBUNTU_IMAGE_NAME}" \
  TENANT_NETWORK_NAME="${TENANT_NETWORK_NAME}" \
  EXTERNAL_NETWORK_NAME="${EXTERNAL_NETWORK_NAME}" \
  bash "${KOLLA_DEPLOY_DIR}/scripts/verify-openstack-guests.sh" \
  2>&1 | tee "${log_file}"
result="${PIPESTATUS[0]}"
set -e
if [[ "${result}" -ne 0 ]]; then
  warn "Guest verification failed; resources were preserved for diagnosis"
  exit "${result}"
fi

remote_state="${KOLLA_DEPLOY_DIR}/artifacts/verification.env"
temporary="/tmp/openstack-k8s-verification.env"
run_on "${CONTROLLER_NAME}" install -m 0600 "${remote_state}" "${temporary}"
copy_from "${CONTROLLER_NAME}" "${temporary}" \
  "${GENERATED_DIR}/verification.env"
run_on "${CONTROLLER_NAME}" rm -f "${temporary}"
chmod 600 "${GENERATED_DIR}/verification.env"
# shellcheck disable=SC1090
source "${GENERATED_DIR}/verification.env"

probe_results=()
for compute_name in "${COMPUTE_NAMES[@]}"; do
  # Kolla deliberately configures compute Docker with bridge=none and
  # iptables=false. Each compute host is an independent GCP VPC consumer;
  # the management cluster runs its own container-path gate.
  log "Checking both API paths from GCP VPC host ${compute_name}"
  run_on "${compute_name}" curl \
    --fail --silent --show-error --connect-timeout 10 \
    "http://${KOLLA_INTERNAL_VIP_ADDRESS}:5000/v3" >/dev/null
  run_on "${compute_name}" curl \
    --fail --silent --show-error --connect-timeout 10 \
    "http://${UBUNTU_TEST_FLOATING_IP}:${PROBE_API_PORT}/" >/dev/null
  probe_results+=(
    "openstack_api_from_${compute_name}=pass"
    "floating_ip_6443_from_${compute_name}=pass"
  )
done
printf '%s\n' "${probe_results[@]}" > "${run_dir}/capo-network-preflight.txt"

if [[ "${KEEP_TEST_RESOURCES:-NO}" == "YES" ]]; then
  log "KEEP_TEST_RESOURCES=YES; Ubuntu verification server was preserved"
else
  run_on "${CONTROLLER_NAME}" env \
    KOLLA_DEPLOY_DIR="${KOLLA_DEPLOY_DIR}" \
    bash "${KOLLA_DEPLOY_DIR}/scripts/cleanup-openstack-verification.sh"
  rm -f "${GENERATED_DIR}/verification.env"
fi

log "OpenStack guest and GCP VPC network preflight passed"
