#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

echo "Environment: ${ENV}"
"${PROJECT_ROOT}/scripts/gcp-hosts.sh" status

echo
echo "State: ${STATE_DIR}"
if [[ -d "${STATE_DIR}" ]]; then
  find "${STATE_DIR}" -maxdepth 2 -type f -print
else
  echo "(not created)"
fi
