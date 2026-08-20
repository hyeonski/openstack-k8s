#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

if [[ "${KOLLA_BUILD_NOVA_LIBVIRT_OVERRIDE}" != "yes" ]]; then
  log "No nova-libvirt override is required for ${ENV}; using official Kolla images"
  exit 0
fi

instance_running "${COMPUTE_NAME}" || die "compute is not running"
require_command limactl

dockerfile="${PROJECT_ROOT}/kolla/images/nova-libvirt/Dockerfile"
[[ -f "${dockerfile}" ]] || die "missing Dockerfile: ${dockerfile}"

remote_dockerfile="/tmp/openstack-k8s-nova-libvirt.Dockerfile"
final_image="${KOLLA_NOVA_LIBVIRT_IMAGE}:${KOLLA_NOVA_LIBVIRT_TAG}"

limactl copy "${dockerfile}" "${COMPUTE_NAME}:${remote_dockerfile}"
run_on "${COMPUTE_NAME}" sudo docker build \
  --network host \
  --build-arg "BASE_IMAGE=${KOLLA_NOVA_LIBVIRT_BASE_IMAGE}" \
  --label "org.openstack-k8s.base-image=${KOLLA_NOVA_LIBVIRT_BASE_IMAGE}" \
  --tag "${final_image}" \
  --file "${remote_dockerfile}" \
  /tmp

run_on "${COMPUTE_NAME}" sudo docker run --rm \
  --entrypoint /bin/sh "${final_image}" \
  -ec 'command -v dnsmasq; dpkg-query -W -f="${Status}\n" dnsmasq-base'

run_on "${COMPUTE_NAME}" rm -f "${remote_dockerfile}"
log "Built and verified Kolla override image: ${final_image}"
