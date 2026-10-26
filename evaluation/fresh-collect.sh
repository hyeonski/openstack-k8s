#!/usr/bin/env bash
# Retrieve existing evidence without starting an environment, probe, or action.
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a
source "${PROJECT_ROOT}/scripts/lib/common.sh"
set +a
export PROJECT_ROOT STATE_DIR
exec python3 "${PROJECT_ROOT}/evaluation/fresh_collection.py" "$@"
