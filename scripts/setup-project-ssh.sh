#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

ensure_state_dirs
key="${SECRET_DIR}/deployment_ed25519"
require_command ssh-keygen

if [[ ! -f "${key}" ]]; then
  ssh-keygen -q -t ed25519 -N "" -C "openstack-k8s-${ENV}" -f "${key}"
  chmod 600 "${key}"
  chmod 600 "${key}.pub"
fi

pubkey="$(<"${key}.pub")"
while IFS= read -r node; do
  run_on "${node}" bash -lc \
    "umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; grep -qxF '${pubkey}' ~/.ssh/authorized_keys || printf '%s\n' '${pubkey}' >> ~/.ssh/authorized_keys; chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys"
done < <(all_instance_names)

tmpkey="/tmp/openstack-k8s-deployment-key"
copy_to "${key}" "${CONTROLLER_NAME}" "${tmpkey}"
run_on "${CONTROLLER_NAME}" bash -lc \
  "umask 077; mkdir -p ~/.ssh; install -m 600 '${tmpkey}' ~/.ssh/openstack_k8s; rm -f '${tmpkey}'"

log "Project-scoped deployment SSH key installed"
