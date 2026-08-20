#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

case "${HOST_PROVIDER}" in
  lima) exec "${PROJECT_ROOT}/scripts/host-preflight.sh" ;;
  gcp) exec "${PROJECT_ROOT}/scripts/gcp-preflight.sh" ;;
  *) die "unsupported host provider: ${HOST_PROVIDER}" ;;
esac
