#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
set -a
source "${PROJECT_ROOT}/scripts/lib/common.sh"
set +a
export PROJECT_ROOT STATE_DIR
if [[ -n "${EVIDENCE_DIR:-}" ]]; then
  evidence="${EVIDENCE_DIR}"
else
  record="${STATE_DIR}/s4-experiment.json"
  [[ -f "${record}" ]] || die "no S4 experiment record; pass EVIDENCE_DIR"
  evidence="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["evidence"])' "${record}")"
fi
exec python3 "${PROJECT_ROOT}/scripts/graduation_s4_analyze.py" "${evidence}"
