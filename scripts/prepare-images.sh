#!/usr/bin/env bash

set -Eeuo pipefail

KOLLA_DEPLOY_DIR="${KOLLA_DEPLOY_DIR:?}"
CIRROS_IMAGE_URL="${CIRROS_IMAGE_URL:?}"
CIRROS_SHA256_URL="${CIRROS_SHA256_URL:?}"
UBUNTU_IMAGE_URL="${UBUNTU_IMAGE_URL:?}"
UBUNTU_SHA256_URL="${UBUNTU_SHA256_URL:?}"

cache="${KOLLA_DEPLOY_DIR}/cache/images"
install -d -m 0755 "${cache}"

download_verified() {
  local image_url="$1"
  local sums_url="$2"
  local destination="$3"
  local filename
  local expected
  filename="$(basename "${image_url}")"

  curl --fail --location --retry 4 --retry-all-errors \
    --output "${cache}/SHA256SUMS.tmp" "${sums_url}"
  expected="$(
    awk -v wanted="${filename}" '
      {
        candidate=$2
        sub(/^\*/, "", candidate)
        if (candidate == wanted) {
          print $1
          exit
        }
      }
    ' "${cache}/SHA256SUMS.tmp"
  )"
  [[ "${expected}" =~ ^[0-9a-fA-F]{64}$ ]] || {
    echo "No SHA-256 entry found for ${filename}" >&2
    exit 1
  }

  if [[ ! -f "${destination}" ]] ||
     [[ "$(sha256sum "${destination}" | awk '{print $1}')" != "${expected}" ]]; then
    curl --fail --location --retry 4 --retry-all-errors \
      --output "${destination}.tmp" "${image_url}"
    printf '%s  %s\n' "${expected}" "${destination}.tmp" |
      sha256sum --check -
    mv "${destination}.tmp" "${destination}"
  fi

  printf '%s  %s\n' "${expected}" "$(basename "${destination}")"
}

manifest="${cache}/SHA256.lock"
{
  download_verified \
    "${CIRROS_IMAGE_URL}" "${CIRROS_SHA256_URL}" \
    "${cache}/cirros-aarch64.img"
  download_verified \
    "${UBUNTU_IMAGE_URL}" "${UBUNTU_SHA256_URL}" \
    "${cache}/ubuntu-24.04-arm64.img"
} > "${manifest}.tmp"
mv "${manifest}.tmp" "${manifest}"
chmod 0644 "${cache}"/*.img "${manifest}"

echo "Verified images are ready in ${cache}"
