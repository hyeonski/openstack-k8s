#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

require_command gcloud
require_command python3
require_command rsync
require_command ssh-keygen
require_command tar
require_command curl
require_command kubectl

if command -v tofu >/dev/null 2>&1; then
  iac_engine="tofu"
elif command -v terraform >/dev/null 2>&1; then
  iac_engine="terraform"
else
  die "OpenTofu or Terraform is required"
fi

active_account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -n 1)"
[[ -n "${active_account}" ]] || die "gcloud has no active account"
gcloud projects describe "${GCP_PROJECT_ID}" --format='value(projectId)' |
  grep -qx "${GCP_PROJECT_ID}" || die "GCP project is unavailable: ${GCP_PROJECT_ID}"

log "Bootstrap client: ${iac_engine}, kubectl $(kubectl version --client -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)["clientVersion"]["gitVersion"])')"
log "GCP account/project: ${active_account}/${GCP_PROJECT_ID}"
log "Bootstrap preflight passed without requiring existing VPCs or VMs"
