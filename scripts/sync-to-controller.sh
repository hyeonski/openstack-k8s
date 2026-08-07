#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

require_command rsync
instance_running "${CONTROLLER_NAME}" || die "controller is not running"
instance_running "${COMPUTE_NAME}" || die "compute is not running"
ensure_state_dirs
scripts/sync-guest-clocks.sh

controller_ip="$(controller_ipv4)"
key="${SECRET_DIR}/deployment_ed25519"
[[ -f "${key}" ]] || die "deployment key missing; run make local-up"

run_on "${CONTROLLER_NAME}" sudo install -d \
  -o "${TARGET_SSH_USER}" -g "${TARGET_SSH_USER}" -m 0755 "${KOLLA_DEPLOY_DIR}"

rsync -a --delete \
  --exclude .git \
  --exclude .state \
  --exclude artifacts \
  --exclude generated \
  -e "ssh -i ${key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null" \
  "${PROJECT_ROOT}/ansible" \
  "${PROJECT_ROOT}/config" \
  "${PROJECT_ROOT}/kolla" \
  "${PROJECT_ROOT}/openstack" \
  "${PROJECT_ROOT}/scripts" \
  "${TARGET_SSH_USER}@${controller_ip}:${KOLLA_DEPLOY_DIR}/"

run_on "${CONTROLLER_NAME}" env \
  KOLLA_VENV="${KOLLA_VENV}" \
  KOLLA_GIT_URL="${KOLLA_GIT_URL}" \
  KOLLA_GIT_REF="${KOLLA_GIT_REF}" \
  KOLLA_COLLECTION_GIT_URL="${KOLLA_COLLECTION_GIT_URL}" \
  KOLLA_COLLECTION_GIT_REF="${KOLLA_COLLECTION_GIT_REF}" \
  bash "${KOLLA_DEPLOY_DIR}/scripts/bootstrap-controller.sh"

log "Deployment inputs synchronized to controller"
