#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

confirmation="${1:-}"
[[ "${confirmation}" == "${ENV}" ]] ||
  die "refusing deletion; run with CONFIRM=${ENV}"

require_command limactl

if ! instance_exists "${IMAGE_BUILDER_NAME}"; then
  log "No image-builder Lima instance to delete"
  exit 0
fi

printf 'Deleting only this Lima instance:\n  %s\n' "${IMAGE_BUILDER_NAME}"
limactl delete --force "${IMAGE_BUILDER_NAME}"
log "Built QCOW2 files, checksums, OpenStack VMs and all other Lima instances were preserved"
