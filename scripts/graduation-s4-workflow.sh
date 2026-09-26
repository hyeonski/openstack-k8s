#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
set -a
source "${PROJECT_ROOT}/scripts/lib/common.sh"
set +a
export PROJECT_ROOT STATE_DIR
exec python3 "${PROJECT_ROOT}/scripts/graduation_s4_workflow.py" "${1:?scenario, e2e, resume or status}"
