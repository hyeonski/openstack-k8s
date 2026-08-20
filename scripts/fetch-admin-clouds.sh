#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

ensure_state_dirs
instance_running "${CONTROLLER_NAME}" || die "controller is not running"

for remote in \
  "${KOLLA_CONFIG_DIR}/clouds.yaml" \
  "${KOLLA_CONFIG_DIR}/passwords.yml"; do
  filename="$(basename "${remote}")"
  temporary="/tmp/openstack-k8s-${filename}"
  run_on "${CONTROLLER_NAME}" sudo install -o "${TARGET_SSH_USER}" \
    -g "${TARGET_SSH_USER}" -m 0600 "${remote}" "${temporary}"
  copy_from "${CONTROLLER_NAME}" "${temporary}" "${SECRET_DIR}/${filename}"
  run_on "${CONTROLLER_NAME}" rm -f "${temporary}"
  chmod 600 "${SECRET_DIR}/${filename}"
done

log "Admin credentials fetched to ${SECRET_DIR}"
