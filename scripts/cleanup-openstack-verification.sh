#!/usr/bin/env bash

set -Eeuo pipefail

KOLLA_DEPLOY_DIR="${KOLLA_DEPLOY_DIR:?}"
state_file="${KOLLA_DEPLOY_DIR}/artifacts/verification.env"
[[ -f "${state_file}" ]] || exit 0
# shellcheck disable=SC1090
source "${state_file}"

export OS_CLIENT_CONFIG_FILE=/etc/kolla/capi-clouds.yaml
export OS_CLOUD=capi
source /opt/kolla-venv/bin/activate

openstack server delete --wait "${UBUNTU_TEST_SERVER}" >/dev/null 2>&1 || true
openstack floating ip delete "${UBUNTU_TEST_FLOATING_IP}" \
  >/dev/null 2>&1 || true
rm -f "${state_file}"
echo "Verification server and Floating IP removed"
