#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

run_on "${CONTROLLER_NAME}" env \
  KOLLA_DEPLOY_DIR="${KOLLA_DEPLOY_DIR}" \
  bash "${KOLLA_DEPLOY_DIR}/scripts/cleanup-openstack-verification.sh"
rm -f "$(safe_realpath_within_project "${GENERATED_DIR}/verification.env")"
log "Local and remote OpenStack verification state was removed"
