#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

require_command gcloud
for node in "${CONTROLLER_NAME}" "${COMPUTE_NAMES[@]}"; do
  ready="no"
  for ((attempt = 1; attempt <= 60; attempt++)); do
    if run_on "${node}" true >/dev/null 2>&1; then
      ready="yes"
      break
    fi
    sleep 5
  done
  [[ "${ready}" == "yes" ]] || die "SSH did not become ready: ${node}"
  log "SSH ready: ${node}"
done
