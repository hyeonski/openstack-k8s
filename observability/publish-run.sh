#!/usr/bin/env bash
# Publish the allowlisted run index; detailed local diagnostics remain private.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${ROOT}/scripts/lib/common.sh"
run_dir="${1:?pass an autoscaler-cycle evidence directory}"
[[ -d "${run_dir}" ]] || die "missing run directory: ${run_dir}"
run_id="$(basename "${run_dir}")"
[[ "${run_id}" == autoscaler-cycle-* ]] || die "refusing non-autoscaler evidence"
# Lifecycle attempts have local ordinal names; preserve their globally unique
# parent run in the remote key so separate experiments cannot collide.
parent_run="$(basename "$(dirname "${run_dir}")")"
if [[ "${parent_run}" == autoscaler-run-* ]]; then
  run_id="${parent_run}/${run_id}"
fi
manifest="${run_dir}/observability-manifest.json"
[[ -f "${manifest}" ]] || die "run manifest missing; build it first"
require_command gcloud
number="$(gcloud projects describe "${GCP_PROJECT_ID}" --format='value(projectNumber)')"
bucket="gs://osk8s-${number}-evidence"
gcloud storage cp "${manifest}" "${bucket}/${ENV}/${run_id}/manifest.json" \
  --if-generation-match=0
if [[ -f "${run_dir}/result.json" ]]; then
  gcloud storage cp "${run_dir}/result.json" "${bucket}/${ENV}/${run_id}/result.json" \
    --if-generation-match=0
fi
log "published ${run_id} index to ${bucket}/${ENV}/${run_id}/"
