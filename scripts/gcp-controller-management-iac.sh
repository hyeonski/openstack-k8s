#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

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

ensure_state_dirs
iac_dir="${PROJECT_ROOT}/infra/gcp"
plan_file="${STATE_DIR}/gcp-controller-management.tfplan"

run_iac() {
  "${engine}" -chdir="${iac_dir}" "$@"
}

set +e
run_iac plan -input=false -detailed-exitcode -out="${plan_file}"
plan_status="$?"
set -e
case "${plan_status}" in
  0)
    log "Controller management network already matches the declaration"
    ;;
  2)
    run_iac show -json "${plan_file}" |
      python3 "${PROJECT_ROOT}/scripts/validate-controller-management-plan.py"
    run_iac apply -input=false "${plan_file}"
    ;;
  *)
    exit "${plan_status}"
    ;;
esac
