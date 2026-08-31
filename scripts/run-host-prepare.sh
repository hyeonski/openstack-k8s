#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

"${PROJECT_ROOT}/scripts/run-controller.sh" ansible-playbook \
  -i "${KOLLA_DEPLOY_DIR}/ansible/inventory/${ENV}/generated-hosts.ini" \
  "${KOLLA_DEPLOY_DIR}/ansible/playbooks/prepare-hosts.yml"
