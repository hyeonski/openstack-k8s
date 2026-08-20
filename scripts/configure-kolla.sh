#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

[[ "$#" -le 1 ]] || die "usage: configure-kolla.sh [--base-images]"
render_base_images="false"
if [[ "${1:-}" == "--base-images" ]]; then
  render_base_images="true"
elif [[ "$#" -eq 1 ]]; then
  die "unsupported argument: $1"
fi

instance_running "${CONTROLLER_NAME}" || die "controller is not running"
[[ -f "${GENERATED_DIR}/addresses.env" ]] ||
  die "addresses are missing; run make inventory"

# shellcheck disable=SC1090
source "${GENERATED_DIR}/addresses.env"

nova_libvirt_image="${KOLLA_NOVA_LIBVIRT_IMAGE:-}"
nova_libvirt_tag="${KOLLA_NOVA_LIBVIRT_TAG:-}"
if [[ "${render_base_images}" == "true" &&
      "${KOLLA_BUILD_NOVA_LIBVIRT_OVERRIDE}" == "yes" ]]; then
  # Preserve Jinja expressions in globals.yml so Kolla resolves its normal
  # registry and release tag. This keeps `kolla-ansible pull` independent of
  # the locally built derivative image.
  nova_libvirt_image='{{ docker_image_url }}nova-libvirt'
  nova_libvirt_tag='{{ openstack_tag }}'
fi

run_on "${CONTROLLER_NAME}" env \
  KOLLA_BASE_DISTRO="${KOLLA_BASE_DISTRO}" \
  KOLLA_SERIES="${KOLLA_SERIES}" \
  KOLLA_OPENSTACK_TAG_SUFFIX="${KOLLA_OPENSTACK_TAG_SUFFIX}" \
  KOLLA_NOVA_LIBVIRT_IMAGE="${nova_libvirt_image}" \
  KOLLA_NOVA_LIBVIRT_TAG="${nova_libvirt_tag}" \
  KOLLA_GLOBALS_TEMPLATE="${KOLLA_GLOBALS_TEMPLATE}" \
  MANAGEMENT_INTERFACE="${MANAGEMENT_INTERFACE}" \
  KOLLA_INTERNAL_VIP_ADDRESS="${KOLLA_INTERNAL_VIP_ADDRESS}" \
  EXTERNAL_INTERFACE="${EXTERNAL_INTERFACE}" \
  COMPUTE_MANAGEMENT_IP="${COMPUTE_MANAGEMENT_IP}" \
  COMPUTE_INVENTORY_SPECS="${COMPUTE_INVENTORY_SPECS}" \
  TARGET_SSH_USER="${TARGET_SSH_USER}" \
  KOLLA_VENV="${KOLLA_VENV}" \
  KOLLA_CONFIG_DIR="${KOLLA_CONFIG_DIR}" \
  KOLLA_DEPLOY_DIR="${KOLLA_DEPLOY_DIR}" \
  bash -lc '
    set -Eeuo pipefail
    sample="$(find "${KOLLA_VENV}/share/kolla-ansible" \
      -type f -path "*/inventory/multinode" -print -quit)"
    [[ -n "${sample}" ]] || {
      echo "Kolla multinode sample inventory not found" >&2
      exit 1
    }

    "${KOLLA_DEPLOY_DIR}/scripts/render-template.py" \
      "${KOLLA_DEPLOY_DIR}/kolla/${KOLLA_GLOBALS_TEMPLATE}" \
      "${KOLLA_CONFIG_DIR}/globals.yml"
    chmod 600 "${KOLLA_CONFIG_DIR}/globals.yml"

    compute_args=()
    for compute_spec in ${COMPUTE_INVENTORY_SPECS}; do
      compute_args+=(--compute "${compute_spec}")
    done
    "${KOLLA_DEPLOY_DIR}/scripts/build-kolla-inventory.py" \
      "${sample}" "${KOLLA_DEPLOY_DIR}/kolla/generated/multinode" \
      "${compute_args[@]}" --user "${TARGET_SSH_USER}"

    if [[ ! -s "${KOLLA_CONFIG_DIR}/passwords.yml" ]]; then
      sample_passwords="$(find "${KOLLA_VENV}/share/kolla-ansible" \
        -type f -name passwords.yml -print -quit)"
      [[ -n "${sample_passwords}" ]] || {
        echo "Kolla sample passwords.yml not found" >&2
        exit 1
      }
      install -m 600 "${sample_passwords}" \
        "${KOLLA_CONFIG_DIR}/passwords.yml"
      "${KOLLA_VENV}/bin/kolla-genpwd" \
        -p "${KOLLA_CONFIG_DIR}/passwords.yml"
    fi
  '

log "Kolla configuration rendered on controller"
