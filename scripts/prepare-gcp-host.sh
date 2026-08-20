#!/usr/bin/env bash

set -Eeuo pipefail

role="${1:-}"
case "${role}" in
  controller) expected_hostname="osk8s-controller" ;;
  compute01) expected_hostname="osk8s-compute01" ;;
  compute02) expected_hostname="osk8s-compute02" ;;
  *)
    echo "usage: prepare-gcp-host.sh {controller|compute01|compute02}" >&2
    exit 2
    ;;
esac

if [[ "${EUID}" -ne 0 ]]; then
  echo "prepare-gcp-host.sh must run as root" >&2
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID}" == "ubuntu" ]] || {
  echo "Ubuntu is required; found ${ID}" >&2
  exit 1
}
[[ "${VERSION_ID}" == "24.04" ]] || {
  echo "Ubuntu 24.04 is required; found ${VERSION_ID}" >&2
  exit 1
}
[[ "$(uname -m)" == "x86_64" ]] || {
  echo "x86_64 is required; found $(uname -m)" >&2
  exit 1
}

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  ca-certificates \
  chrony \
  cloud-guest-utils \
  curl \
  file \
  git \
  iptables \
  jq \
  openssh-client \
  python3 \
  python3-apt \
  python3-docker \
  python3-libvirt \
  python3-venv \
  rsync

if [[ "${role}" == compute* ]]; then
  apt-get install -y cpu-checker
fi

hostnamectl set-hostname "${expected_hostname}"
systemctl enable --now chrony

hosts_tmp="$(mktemp)"
trap 'rm -f "${hosts_tmp}"' EXIT
sed '/^# BEGIN OPENSTACK-K8S GCP HOSTS$/,/^# END OPENSTACK-K8S GCP HOSTS$/d' \
  /etc/hosts > "${hosts_tmp}"
cat >> "${hosts_tmp}" <<'EOF'
# BEGIN OPENSTACK-K8S GCP HOSTS
10.20.0.10 osk8s-controller controller
10.20.0.21 osk8s-compute01 compute01
10.20.0.22 osk8s-compute02 compute02
# END OPENSTACK-K8S GCP HOSTS
EOF
install -o root -g root -m 0644 "${hosts_tmp}" /etc/hosts

cat > /etc/modules-load.d/openstack-k8s.conf <<'EOF'
br_netfilter
overlay
EOF
modprobe br_netfilter
modprobe overlay

cat > /etc/sysctl.d/99-openstack-k8s.conf <<'EOF'
net.ipv4.ip_forward = 1
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
vm.swappiness = 10
EOF
sysctl --system >/dev/null

swap_file="/swapfile-openstack-k8s"
if [[ ! -f "${swap_file}" ]]; then
  fallocate -l 2G "${swap_file}"
  chmod 0600 "${swap_file}"
  mkswap "${swap_file}"
fi
if ! swapon --show=NAME --noheadings | grep -qx "${swap_file}"; then
  swapon "${swap_file}"
fi
if ! grep -Eq "^[^#]+[[:space:]]+none[[:space:]]+swap[[:space:]]+.*openstack-k8s" /etc/fstab; then
  printf '%s\n' "${swap_file} none swap sw,comment=openstack-k8s 0 0" >> /etc/fstab
fi

if [[ "${role}" == compute* ]]; then
  printf '%s\n' 'kvm_intel' > /etc/modules-load.d/openstack-k8s-kvm.conf
  modprobe kvm_intel
  [[ -c /dev/kvm ]] || {
    echo "/dev/kvm is unavailable" >&2
    exit 1
  }
  [[ "$(cat /sys/module/kvm_intel/parameters/nested)" == "Y" ]] || {
    echo "nested KVM is not enabled" >&2
    exit 1
  }
  kvm-ok
fi

echo "host=${expected_hostname}"
echo "role=${role}"
echo "architecture=$(uname -m)"
echo "chrony=$(systemctl is-active chrony)"
echo "ip_forward=$(sysctl -n net.ipv4.ip_forward)"
echo "swap=$(swapon --show=NAME,SIZE --noheadings | xargs)"
df -hT /
