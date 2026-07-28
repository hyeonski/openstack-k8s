#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

require_command curl
require_command docker
[[ -f "${SECRET_DIR}/capi-clouds.yaml" ]] ||
  die "CAPO credentials are missing; run make openstack-bootstrap"
export DOCKER_CONFIG="${PROJECT_ROOT}/config/docker-anonymous"
docker info >/dev/null 2>&1 ||
  die "Docker is required and must be running for the strict CAPO network probe"

run_dir="$(current_or_new_run)"
log_file="${run_dir}/logs/openstack-verification.log"
scripts/manage-route.sh add

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
limactl copy "${CONTROLLER_NAME}:${temporary}" \
  "${GENERATED_DIR}/verification.env"
run_on "${CONTROLLER_NAME}" rm -f "${temporary}"
chmod 600 "${GENERATED_DIR}/verification.env"
# shellcheck disable=SC1090
source "${GENERATED_DIR}/verification.env"

log "Checking the OpenStack API and workload API path from macOS"
curl --fail --silent --show-error --connect-timeout 10 \
  "http://${KOLLA_INTERNAL_VIP_ADDRESS}:5000/v3" >/dev/null
curl --fail --silent --show-error --connect-timeout 10 \
  "http://${UBUNTU_TEST_FLOATING_IP}:${PROBE_API_PORT}/" >/dev/null

log "Checking both paths from an isolated Docker bridge container"
docker run --rm --network bridge curlimages/curl:8.12.1 \
  --fail --silent --show-error --connect-timeout 10 \
  "http://${KOLLA_INTERNAL_VIP_ADDRESS}:5000/v3" >/dev/null
docker run --rm --network bridge curlimages/curl:8.12.1 \
  --fail --silent --show-error --connect-timeout 10 \
  "http://${UBUNTU_TEST_FLOATING_IP}:${PROBE_API_PORT}/" >/dev/null

{
  echo "openstack_api_from_host=pass"
  echo "openstack_api_from_docker_bridge=pass"
  echo "floating_ip_6443_from_host=pass"
  echo "floating_ip_6443_from_docker_bridge=pass"
} > "${run_dir}/capo-network-preflight.txt"

if [[ "${KEEP_TEST_RESOURCES:-NO}" == "YES" ]]; then
  log "KEEP_TEST_RESOURCES=YES; Ubuntu verification server was preserved"
else
  run_on "${CONTROLLER_NAME}" env \
    KOLLA_DEPLOY_DIR="${KOLLA_DEPLOY_DIR}" \
    bash "${KOLLA_DEPLOY_DIR}/scripts/cleanup-openstack-verification.sh"
  rm -f "${GENERATED_DIR}/verification.env"
fi

log "OpenStack and strict CAPO network preflight passed"
