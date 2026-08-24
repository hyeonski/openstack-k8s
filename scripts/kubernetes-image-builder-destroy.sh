#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

[[ "${1:-}" == "${ENV}" ]] ||
  die "refusing deletion; run with CONFIRM=${ENV}"
exec "${PROJECT_ROOT}/scripts/gcp-image-builder.sh" delete
