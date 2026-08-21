#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

[[ "${HOST_PROVIDER}" == "gcp" ]] || die "GCP management host requires a GCP profile"
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

[[ "${1:-}" == "create" ]] || die "usage: gcp-management-host.sh create"
ensure_state_dirs
iac_dir="${PROJECT_ROOT}/infra/gcp"
plan_file="${STATE_DIR}/gcp-management-host.tfplan"

run_iac() {
  "${engine}" -chdir="${iac_dir}" "$@"
}

set +e
run_iac plan -input=false -detailed-exitcode -out="${plan_file}"
plan_status="$?"
set -e
case "${plan_status}" in
  0)
    log "Management-host infrastructure already matches the declaration"
    ;;
  2)
    run_iac show -json "${plan_file}" |
      python3 "${PROJECT_ROOT}/scripts/validate-management-host-plan.py"
    run_iac apply -input=false "${plan_file}"
    ;;
  *)
    exit "${plan_status}"
    ;;
esac

if [[ "$(instance_status "${MANAGEMENT_HOST_NAME}" 2>/dev/null || true)" == "Stopped" ]]; then
  gcloud compute instances start "${MANAGEMENT_HOST_NAME}" \
    --project="${GCP_PROJECT_ID}" --zone="${GCP_ZONE}" --quiet
fi

for _ in {1..60}; do
  if instance_running "${MANAGEMENT_HOST_NAME}" &&
      run_on "${MANAGEMENT_HOST_NAME}" true >/dev/null 2>&1; then
    break
  fi
  sleep 5
done
instance_running "${MANAGEMENT_HOST_NAME}" || die "management host did not become RUNNING"
run_on "${MANAGEMENT_HOST_NAME}" true >/dev/null 2>&1 ||
  die "management host SSH did not become ready"

remote_prepare="/tmp/openstack-k8s-prepare-management-host.sh"
copy_to "${PROJECT_ROOT}/scripts/prepare-management-host.sh" \
  "${MANAGEMENT_HOST_NAME}" "${remote_prepare}"
run_on "${MANAGEMENT_HOST_NAME}" sudo env \
  TARGET_SSH_USER="${TARGET_SSH_USER}" bash "${remote_prepare}"
run_on "${MANAGEMENT_HOST_NAME}" rm -f "${remote_prepare}"

run_on "${MANAGEMENT_HOST_NAME}" bash -lc \
  'test "$(uname -m)" = x86_64 && test "$(stat -fc %T /sys/fs/cgroup)" = cgroup2fs'
run_on "${MANAGEMENT_HOST_NAME}" docker info >/dev/null

max_run="$(gcloud compute instances describe "${MANAGEMENT_HOST_NAME}" \
  --project="${GCP_PROJECT_ID}" --zone="${GCP_ZONE}" \
  --format='value(scheduling.maxRunDuration.seconds)')"
[[ "${max_run}" == "${GCP_MAX_RUN_DURATION_SECONDS:-36000}" ]] ||
  die "unexpected management-host max run duration: ${max_run}"
log "GCP management host is ready with ${max_run}s automatic STOP"
