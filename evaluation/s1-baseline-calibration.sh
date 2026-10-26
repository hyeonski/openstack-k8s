#!/usr/bin/env bash
# Explicit normal-load-only entry point. Does not dispatch fresh campaign run.
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
set -a
source "${PROJECT_ROOT}/scripts/lib/common.sh"
set +a
export PROJECT_ROOT STATE_DIR
exec python3 "${PROJECT_ROOT}/evaluation/fresh_calibration.py" "$@"
