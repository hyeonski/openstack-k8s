#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

require_command limactl
instance_exists "${CONTROLLER_NAME}" || die "run make local-create first"
instance_exists "${COMPUTE_NAME}" || die "run make local-create first"

for node in "${CONTROLLER_NAME}" "${COMPUTE_NAME}"; do
  if instance_running "${node}"; then
    log "${node} already running"
  else
    log "Starting ${node}"
    limactl start --tty=false "${node}"
  fi
done

scripts/setup-project-ssh.sh

controller_ip="$(controller_ipv4)"
compute_ip="$(compute_ipv4)"
for assigned_ip in "${controller_ip}" "${compute_ip}"; do
  [[ "${assigned_ip}" != "${KOLLA_INTERNAL_VIP_ADDRESS}" ]] ||
    die "Lima DHCP assigned the reserved Kolla VIP ${KOLLA_INTERNAL_VIP_ADDRESS}; choose another VIP"
done

scripts/generate-inventory.sh
scripts/local-health.sh
log "Local environment is running: controller=${controller_ip}, compute=${compute_ip}"
