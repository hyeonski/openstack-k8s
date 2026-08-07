#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

require_command limactl
instance_running "${CONTROLLER_NAME}" || die "controller is not running"
instance_running "${COMPUTE_NAME}" || die "compute is not running"
[[ -f "${SECRET_DIR}/capi-clouds.yaml" ]] ||
  die "CAPO credentials are missing; run make openstack-bootstrap"

scripts/sync-to-controller.sh
run_dir="$(start_run)"
log_file="${run_dir}/logs/kubernetes-image-verification.log"

log "Booting and validating ${KUBERNETES_IMAGE_NAME}"
set +e
run_on "${CONTROLLER_NAME}" env \
  KOLLA_DEPLOY_DIR="${KOLLA_DEPLOY_DIR}" \
  KUBERNETES_IMAGE_NAME="${KUBERNETES_IMAGE_NAME}" \
  KUBERNETES_VERSION="${KUBERNETES_VERSION}" \
  KUBERNETES_CONTROL_PLANE_FLAVOR="${KUBERNETES_CONTROL_PLANE_FLAVOR}" \
  TENANT_NETWORK_NAME="${TENANT_NETWORK_NAME}" \
  EXTERNAL_NETWORK_NAME="${EXTERNAL_NETWORK_NAME}" \
  bash "${KOLLA_DEPLOY_DIR}/scripts/verify-kubernetes-image-guest.sh" \
  2>&1 | tee "${log_file}"
result="${PIPESTATUS[0]}"
set -e

for name in kubernetes-image-verification.txt kubernetes-image-console.log \
  kubernetes-image-guest-checks.log; do
  remote="${KOLLA_DEPLOY_DIR}/artifacts/${name}"
  if run_on "${CONTROLLER_NAME}" test -f "${remote}"; then
    limactl copy "${CONTROLLER_NAME}:${remote}" "${run_dir}/${name}"
  fi
done

if [[ "${result}" -ne 0 ]]; then
  warn "Kubernetes image verification failed; Nova resources were preserved for diagnosis"
  exit "${result}"
fi

log "Kubernetes ARM64 Glance image and Nova reboot gate passed"
