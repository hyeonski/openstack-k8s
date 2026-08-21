#!/usr/bin/env bash

set -Eeuo pipefail

KOLLA_DEPLOY_DIR="${KOLLA_DEPLOY_DIR:?}"
OPENSTACK_TEST_FLAVOR="${OPENSTACK_TEST_FLAVOR:?}"
CIRROS_IMAGE_NAME="${CIRROS_IMAGE_NAME:?}"
UBUNTU_IMAGE_NAME="${UBUNTU_IMAGE_NAME:?}"
TENANT_NETWORK_NAME="${TENANT_NETWORK_NAME:?}"
EXTERNAL_NETWORK_NAME="${EXTERNAL_NETWORK_NAME:?}"

export OS_CLIENT_CONFIG_FILE=/etc/kolla/capi-clouds.yaml
export OS_CLOUD=capi
source /opt/kolla-venv/bin/activate

state_dir="${KOLLA_DEPLOY_DIR}/artifacts"
state_file="${state_dir}/verification.env"
install -d -m 0700 "${state_dir}"
rm -f "${state_file}"

key_name="openstack-k8s-verification"
key_file="/home/${USER}/.ssh/openstack_k8s"
public_key="${state_dir}/verification.pub"
ssh-keygen -y -f "${key_file}" > "${public_key}"

# This keypair is reserved for disposable verification servers. Reconcile it on
# every run because the ignored local state (and therefore the private key) may
# have been removed while the persistent OpenStack keypair still exists.
openstack keypair delete "${key_name}" >/dev/null 2>&1 || true
openstack keypair create --public-key "${public_key}" "${key_name}" >/dev/null

wait_for_ssh() {
  local user="$1"
  local address="$2"
  local attempts=60
  local index
  for ((index = 1; index <= attempts; index++)); do
    if ssh -i "${key_file}" \
      -o BatchMode=yes \
      -o ConnectTimeout=5 \
      -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      "${user}@${address}" true >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  return 1
}

create_server_with_fip() {
  local server_name="$1"
  local image="$2"
  shift 2
  local extra=("$@")
  local fip

  delete_server_and_fips "${server_name}"
  openstack server create --wait \
    --config-drive true \
    --flavor "${OPENSTACK_TEST_FLAVOR}" \
    --image "${image}" \
    --network "${TENANT_NETWORK_NAME}" \
    --security-group capi-test-allow \
    --key-name "${key_name}" \
    "${extra[@]}" \
    "${server_name}" >/dev/null
  fip="$(openstack floating ip create \
    -f value -c floating_ip_address "${EXTERNAL_NETWORK_NAME}")"
  openstack server add floating ip "${server_name}" "${fip}"
  printf '%s\n' "${fip}"
}

delete_server_and_fips() {
  local server_name="$1"
  local addresses
  local address

  addresses="$(
    openstack server show "${server_name}" -f value -c addresses 2>/dev/null || true
  )"
  while IFS= read -r address; do
    if openstack floating ip show "${address}" >/dev/null 2>&1; then
      openstack floating ip delete "${address}"
    fi
  done < <(grep -Eo '([0-9]{1,3}\.){3}[0-9]{1,3}' <<<"${addresses}" | sort -u)
  openstack server delete --wait "${server_name}" >/dev/null 2>&1 || true
}

cirros_name="verify-cirros"
cirros_fip="$(create_server_with_fip "${cirros_name}" "${CIRROS_IMAGE_NAME}")"
if ! wait_for_ssh cirros "${cirros_fip}"; then
  openstack console log show "${cirros_name}" || true
  echo "CirrOS did not become SSH reachable at ${cirros_fip}" >&2
  exit 1
fi
ssh -i "${key_file}" \
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  "cirros@${cirros_fip}" \
  "ip -4 address; ping -c 3 1.1.1.1" >/dev/null
openstack console log show "${cirros_name}" > "${state_dir}/cirros-console.log"
openstack server delete --wait "${cirros_name}"
openstack floating ip delete "${cirros_fip}"

ubuntu_name="verify-ubuntu-api"
ubuntu_fip="$(
  create_server_with_fip "${ubuntu_name}" "${UBUNTU_IMAGE_NAME}" \
    --user-data "${KOLLA_DEPLOY_DIR}/openstack/cloud-init-api-probe.yaml"
)"
if ! wait_for_ssh ubuntu "${ubuntu_fip}"; then
  openstack console log show "${ubuntu_name}" || true
  echo "Ubuntu did not become SSH reachable at ${ubuntu_fip}" >&2
  exit 1
fi
ssh -i "${key_file}" \
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  "ubuntu@${ubuntu_fip}" \
  "cloud-init status --wait; systemctl is-active capo-api-probe.service"

for _ in {1..30}; do
  if curl --fail --silent --show-error --connect-timeout 5 \
    "http://${ubuntu_fip}:6443/" >/dev/null; then
    break
  fi
  sleep 3
done
curl --fail --silent --show-error --connect-timeout 5 \
  "http://${ubuntu_fip}:6443/" >/dev/null

cat > "${state_file}" <<EOF
UBUNTU_TEST_SERVER="${ubuntu_name}"
UBUNTU_TEST_FLOATING_IP="${ubuntu_fip}"
EOF
chmod 0600 "${state_file}"

# This script intentionally uses the restricted CAPO application credential.
# Successful guest creation already exercises Nova scheduling and the Neutron
# agents; keep the final inventory checks within tenant-level policy.
# Validate the application credential without writing the bearer token itself
# to the persisted verification log.
openstack token issue -f value -c project_id >/dev/null
openstack server list
openstack network list
openstack image list
echo "Guest verification succeeded; Ubuntu probe remains at ${ubuntu_fip}:6443"
