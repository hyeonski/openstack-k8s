#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

if [[ "${HOST_PROVIDER}" == "gcp" ]]; then
  require_command gcloud
else
  require_command limactl
fi
require_command shasum
instance_running "${CONTROLLER_NAME}" || die "controller is not running"
[[ -f "${SECRET_DIR}/capi-clouds.yaml" ]] ||
  die "CAPO credentials are missing; run make openstack-bootstrap"

image_dir="${STATE_DIR}/images"
artifact_name="${KUBERNETES_IMAGE_NAME}.qcow2"
image_path="${image_dir}/${artifact_name}"
checksum_path="${image_path}.sha256"
[[ -s "${image_path}" && -s "${checksum_path}" ]] ||
  die "built Kubernetes image is missing; run make kubernetes-image-build"
(
  cd "${image_dir}"
  shasum -a 256 -c "${artifact_name}.sha256"
)
expected_sha256="$(awk '{print $1}' "${checksum_path}")"

remote_image="/tmp/${artifact_name}"
log "Copying the verified Kubernetes image to the controller"
copy_to "${image_path}" "${CONTROLLER_NAME}" "${remote_image}"

set +e
run_on "${CONTROLLER_NAME}" env \
  KUBERNETES_IMAGE_NAME="${KUBERNETES_IMAGE_NAME}" \
  KUBERNETES_VERSION="${KUBERNETES_VERSION}" \
  KUBERNETES_IMAGE_OS_VERSION="${KUBERNETES_IMAGE_OS_VERSION}" \
  IMAGE_BUILDER_VERSION="${IMAGE_BUILDER_VERSION}" \
  KUBERNETES_IMAGE_SHA256="${expected_sha256}" \
  REMOTE_IMAGE="${remote_image}" \
  bash -lc '
    set -Eeuo pipefail
    source /opt/kolla-venv/bin/activate
    export OS_CLIENT_CONFIG_FILE=/etc/kolla/capi-clouds.yaml
    export OS_CLOUD=capi

    if openstack image show "${KUBERNETES_IMAGE_NAME}" >/dev/null 2>&1; then
      actual="$(openstack image show "${KUBERNETES_IMAGE_NAME}" -f json |
        jq -r ".properties.kubernetes_image_sha256 // empty")"
      status="$(openstack image show "${KUBERNETES_IMAGE_NAME}" -f value -c status)"
      [[ "${actual}" == "${KUBERNETES_IMAGE_SHA256}" && "${status}" == "active" ]] || {
        echo "existing versioned Glance image does not match the local checksum" >&2
        exit 1
      }
      echo "Matching Glance image already exists"
      exit 0
    fi

    openstack image create \
      --private \
      --disk-format qcow2 \
      --container-format bare \
      --property hw_architecture=aarch64 \
      --property hw_firmware_type=uefi \
      --property os_distro=ubuntu \
      --property os_version="${KUBERNETES_IMAGE_OS_VERSION}" \
      --property kubernetes_version="${KUBERNETES_VERSION}" \
      --property image_builder_version="${IMAGE_BUILDER_VERSION}" \
      --property kubernetes_image_sha256="${KUBERNETES_IMAGE_SHA256}" \
      --file "${REMOTE_IMAGE}" \
      "${KUBERNETES_IMAGE_NAME}"

    [[ "$(openstack image show "${KUBERNETES_IMAGE_NAME}" -f value -c status)" == "active" ]]
  '
result="$?"
set -e
run_on "${CONTROLLER_NAME}" rm -f "${remote_image}"
[[ "${result}" -eq 0 ]] || die "Glance image upload failed"

log "Glance image ${KUBERNETES_IMAGE_NAME} is active and checksum-labelled"
