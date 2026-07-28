#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

confirmation="${1:-}"
[[ "${confirmation}" == "${ENV}" ]] ||
  die "refusing deletion; run with CONFIRM=${ENV}"

require_command limactl

if instance_running "${CONTROLLER_NAME}"; then
  scripts/manage-route.sh delete
fi

targets=()
instance_exists "${CONTROLLER_NAME}" && targets+=("${CONTROLLER_NAME}")
instance_exists "${COMPUTE_NAME}" && targets+=("${COMPUTE_NAME}")

if [[ "${#targets[@]}" -eq 0 ]]; then
  log "No project Lima instances to delete"
  exit 0
fi

printf 'Deleting only these Lima instances:\n'
printf '  %s\n' "${targets[@]}"
limactl delete --force "${targets[@]}"
log "Secrets, artifacts, socket_vmnet and existing non-project VMs were preserved"

