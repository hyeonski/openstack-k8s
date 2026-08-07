#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

require_command limactl
require_command shasum
instance_exists "${IMAGE_BUILDER_NAME}" ||
  die "image builder is missing; run make kubernetes-image-builder-create"

if instance_running "${CONTROLLER_NAME}" || instance_running "${COMPUTE_NAME}"; then
  die "stop the OpenStack Lima VMs before running the 6 GiB image builder"
fi

if ! instance_running "${IMAGE_BUILDER_NAME}"; then
  log "Starting ${IMAGE_BUILDER_NAME}"
  limactl start "${IMAGE_BUILDER_NAME}"
fi

run_on "${IMAGE_BUILDER_NAME}" test -c /dev/kvm ||
  die "nested KVM is unavailable in ${IMAGE_BUILDER_NAME}"
run_on "${IMAGE_BUILDER_NAME}" sudo usermod -aG kvm "${TARGET_SSH_USER}"
if ! run_on "${IMAGE_BUILDER_NAME}" id -nG | tr ' ' '\n' | grep -Fx kvm >/dev/null; then
  log "Restarting ${IMAGE_BUILDER_NAME} once to activate kvm group membership"
  limactl stop "${IMAGE_BUILDER_NAME}"
  limactl start "${IMAGE_BUILDER_NAME}"
fi
run_on "${IMAGE_BUILDER_NAME}" id -nG | tr ' ' '\n' | grep -Fx kvm >/dev/null ||
  die "${TARGET_SSH_USER} did not receive access to /dev/kvm"
run_on "${IMAGE_BUILDER_NAME}" sudo chown "${TARGET_SSH_USER}:kvm" \
  /var/lib/libvirt/images/capi.fd \
  /var/lib/libvirt/images/capi-nvmram.fd
run_on "${IMAGE_BUILDER_NAME}" sudo chmod 0660 \
  /var/lib/libvirt/images/capi.fd \
  /var/lib/libvirt/images/capi-nvmram.fd

ensure_state_dirs
image_dir="${STATE_DIR}/images"
mkdir_private "${image_dir}"
run_dir="$(start_run)"
log_file="${run_dir}/logs/kubernetes-image-build.log"

remote_input="/tmp/openstack-k8s-image-inputs"
remote_result="/home/${TARGET_SSH_USER}/kubernetes-image-output"
run_on "${IMAGE_BUILDER_NAME}" rm -rf "${remote_input}"
run_on "${IMAGE_BUILDER_NAME}" install -d -m 0700 "${remote_input}"
limactl copy \
  "${PROJECT_ROOT}/scripts/configure-image-builder-arm64.py" \
  "${PROJECT_ROOT}/scripts/run-kubernetes-image-build.sh" \
  "${PROJECT_ROOT}/kubernetes/image-builder-variables.json" \
  "${IMAGE_BUILDER_NAME}:${remote_input}/"

log "Building ${KUBERNETES_IMAGE_NAME} with ${IMAGE_BUILDER_VERSION}"
set +e
run_on "${IMAGE_BUILDER_NAME}" env \
  IMAGE_BUILDER_VERSION="${IMAGE_BUILDER_VERSION}" \
  IMAGE_BUILDER_COMMIT="${IMAGE_BUILDER_COMMIT}" \
  KUBERNETES_VERSION="${KUBERNETES_VERSION}" \
  KUBERNETES_IMAGE_NAME="${KUBERNETES_IMAGE_NAME}" \
  BUILD_INPUT_DIR="${remote_input}" \
  RESULT_DIR="${remote_result}" \
  PACKER_LOG="${PACKER_LOG:-0}" \
  bash "${remote_input}/run-kubernetes-image-build.sh" \
  2>&1 | tee "${log_file}"
result="${PIPESTATUS[0]}"
set -e
if [[ "${result}" -ne 0 ]]; then
  warn "Kubernetes image build failed; the builder VM and build tree were preserved"
  exit "${result}"
fi

artifact_name="${KUBERNETES_IMAGE_NAME}.qcow2"
for suffix in "" .sha256 .info.json .build.txt; do
  limactl copy \
    "${IMAGE_BUILDER_NAME}:${remote_result}/${artifact_name}${suffix}" \
    "${image_dir}/${artifact_name}${suffix}.tmp"
  mv "${image_dir}/${artifact_name}${suffix}.tmp" \
    "${image_dir}/${artifact_name}${suffix}"
done

(
  cd "${image_dir}"
  shasum -a 256 -c "${artifact_name}.sha256"
)
chmod 0600 "${image_dir}/${artifact_name}"*
cp "${image_dir}/${artifact_name}.sha256" "${run_dir}/kubernetes-image.sha256"
cp "${image_dir}/${artifact_name}.build.txt" "${run_dir}/kubernetes-image-build.txt"

log "Verified image stored at ${image_dir}/${artifact_name}"
