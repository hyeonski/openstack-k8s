#!/usr/bin/env bash

set -Eeuo pipefail

KOLLA_DEPLOY_DIR="${KOLLA_DEPLOY_DIR:?}"
KUBERNETES_IMAGE_NAME="${KUBERNETES_IMAGE_NAME:?}"
KUBERNETES_VERSION="${KUBERNETES_VERSION:?}"
ARCHITECTURE="${ARCHITECTURE:?}"
KUBERNETES_CONTROL_PLANE_FLAVOR="${KUBERNETES_CONTROL_PLANE_FLAVOR:?}"
TENANT_NETWORK_NAME="${TENANT_NETWORK_NAME:?}"
EXTERNAL_NETWORK_NAME="${EXTERNAL_NETWORK_NAME:?}"

export OS_CLIENT_CONFIG_FILE=/etc/kolla/capi-clouds.yaml
export OS_CLOUD=capi
source /opt/kolla-venv/bin/activate

state_dir="${KOLLA_DEPLOY_DIR}/artifacts"
install -d -m 0700 "${state_dir}"
report="${state_dir}/kubernetes-image-verification.txt"
console_log="${state_dir}/kubernetes-image-console.log"
rm -f "${report}" "${console_log}"

server_name="verify-kubernetes-image"
key_name="openstack-k8s-kubernetes-image"
key_file="/home/${USER}/.ssh/openstack_k8s"
public_key="${state_dir}/kubernetes-image-verification.pub"

if openstack server show "${server_name}" >/dev/null 2>&1; then
  echo "${server_name} already exists; inspect and clean up the preserved failure first" >&2
  exit 1
fi

ssh-keygen -y -f "${key_file}" > "${public_key}"
openstack keypair delete "${key_name}" >/dev/null 2>&1 || true
openstack keypair create --public-key "${public_key}" "${key_name}" >/dev/null

openstack server create --wait \
  --config-drive true \
  --flavor "${KUBERNETES_CONTROL_PLANE_FLAVOR}" \
  --image "${KUBERNETES_IMAGE_NAME}" \
  --network "${TENANT_NETWORK_NAME}" \
  --security-group capi-test-allow \
  --key-name "${key_name}" \
  "${server_name}" >/dev/null
fip="$(openstack floating ip create \
  -f value -c floating_ip_address "${EXTERNAL_NETWORK_NAME}")"
openstack server add floating ip "${server_name}" "${fip}"

ssh_options=(
  -i "${key_file}"
  -o BatchMode=yes
  -o ConnectTimeout=5
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

wait_for_ssh() {
  local attempts=120
  local index
  for ((index = 1; index <= attempts; index++)); do
    if ssh "${ssh_options[@]}" "ubuntu@${fip}" true >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  return 1
}

if ! wait_for_ssh; then
  openstack console log show "${server_name}" | tee "${console_log}" || true
  echo "Kubernetes image did not become SSH reachable at ${fip}" >&2
  exit 1
fi

[[ "${ARCHITECTURE}" == "x86_64" ]] || {
  echo "unsupported GCP guest architecture: ${ARCHITECTURE}" >&2
  exit 1
}
expected_uname="x86_64"

log_guest="${state_dir}/kubernetes-image-guest-checks.log"
ssh "${ssh_options[@]}" "ubuntu@${fip}" bash -s -- \
  "${KUBERNETES_VERSION}" "${expected_uname}" \
  > "${log_guest}" <<'GUEST_CHECKS'
set -Eeuo pipefail
expected_version="$1"
expected_uname="$2"
expected_plain="${expected_version#v}"

cloud-init status --wait
[[ "$(uname -m)" == "${expected_uname}" ]]
sudo systemctl is-active containerd
kubeadm version -o short | grep -Fx "${expected_version}"
kubelet --version | grep -Fx "Kubernetes ${expected_version}"
kubectl version --client -o json | grep -F "\"gitVersion\": \"${expected_version}\""
sudo crictl --runtime-endpoint unix:///run/containerd/containerd.sock info >/dev/null
sudo modprobe overlay
sudo modprobe br_netfilter
[[ "$(sysctl -n net.ipv4.ip_forward)" == "1" ]]
[[ -z "$(swapon --noheadings)" ]]
sudo ctr --namespace k8s.io images pull registry.k8s.io/pause:3.10.2 >/dev/null
dpkg-query -W -f='${Version}\n' kubeadm | grep -Fx "${expected_plain}-1.1"
GUEST_CHECKS

ssh "${ssh_options[@]}" "ubuntu@${fip}" sudo systemctl reboot >/dev/null 2>&1 || true
for _ in {1..30}; do
  if ! ssh "${ssh_options[@]}" "ubuntu@${fip}" true >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
wait_for_ssh
ssh "${ssh_options[@]}" "ubuntu@${fip}" \
  "cloud-init status --wait; sudo systemctl is-active containerd; kubeadm version -o short" \
  >> "${log_guest}"

openstack console log show "${server_name}" > "${console_log}"
{
  echo "nova_active=pass"
  echo "ssh=pass"
  echo "cloud_init=pass"
  echo "architecture_${ARCHITECTURE}=pass"
  echo "kubernetes_version=pass"
  echo "containerd_cri=pass"
  echo "kernel_prerequisites=pass"
  echo "registry_pull=pass"
  echo "reboot_readiness=pass"
  echo "floating_ip=${fip}"
} > "${report}"

openstack server delete --wait "${server_name}"
openstack floating ip delete "${fip}"
openstack keypair delete "${key_name}"
echo "Kubernetes image verification succeeded"
