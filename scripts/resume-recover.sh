#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

[[ "${ENV}" == "local-arm64" ]] ||
  die "resume recovery is intentionally limited to local-arm64"

log "Starting or recovering outer Lima guests and OpenStack readiness"
scripts/local-up.sh
scripts/manage-route.sh add

log "Recovering nested CAPO workload clocks"
scripts/workload-clock.sh recover
scripts/workload-clock.sh check

log "Waiting for strict CAPI control-plane readiness"
scripts/workload-cluster.sh capi-ready
log "Local sleep/resume recovery passed"
