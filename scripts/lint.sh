#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v rg >/dev/null 2>&1 || {
  echo "ERROR: ripgrep is required for GCP-only regression checks" >&2
  exit 1
}

status=0
while IFS= read -r file; do
  if ! bash -n "${file}"; then
    status=1
  fi
done < <(find "${PROJECT_ROOT}/scripts" -type f -name '*.sh' -print | sort)

if command -v shellcheck >/dev/null 2>&1; then
  while IFS= read -r file; do
    shellcheck --severity=warning -x "${file}" || status=1
  done < <(find "${PROJECT_ROOT}/scripts" -type f -name '*.sh' -print | sort)
else
  echo "WARN: shellcheck not installed; syntax checks only" >&2
fi

if [[ "${status}" -ne 0 ]]; then
  exit "${status}"
fi

forbidden_pattern='HOST_PROVIDER|limactl|socket_vmnet|local-arm64|LIMA_|qemu-system-aarch64|configure-image-builder-arm64|build-kolla-overrides|run-as-administrator'
if rg -n -i --glob '!lint.sh' "${forbidden_pattern}" \
    "${PROJECT_ROOT}/Makefile" \
    "${PROJECT_ROOT}/ansible" \
    "${PROJECT_ROOT}/config" \
    "${PROJECT_ROOT}/kolla" \
    "${PROJECT_ROOT}/kubernetes" \
    "${PROJECT_ROOT}/scripts" \
    "${PROJECT_ROOT}/systemd" \
    "${PROJECT_ROOT}/tests"; then
  echo "ERROR: removed local-VM automation was reintroduced" >&2
  exit 1
fi

python3 -m py_compile "${PROJECT_ROOT}"/scripts/*.py
python3 -m unittest discover -s "${PROJECT_ROOT}/tests" -p 'test_*.py'

echo "Static shell checks passed."
