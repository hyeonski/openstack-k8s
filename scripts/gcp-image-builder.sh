#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

require_command gcloud
require_command python3

if [[ -n "${IAC_ENGINE:-}" ]]; then
  engine="${IAC_ENGINE}"
elif command -v tofu >/dev/null 2>&1; then
  engine="tofu"
elif command -v terraform >/dev/null 2>&1; then
  engine="terraform"
else
  die "OpenTofu or Terraform is required"
fi

iac_dir="${PROJECT_ROOT}/infra/gcp"
action="${1:-}"
ensure_state_dirs
plan_file="${STATE_DIR}/gcp-image-builder.tfplan"

run_iac() {
  "${engine}" -chdir="${iac_dir}" "$@"
}

plan_and_apply() {
  local enabled="$1"
  local expected_action="$2"
  local status

  set +e
  run_iac plan -input=false -detailed-exitcode \
    -var="enable_image_builder=${enabled}" \
    -var="image_builder_name=${IMAGE_BUILDER_NAME}" \
    -var="image_builder_machine_type=${IMAGE_BUILDER_MACHINE_TYPE}" \
    -var="image_builder_disk_size_gb=${IMAGE_BUILDER_DISK_GIB}" \
    -out="${plan_file}"
  status="$?"
  set -e
  case "${status}" in
    0)
      log "Image-builder infrastructure already matches enabled=${enabled}"
      return
      ;;
    2)
      run_iac show -json "${plan_file}" |
        python3 "${PROJECT_ROOT}/scripts/validate-image-builder-plan.py" \
          "${expected_action}"
      run_iac apply -input=false "${plan_file}"
      ;;
    *)
      exit "${status}"
      ;;
  esac
}

wait_for_running() {
  local attempt status
  for ((attempt = 1; attempt <= 60; attempt++)); do
    status="$(gcloud compute instances describe "${IMAGE_BUILDER_NAME}" \
      --project="${GCP_PROJECT_ID}" --zone="${GCP_ZONE}" \
      --format='value(status)' 2>/dev/null || true)"
    [[ "${status}" == "RUNNING" ]] && return
    sleep 5
  done
  die "image builder did not become RUNNING"
}

wait_for_ssh() {
  local attempt
  for ((attempt = 1; attempt <= 60; attempt++)); do
    if run_on "${IMAGE_BUILDER_NAME}" true >/dev/null 2>&1; then
      return
    fi
    sleep 5
  done
  die "image builder SSH did not become ready"
}

case "${action}" in
  create)
    plan_and_apply true create
    if [[ "$(instance_status "${IMAGE_BUILDER_NAME}" 2>/dev/null || true)" == "Stopped" ]]; then
      gcloud compute instances start "${IMAGE_BUILDER_NAME}" \
        --project="${GCP_PROJECT_ID}" --zone="${GCP_ZONE}" --quiet
    fi
    wait_for_running
    wait_for_ssh

    remote_prepare="/tmp/openstack-k8s-prepare-image-builder.sh"
    copy_to "${PROJECT_ROOT}/scripts/prepare-image-builder-host.sh" \
      "${IMAGE_BUILDER_NAME}" "${remote_prepare}"
    run_on "${IMAGE_BUILDER_NAME}" sudo env \
      TARGET_SSH_USER="${TARGET_SSH_USER}" bash "${remote_prepare}"
    run_on "${IMAGE_BUILDER_NAME}" rm -f "${remote_prepare}"
    run_on "${IMAGE_BUILDER_NAME}" bash -lc \
      'test "$(uname -m)" = x86_64'
    run_on "${IMAGE_BUILDER_NAME}" test -c /dev/kvm
    run_on "${IMAGE_BUILDER_NAME}" id -nG | tr ' ' '\n' | grep -Fx kvm >/dev/null ||
      die "${TARGET_SSH_USER} did not receive access to /dev/kvm"

    max_run="$(gcloud compute instances describe "${IMAGE_BUILDER_NAME}" \
      --project="${GCP_PROJECT_ID}" --zone="${GCP_ZONE}" \
      --format='value(scheduling.maxRunDuration.seconds)')"
    [[ "${max_run}" == "${GCP_MAX_RUN_DURATION_SECONDS:-36000}" ]] ||
      die "unexpected image-builder max run duration: ${max_run}"
    log "GCP AMD64 image builder is ready with ${max_run}s automatic STOP"
    ;;
  delete)
    plan_and_apply false delete
    log "Disposable GCP image builder is absent"
    ;;
  *)
    die "usage: gcp-image-builder.sh create|delete"
    ;;
esac
