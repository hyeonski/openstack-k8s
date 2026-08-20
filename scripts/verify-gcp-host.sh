#!/usr/bin/env bash

set -Eeuo pipefail

role="${1:-}"
external_interface="${2:-}"
external_gateway_interface="${3:-}"
external_gateway_cidr="${4:-}"
case "${role}" in
  controller)
    expected_hostname="osk8s-controller"
    minimum_root_gib=70
    ;;
  compute01)
    expected_hostname="osk8s-compute01"
    minimum_root_gib=100
    ;;
  compute02)
    expected_hostname="osk8s-compute02"
    minimum_root_gib=100
    ;;
  *)
    echo "usage: verify-gcp-host.sh {controller|compute01|compute02}" >&2
    exit 2
    ;;
esac

[[ "$(hostname)" == "${expected_hostname}" ]]
[[ "$(uname -m)" == "x86_64" ]]
systemctl is-active --quiet chrony
[[ "$(sysctl -n net.ipv4.ip_forward)" == "1" ]]
[[ "$(sysctl -n net.bridge.bridge-nf-call-iptables)" == "1" ]]
swapon --show=NAME --noheadings | grep -qx '/swapfile-openstack-k8s'
getent hosts controller >/dev/null
getent hosts compute01 >/dev/null
getent hosts compute02 >/dev/null

root_gib="$(df -BG --output=size / | awk 'NR == 2 {gsub(/G/, "", $1); print $1}')"
(( root_gib >= minimum_root_gib ))

if [[ "${role}" == compute* ]]; then
  [[ -c /dev/kvm ]]
  [[ "$(cat /sys/module/kvm_intel/parameters/nested)" == "Y" ]]
fi

if [[ "${role}" == "controller" ]]; then
  [[ -n "${external_interface}" ]]
  [[ -n "${external_gateway_interface}" ]]
  [[ -n "${external_gateway_cidr}" ]]
  systemctl is-active --quiet openstack-external-network.service
  ip link show "${external_interface}" >/dev/null
  ip link show "${external_gateway_interface}" >/dev/null
  ip -4 -o address show dev "${external_gateway_interface}" |
    awk '{print $4}' |
    grep -Fxq "${external_gateway_cidr}"
fi

if [[ -e /var/run/reboot-required ]]; then
  reboot_required="yes"
else
  reboot_required="no"
fi

if command -v docker >/dev/null 2>&1; then
  docker_state="installed"
else
  docker_state="deferred-to-kolla-bootstrap"
fi

echo "host=${expected_hostname}"
echo "role=${role}"
echo "chrony=active"
echo "ip_forward=1"
echo "swap=2GiB"
echo "root_filesystem=${root_gib}GiB"
echo "docker=${docker_state}"
echo "reboot_required=${reboot_required}"
if [[ "${role}" == compute* ]]; then
  echo "nested_kvm=available"
else
  echo "external_network=active"
fi
