#!/usr/bin/env bash

set -Eeuo pipefail

mode="${1:-}"
case "${mode}" in
  controller|compute) ;;
  *)
    echo "usage: install-gcp-deployment-key.sh {controller|compute}" >&2
    exit 2
    ;;
esac

cleanup() {
  rm -f /tmp/deployment_ed25519 /tmp/deployment_ed25519.pub
}
trap cleanup EXIT

install -d -m 0700 "${HOME}/.ssh"

if [[ "${mode}" == "controller" ]]; then
  install -m 0600 /tmp/deployment_ed25519 "${HOME}/.ssh/openstack_k8s"
  install -m 0600 /tmp/deployment_ed25519.pub "${HOME}/.ssh/openstack_k8s.pub"
  cat > "${HOME}/.ssh/config.d-openstack-k8s" <<EOF
Host compute01
  HostName 10.20.0.21
  User ${USER}
  IdentityFile ~/.ssh/openstack_k8s
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new

Host compute02
  HostName 10.20.0.22
  User ${USER}
  IdentityFile ~/.ssh/openstack_k8s
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
EOF
  chmod 0600 "${HOME}/.ssh/config.d-openstack-k8s"

  if [[ ! -f "${HOME}/.ssh/config" ]]; then
    touch "${HOME}/.ssh/config"
    chmod 0600 "${HOME}/.ssh/config"
  fi
  if ! grep -qxF 'Include ~/.ssh/config.d-openstack-k8s' "${HOME}/.ssh/config"; then
    printf '%s\n' 'Include ~/.ssh/config.d-openstack-k8s' >> "${HOME}/.ssh/config"
  fi
else
  touch "${HOME}/.ssh/authorized_keys"
  chmod 0600 "${HOME}/.ssh/authorized_keys"
  public_key="$(cat /tmp/deployment_ed25519.pub)"
  if ! grep -qxF "${public_key}" "${HOME}/.ssh/authorized_keys"; then
    printf '%s\n' "${public_key}" >> "${HOME}/.ssh/authorized_keys"
  fi
fi
