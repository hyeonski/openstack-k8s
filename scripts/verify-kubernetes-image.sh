#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

require_command gcloud
instance_running "${CONTROLLER_NAME}" || die "controller is not running"
for compute_name in "${COMPUTE_NAMES[@]}"; do
  instance_running "${compute_name}" || die "${compute_name} is not running"
done
[[ -f "${SECRET_DIR}/capi-clouds.yaml" ]] ||
  die "CAPO credentials are missing; run make openstack-bootstrap"

run_dir="$(start_run)"
sync_log="${run_dir}/logs/sync-to-controller.log"
log_file="${run_dir}/logs/kubernetes-image-verification.log"

set +e
scripts/sync-to-controller.sh 2>&1 | tee "${sync_log}"
sync_result="${PIPESTATUS[0]}"
set -e
if [[ "${sync_result}" -ne 0 ]]; then
  warn "Controller synchronization failed; logs were preserved at ${sync_log}"
  exit "${sync_result}"
fi

log "Booting and validating ${KUBERNETES_IMAGE_NAME}"
set +e
run_on "${CONTROLLER_NAME}" env \
  KOLLA_DEPLOY_DIR="${KOLLA_DEPLOY_DIR}" \
  KUBERNETES_IMAGE_NAME="${KUBERNETES_IMAGE_NAME}" \
  KUBERNETES_VERSION="${KUBERNETES_VERSION}" \
  ARCHITECTURE="${ARCHITECTURE}" \
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
    copy_from "${CONTROLLER_NAME}" "${remote}" "${run_dir}/${name}"
  fi
done

if [[ "${result}" -ne 0 ]]; then
  warn "Kubernetes image verification failed; Nova resources were preserved for diagnosis"
  exit "${result}"
fi

log "Kubernetes ${ARCHITECTURE} Glance image and Nova reboot gate passed"
