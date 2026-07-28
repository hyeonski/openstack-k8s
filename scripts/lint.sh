#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

status=0
while IFS= read -r file; do
  if ! bash -n "${file}"; then
    status=1
  fi
done < <(find "${PROJECT_ROOT}/scripts" -type f -name '*.sh' -print | sort)

if command -v shellcheck >/dev/null 2>&1; then
  while IFS= read -r file; do
    shellcheck -x "${file}" || status=1
  done < <(find "${PROJECT_ROOT}/scripts" -type f -name '*.sh' -print | sort)
else
  echo "WARN: shellcheck not installed; syntax checks only" >&2
fi

if [[ "${status}" -ne 0 ]]; then
  exit "${status}"
fi

python3 -m py_compile "${PROJECT_ROOT}"/scripts/*.py
python3 -m unittest discover -s "${PROJECT_ROOT}/tests" -p 'test_*.py'

echo "Static shell checks passed."
