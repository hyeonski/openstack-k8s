#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

if [[ "${HOST_PROVIDER}" == "gcp" ]]; then
  exec "${PROJECT_ROOT}/scripts/gcp-image-builder.sh" create
fi

require_command limactl
require_command python3
ensure_state_dirs

[[ "${ARCHITECTURE}" == "aarch64" ]] ||
  die "the local image-builder profile currently supports only aarch64"

if instance_running "${CONTROLLER_NAME}" || instance_running "${COMPUTE_NAME}"; then
  die "stop the OpenStack Lima VMs before running the 6 GiB image builder"
fi

export IMAGE_BUILDER_CPUS IMAGE_BUILDER_MEMORY_GIB IMAGE_BUILDER_DISK_GIB
export TARGET_SSH_USER
builder_yaml="${GENERATED_DIR}/image-builder.yaml"
"${PROJECT_ROOT}/scripts/render-template.py" \
  "${PROJECT_ROOT}/lima/image-builder.yaml.tpl" "${builder_yaml}"

if ! instance_exists "${IMAGE_BUILDER_NAME}"; then
  log "Creating isolated image builder ${IMAGE_BUILDER_NAME}"
  limactl create --tty=false --name "${IMAGE_BUILDER_NAME}" "${builder_yaml}"
else
  log "${IMAGE_BUILDER_NAME} already exists"
fi

log "Image builder created. Run 'make kubernetes-image-build ENV=${ENV}'."
