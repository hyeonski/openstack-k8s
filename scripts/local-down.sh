#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

require_command limactl

if instance_running "${CONTROLLER_NAME}"; then
  scripts/manage-route.sh delete
fi

for node in "${COMPUTE_NAME}" "${CONTROLLER_NAME}"; do
  if instance_running "${node}"; then
    log "Stopping ${node}"
    limactl stop "${node}"
  else
    log "${node} is already stopped or absent"
  fi
done

