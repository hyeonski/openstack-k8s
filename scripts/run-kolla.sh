#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

[[ "$#" -eq 1 ]] || die "usage: run-kolla.sh COMMAND"
command_name="$1"
case "${command_name}" in
  bootstrap-servers|prechecks|validate-config|deploy|post-deploy|reconfigure|pull) ;;
  *) die "unsupported Kolla command: ${command_name}" ;;
esac

run_dir="$(current_or_new_run)"
log_file="${run_dir}/logs/kolla-${command_name}.log"
mkdir -p "$(dirname "${log_file}")"

log "Running Kolla-Ansible ${command_name}"
set +e
"${PROJECT_ROOT}/scripts/run-controller.sh" kolla-ansible "${command_name}" \
  -i "${KOLLA_DEPLOY_DIR}/kolla/generated/multinode" \
  2>&1 | "${PROJECT_ROOT}/scripts/redact-output.py" | tee "${log_file}"
result="${PIPESTATUS[0]}"
set -e

if [[ "${result}" -ne 0 ]]; then
  warn "Kolla ${command_name} failed; state and logs were preserved at ${run_dir}"
  exit "${result}"
fi

log "Kolla ${command_name} completed"
