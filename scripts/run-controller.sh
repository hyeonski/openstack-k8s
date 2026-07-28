#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

[[ "$#" -gt 0 ]] || die "usage: run-controller.sh COMMAND [ARG...]"
instance_running "${CONTROLLER_NAME}" || die "controller is not running"

quoted=()
for arg in "$@"; do
  printf -v escaped '%q' "${arg}"
  quoted+=("${escaped}")
done

run_on "${CONTROLLER_NAME}" bash -lc \
  "source '${KOLLA_VENV}/bin/activate'; export ANSIBLE_CONFIG='${KOLLA_DEPLOY_DIR}/ansible/ansible.cfg'; export GUEST_SWAP_GIB='${GUEST_SWAP_GIB}'; export EXTERNAL_INTERFACE='${EXTERNAL_INTERFACE}'; export EXTERNAL_GATEWAY_INTERFACE='${EXTERNAL_GATEWAY_INTERFACE}'; export EXTERNAL_CIDR='${EXTERNAL_CIDR}'; export EXTERNAL_GATEWAY='${EXTERNAL_GATEWAY}'; export LIMA_MANAGEMENT_INTERFACE='${LIMA_MANAGEMENT_INTERFACE}'; ${quoted[*]}"

