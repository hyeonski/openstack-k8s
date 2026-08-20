#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

echo "Environment: ${ENV}"
if [[ "${HOST_PROVIDER}" == "gcp" ]]; then
  "${PROJECT_ROOT}/scripts/gcp-hosts.sh" status
elif command -v limactl >/dev/null 2>&1; then
  limactl list
  echo
  limactl network list || true
else
  echo "Lima is not installed."
fi

echo
echo "State: ${STATE_DIR}"
if [[ -d "${STATE_DIR}" ]]; then
  find "${STATE_DIR}" -maxdepth 2 -type f -print
else
  echo "(not created)"
fi
