#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

confirmation="${1:-}"
[[ "${confirmation}" == "${ENV}" ]] ||
  die "refusing full lab deployment; pass CONFIRM=${ENV}"

run_make() {
  log "Running make $*"
  make -C "${PROJECT_ROOT}" "$@"
}

run_make bootstrap-preflight
run_make gcp-bootstrap CONFIRM="${confirmation}"
run_make gcp-iac-init
run_make gcp-iac-validate

if ! "${PROJECT_ROOT}/scripts/gcp-iac.sh" foundation-ready; then
  run_make gcp-foundation-plan
  run_make gcp-foundation-apply CONFIRM="${confirmation}"
else
  log "Skipping foundation create; managed resources are already present"
fi

run_make gcp-start
run_make gcp-wait-ssh
run_make inventory
run_make gcp-deployment-key-setup
run_make host-prepare
run_make gcp-host-verify
run_make gcp-openstack-recover

run_make openstack-precheck
run_make openstack-pull
run_make openstack-deploy
run_make openstack-validate
run_make openstack-post-deploy
run_make openstack-bootstrap

run_make gcp-floating-ip-route-plan
run_make gcp-floating-ip-route-apply CONFIRM="${confirmation}"
run_make openstack-verify

image_dir="${STATE_DIR}/images"
image_name="${KUBERNETES_IMAGE_NAME}.qcow2"
if [[ -f "${image_dir}/${image_name}" && -f "${image_dir}/${image_name}.sha256" ]] &&
    (cd "${image_dir}" && shasum -a 256 -c "${image_name}.sha256" >/dev/null 2>&1); then
  log "Reusing verified Kubernetes image artifact: ${image_name}"
else
  run_make kubernetes-image-builder-create
  run_make kubernetes-image-build
fi
run_make kubernetes-image-upload
run_make kubernetes-image-verify
if instance_exists "${IMAGE_BUILDER_NAME}"; then
  run_make kubernetes-image-builder-destroy CONFIRM="${confirmation}"
fi

run_make gcp-controller-management-prepare
run_make management-cluster-create
run_make capi-providers-install
run_make capi-credentials-verify
run_make workload-cluster-create
run_make cluster-autoscaler-install
run_make cluster-autoscaler-verify

log "Greenfield GCP, OpenStack, Kubernetes, and Autoscaler deployment completed"
