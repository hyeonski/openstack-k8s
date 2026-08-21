#!/usr/bin/env bash

set -Eeuo pipefail

MANAGEMENT_DOCKER_NETWORK="${MANAGEMENT_DOCKER_NETWORK:?}"
MANAGEMENT_DOCKER_CIDR="${MANAGEMENT_DOCKER_CIDR:?}"
MANAGEMENT_DOCKER_BRIDGE="${MANAGEMENT_DOCKER_BRIDGE:?}"

rule_exists() {
  iptables "$@" >/dev/null 2>&1
}

remove_rule() {
  local table_args=("$@")
  local delete_args
  local index
  while rule_exists "${table_args[@]}"; do
    delete_args=("${table_args[@]}")
    for index in "${!delete_args[@]}"; do
      if [[ "${delete_args[index]}" == "-C" ]]; then
        delete_args[index]="-D"
        break
      fi
    done
    iptables "${delete_args[@]}"
  done
}

network_exists() {
  docker network inspect "${MANAGEMENT_DOCKER_NETWORK}" >/dev/null 2>&1
}

verify_network() {
  local subnet bridge
  subnet="$(docker network inspect "${MANAGEMENT_DOCKER_NETWORK}" \
    --format '{{(index .IPAM.Config 0).Subnet}}')"
  bridge="$(docker network inspect "${MANAGEMENT_DOCKER_NETWORK}" \
    --format '{{index .Options "com.docker.network.bridge.name"}}')"
  [[ "${subnet}" == "${MANAGEMENT_DOCKER_CIDR}" ]] || {
    echo "unexpected ${MANAGEMENT_DOCKER_NETWORK} subnet: ${subnet}" >&2
    exit 1
  }
  [[ "${bridge}" == "${MANAGEMENT_DOCKER_BRIDGE}" ]] || {
    echo "unexpected ${MANAGEMENT_DOCKER_NETWORK} bridge: ${bridge}" >&2
    exit 1
  }
}

start_network() {
  if network_exists; then
    verify_network
  else
    docker network create \
      --driver bridge \
      --subnet "${MANAGEMENT_DOCKER_CIDR}" \
      --opt "com.docker.network.bridge.name=${MANAGEMENT_DOCKER_BRIDGE}" \
      --opt com.docker.network.bridge.enable_ip_masquerade=false \
      "${MANAGEMENT_DOCKER_NETWORK}" >/dev/null
  fi

  if ! rule_exists -C FORWARD -i "${MANAGEMENT_DOCKER_BRIDGE}" -j ACCEPT; then
    iptables -I FORWARD 1 -i "${MANAGEMENT_DOCKER_BRIDGE}" -j ACCEPT
  fi
  if ! rule_exists -C FORWARD -o "${MANAGEMENT_DOCKER_BRIDGE}" \
      -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT; then
    iptables -I FORWARD 2 -o "${MANAGEMENT_DOCKER_BRIDGE}" \
      -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
  fi
  if ! rule_exists -t nat -C POSTROUTING -s "${MANAGEMENT_DOCKER_CIDR}" \
      ! -d "${MANAGEMENT_DOCKER_CIDR}" -j MASQUERADE; then
    iptables -t nat -A POSTROUTING -s "${MANAGEMENT_DOCKER_CIDR}" \
      ! -d "${MANAGEMENT_DOCKER_CIDR}" -j MASQUERADE
  fi
}

stop_network() {
  remove_rule -C FORWARD -i "${MANAGEMENT_DOCKER_BRIDGE}" -j ACCEPT
  remove_rule -C FORWARD -o "${MANAGEMENT_DOCKER_BRIDGE}" \
    -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
  remove_rule -t nat -C POSTROUTING -s "${MANAGEMENT_DOCKER_CIDR}" \
    ! -d "${MANAGEMENT_DOCKER_CIDR}" -j MASQUERADE
  if network_exists; then
    endpoint_count="$(docker network inspect "${MANAGEMENT_DOCKER_NETWORK}" \
      --format '{{len .Containers}}')"
    [[ "${endpoint_count}" == "0" ]] || {
      echo "refusing to remove network with ${endpoint_count} endpoints" >&2
      exit 1
    }
    docker network rm "${MANAGEMENT_DOCKER_NETWORK}" >/dev/null
  fi
}

case "${1:-}" in
  start) start_network ;;
  stop) stop_network ;;
  verify)
    verify_network
    rule_exists -C FORWARD -i "${MANAGEMENT_DOCKER_BRIDGE}" -j ACCEPT
    rule_exists -C FORWARD -o "${MANAGEMENT_DOCKER_BRIDGE}" \
      -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
    rule_exists -t nat -C POSTROUTING -s "${MANAGEMENT_DOCKER_CIDR}" \
      ! -d "${MANAGEMENT_DOCKER_CIDR}" -j MASQUERADE
    ;;
  *)
    echo "usage: controller-kind-network.sh {start|stop|verify}" >&2
    exit 2
    ;;
esac
