#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

[[ "${HOST_PROVIDER}" == "gcp" ]] ||
  die "GCP OpenStack recovery requires a GCP profile"
instance_running "${CONTROLLER_NAME}" || die "controller is not running"

if ! run_on "${CONTROLLER_NAME}" test -s /etc/kolla/clouds.yaml; then
  log "OpenStack is not deployed yet; runtime recovery is not required"
  exit 0
fi

remote_script="/tmp/verify-gcp-openstack-runtime.sh"
cleanup() {
  run_on "${CONTROLLER_NAME}" rm -f "${remote_script}" >/dev/null 2>&1 || true
}
trap cleanup EXIT
copy_to "${PROJECT_ROOT}/scripts/verify-gcp-openstack-runtime.sh" \
  "${CONTROLLER_NAME}" "${remote_script}"
run_on "${CONTROLLER_NAME}" sudo env \
  KOLLA_INTERNAL_VIP_ADDRESS="${KOLLA_INTERNAL_VIP_ADDRESS}" \
  EXPECTED_COMPUTE_COUNT="${#COMPUTE_NAMES[@]}" \
  bash "${remote_script}"
cleanup
trap - EXIT
