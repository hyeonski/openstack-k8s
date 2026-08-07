#!/usr/bin/env bash

set -Eeuo pipefail

IMAGE_BUILDER_VERSION="${IMAGE_BUILDER_VERSION:?}"
IMAGE_BUILDER_COMMIT="${IMAGE_BUILDER_COMMIT:?}"
KUBERNETES_VERSION="${KUBERNETES_VERSION:?}"
KUBERNETES_IMAGE_NAME="${KUBERNETES_IMAGE_NAME:?}"
BUILD_INPUT_DIR="${BUILD_INPUT_DIR:?}"
RESULT_DIR="${RESULT_DIR:?}"

# Image Builder installs Ansible into the invoking user's local bin directory.
# Ubuntu does not add that directory to PATH for this non-login shell.
export PATH="${HOME}/.local/bin:${PATH}"

[[ "$(uname -m)" == "aarch64" ]] || {
  echo "image builder must run natively on aarch64" >&2
  exit 1
}
[[ -c /dev/kvm ]] || {
  echo "nested KVM is unavailable; refusing QEMU TCG fallback" >&2
  exit 1
}

source_root="${HOME}/image-builder-${IMAGE_BUILDER_VERSION}"
if [[ ! -d "${source_root}/.git" ]]; then
  git clone --depth 1 --branch "${IMAGE_BUILDER_VERSION}" \
    https://github.com/kubernetes-sigs/image-builder.git "${source_root}"
fi

actual_commit="$(git -C "${source_root}" rev-parse HEAD)"
[[ "${actual_commit}" == "${IMAGE_BUILDER_COMMIT}" ]] || {
  echo "unexpected Image Builder commit: ${actual_commit}" >&2
  exit 1
}

install -d -m 0700 "${RESULT_DIR}"
result_image="${RESULT_DIR}/${KUBERNETES_IMAGE_NAME}.qcow2"
if [[ -s "${result_image}" && -s "${result_image}.sha256" ]]; then
  (
    cd "${RESULT_DIR}"
    sha256sum --check "$(basename "${result_image}").sha256"
  )
  qemu-img check "${result_image}"
  echo "Verified existing image-builder result: ${result_image}"
  exit 0
fi

capi_root="${source_root}/images/capi"
cd "${capi_root}"
make deps-qemu
# The upstream generator prints every rendered template, including the
# one-time Packer SSH password.  Keep that ephemeral credential out of our
# persisted build log.
make set-ssh-password >/dev/null
python3 "${BUILD_INPUT_DIR}/configure-image-builder-arm64.py" \
  packer/maas/packer-arm64.json

output_dir="${capi_root}/output/ubuntu-2204-arm64-kube-${KUBERNETES_VERSION}"
if [[ -e "${output_dir}" ]]; then
  mv "${output_dir}" "${output_dir}.failed.$(date -u +%Y%m%dT%H%M%SZ)"
fi

common_var_files=(
  packer/config/kubernetes.json
  packer/config/cni.json
  packer/config/containerd.json
  packer/config/wasm-shims.json
  packer/config/ansible-args.json
  packer/config/goss-args.json
  packer/config/common.json
  packer/config/additional_components.json
  packer/config/ecr_credential_provider.json
)
packer_args=()
for var_file in "${common_var_files[@]}"; do
  packer_args+=("-var-file=${capi_root}/${var_file}")
done
packer_args+=("-var-file=${capi_root}/packer/maas/maas-ubuntu-2204-arm64.json")
packer_args+=("-var-file=${BUILD_INPUT_DIR}/image-builder-variables.json")
packer_args+=("-var=ansible_user_vars=provider=openstack")

"${capi_root}/.local/bin/packer" build "${packer_args[@]}" \
  packer/maas/packer-arm64.json

built_image="${output_dir}/ubuntu-2204-arm64-kube-${KUBERNETES_VERSION}"
[[ -s "${built_image}" ]] || {
  echo "Image Builder did not produce ${built_image}" >&2
  exit 1
}

qemu-img convert -p -O qcow2 -c "${built_image}" "${result_image}.tmp"
qemu-img check "${result_image}.tmp"
mv "${result_image}.tmp" "${result_image}"
(
  cd "${RESULT_DIR}"
  sha256sum "$(basename "${result_image}")" > \
    "$(basename "${result_image}").sha256"
)
qemu-img info --output=json "${result_image}" > "${result_image}.info.json"
printf '%s\n' \
  "image_builder_version=${IMAGE_BUILDER_VERSION}" \
  "image_builder_commit=${IMAGE_BUILDER_COMMIT}" \
  "kubernetes_version=${KUBERNETES_VERSION}" \
  "architecture=aarch64" \
  "base_os=ubuntu-22.04" > "${result_image}.build.txt"

echo "Kubernetes ARM64 image built: ${result_image}"
