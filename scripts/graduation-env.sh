#!/usr/bin/env bash
# Common, non-destructive environment gate for graduation scenarios.
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

export PROJECT_ROOT ENVIRONMENT_NAME GCP_PROJECT_ID GCP_ZONE
export WORKLOAD_CLUSTER_NAME WORKLOAD_NAMESPACE
export STATE_DIR
exec python3 "${PROJECT_ROOT}/scripts/graduation_env.py" "$1" \
  --host "${CONTROLLER_NAME}" \
  "${COMPUTE_NAMES[@]/#/--host=}"
