#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

require_command limactl
require_command python3
ensure_state_dirs

[[ -x /opt/socket_vmnet/bin/socket_vmnet ]] ||
  die "socket_vmnet is missing; run make host-setup"
[[ -f /private/etc/sudoers.d/lima ]] ||
  die "Lima sudoers is missing; run make host-setup"

lima_network_exists "${LIMA_NETWORK_NAME}" ||
  die "project Lima network is missing; run make host-setup"

export CONTROLLER_CPUS CONTROLLER_MEMORY_GIB CONTROLLER_DISK_GIB
export COMPUTE_CPUS COMPUTE_MEMORY_GIB COMPUTE_DISK_GIB
export LIMA_NETWORK_NAME LIMA_MANAGEMENT_INTERFACE TARGET_SSH_USER

controller_yaml="${GENERATED_DIR}/controller.yaml"
compute_yaml="${GENERATED_DIR}/compute.yaml"
"${PROJECT_ROOT}/scripts/render-template.py" \
  "${PROJECT_ROOT}/lima/controller.yaml.tpl" "${controller_yaml}"
"${PROJECT_ROOT}/scripts/render-template.py" \
  "${PROJECT_ROOT}/lima/compute.yaml.tpl" "${compute_yaml}"

if ! instance_exists "${CONTROLLER_NAME}"; then
  log "Creating ${CONTROLLER_NAME}"
  limactl create --tty=false --name "${CONTROLLER_NAME}" "${controller_yaml}"
else
  log "${CONTROLLER_NAME} already exists"
fi

if ! instance_exists "${COMPUTE_NAME}"; then
  log "Creating ${COMPUTE_NAME}"
  limactl create --tty=false --name "${COMPUTE_NAME}" "${compute_yaml}"
else
  log "${COMPUTE_NAME} already exists"
fi

log "Lima instances created. Run 'make local-up ENV=${ENV}'."
