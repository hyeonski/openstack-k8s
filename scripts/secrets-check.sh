#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

ensure_state_dirs

git check-ignore -q "${STATE_DIR}" ||
  die "${STATE_DIR} is not ignored by Git"

while IFS= read -r -d '' path; do
  [[ ! -L "${path}" ]] || die "secret path must not be a symlink: ${path}"
  owner="$(stat -f '%Su' "${path}")"
  [[ "${owner}" == "$(id -un)" ]] || die "unexpected owner for ${path}: ${owner}"
  mode="$(stat -f '%Lp' "${path}")"
  if [[ -d "${path}" ]]; then
    [[ "${mode}" == "700" ]] || die "secret directory must be mode 700: ${path} (${mode})"
  else
    [[ "${mode}" == "600" ]] || die "secret file must be mode 600: ${path} (${mode})"
  fi
done < <(find "${SECRET_DIR}" -mindepth 0 -print0)

log "Secret paths are ignored and permission-restricted"

