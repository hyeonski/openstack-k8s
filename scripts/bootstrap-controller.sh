#!/usr/bin/env bash

set -Eeuo pipefail

KOLLA_VENV="${KOLLA_VENV:?}"
KOLLA_GIT_REF="${KOLLA_GIT_REF:?}"

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  gcc git libffi-dev libssl-dev python3-dev python3-pip python3-venv

if [[ ! -x "${KOLLA_VENV}/bin/kolla-ansible" ]]; then
  sudo python3 -m venv "${KOLLA_VENV}"
  sudo "${KOLLA_VENV}/bin/pip" install --upgrade pip wheel
  sudo "${KOLLA_VENV}/bin/pip" install \
    "ansible-core>=2.18,<2.19.99" \
    "git+https://opendev.org/openstack/kolla-ansible@${KOLLA_GIT_REF}"
fi

if ! "${KOLLA_VENV}/bin/pip" show \
    openstacksdk python-openstackclient >/dev/null 2>&1; then
  sudo "${KOLLA_VENV}/bin/pip" install \
    "openstacksdk>=4.7,<5" \
    "python-openstackclient>=8,<9"
fi

export PATH="${KOLLA_VENV}/bin:${PATH}"
dependency_marker="${KOLLA_VENV}/.openstack-k8s-dependencies"
if [[ ! -f "${dependency_marker}" ]]; then
  kolla-ansible install-deps
  ansible-galaxy collection install \
    -r /opt/openstack-k8s/ansible/requirements.yml
  sudo touch "${dependency_marker}"
fi

sudo install -d -o "${USER}" -g "$(id -gn)" -m 0750 /etc/kolla
