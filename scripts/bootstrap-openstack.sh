#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

[[ -f "${SECRET_DIR}/clouds.yaml" ]] ||
  die "admin clouds.yaml is missing; run make openstack-post-deploy"

instance_running "${CONTROLLER_NAME}" || die "controller is not running"
scripts/sync-to-controller.sh

run_on "${CONTROLLER_NAME}" env \
  KOLLA_DEPLOY_DIR="${KOLLA_DEPLOY_DIR}" \
  CIRROS_IMAGE_URL="${CIRROS_IMAGE_URL}" \
  CIRROS_SHA256_URL="${CIRROS_SHA256_URL}" \
  UBUNTU_IMAGE_URL="${UBUNTU_IMAGE_URL}" \
  UBUNTU_SHA256_URL="${UBUNTU_SHA256_URL}" \
  bash "${KOLLA_DEPLOY_DIR}/scripts/prepare-images.sh"

run_on "${CONTROLLER_NAME}" bash -lc '
  set -Eeuo pipefail
  secret_file="/etc/kolla/capi-test-user.env"
  if [[ ! -s "${secret_file}" ]]; then
    umask 077
    printf "OPENSTACK_TEST_PASSWORD=%q\n" \
      "$(openssl rand -base64 36 | tr -d "\n")" > "${secret_file}"
  fi
'

environment_names=(
  OPENSTACK_TEST_PROJECT OPENSTACK_TEST_USER
  EXTERNAL_NETWORK_NAME EXTERNAL_PHYSNET EXTERNAL_CIDR EXTERNAL_GATEWAY
  EXTERNAL_ALLOCATION_POOL_START EXTERNAL_ALLOCATION_POOL_END
  TENANT_NETWORK_NAME TENANT_SUBNET_NAME TENANT_ROUTER_NAME
  TENANT_CIDR TENANT_GATEWAY
  OPENSTACK_TEST_FLAVOR OPENSTACK_TEST_FLAVOR_VCPUS
  OPENSTACK_TEST_FLAVOR_RAM_MB OPENSTACK_TEST_FLAVOR_DISK_GB
  KUBERNETES_CONTROL_PLANE_FLAVOR KUBERNETES_CONTROL_PLANE_VCPUS
  KUBERNETES_CONTROL_PLANE_RAM_MB KUBERNETES_CONTROL_PLANE_DISK_GB
  KUBERNETES_WORKER_FLAVOR KUBERNETES_WORKER_VCPUS
  KUBERNETES_WORKER_RAM_MB KUBERNETES_WORKER_DISK_GB
  CIRROS_IMAGE_NAME CIRROS_VERSION UBUNTU_IMAGE_NAME KOLLA_DEPLOY_DIR
)
remote_exports=()
for name in "${environment_names[@]}"; do
  printf -v escaped '%q' "${!name}"
  remote_exports+=("export ${name}=${escaped};")
done

run_on "${CONTROLLER_NAME}" bash -lc "
  set -Eeuo pipefail
  source /etc/kolla/capi-test-user.env
  # Ansible's lookup('env', ...) reads the child-process environment.  A
  # sourced shell variable is not inherited unless it is explicitly exported.
  export OPENSTACK_TEST_PASSWORD
  export OS_CLIENT_CONFIG_FILE=/etc/kolla/clouds.yaml
  export ANSIBLE_CONFIG=${KOLLA_DEPLOY_DIR}/ansible/ansible.cfg
  ${remote_exports[*]}
  source ${KOLLA_VENV}/bin/activate
  ansible-playbook ${KOLLA_DEPLOY_DIR}/ansible/playbooks/bootstrap-openstack.yml
"

run_on "${CONTROLLER_NAME}" env \
  OPENSTACK_TEST_PROJECT="${OPENSTACK_TEST_PROJECT}" \
  OPENSTACK_TEST_USER="${OPENSTACK_TEST_USER}" \
  KOLLA_INTERNAL_VIP_ADDRESS="${KOLLA_INTERNAL_VIP_ADDRESS}" \
  TARGET_SSH_USER="${TARGET_SSH_USER}" \
  WORKLOAD_SSH_KEY_NAME="${WORKLOAD_SSH_KEY_NAME}" \
  bash -lc '
    set -Eeuo pipefail
    source /etc/kolla/capi-test-user.env
    export OS_AUTH_URL="http://${KOLLA_INTERNAL_VIP_ADDRESS}:5000/v3"
    export OS_AUTH_TYPE=v3password
    export OS_USERNAME="${OPENSTACK_TEST_USER}"
    export OS_PASSWORD="${OPENSTACK_TEST_PASSWORD}"
    export OS_PROJECT_NAME="${OPENSTACK_TEST_PROJECT}"
    export OS_USER_DOMAIN_NAME=Default
    export OS_PROJECT_DOMAIN_NAME=Default
    export OS_IDENTITY_API_VERSION=3
    source /opt/kolla-venv/bin/activate

    credential_name="capi-${OPENSTACK_TEST_PROJECT}"
    if [[ ! -s /etc/kolla/capi-clouds.yaml ]]; then
      if openstack application credential show "${credential_name}" \
          >/dev/null 2>&1; then
        openstack application credential delete "${credential_name}"
      fi
      secret="$(openssl rand -base64 48 | tr -d "\n")"
      id="$(openstack application credential create \
        --secret "${secret}" --restricted \
        -f value -c id "${credential_name}")"
      umask 077
      {
        echo "clouds:"
        echo "  capi:"
        echo "    auth_type: v3applicationcredential"
        echo "    auth:"
        echo "      auth_url: ${OS_AUTH_URL}"
        echo "      application_credential_id: ${id}"
        echo "      application_credential_secret: ${secret}"
      } > /etc/kolla/capi-clouds.yaml
      chmod 0600 /etc/kolla/capi-clouds.yaml
    fi

    # Environment variables take precedence over clouds.yaml. Clear the
    # password-auth context before validating the application credential so
    # keystoneauth selects v3applicationcredential instead of Password.
    unset OS_AUTH_URL OS_AUTH_TYPE OS_USERNAME OS_PASSWORD OS_PROJECT_NAME
    unset OS_USER_DOMAIN_NAME OS_PROJECT_DOMAIN_NAME OS_IDENTITY_API_VERSION
    export OS_CLIENT_CONFIG_FILE=/etc/kolla/capi-clouds.yaml
    openstack --os-cloud capi token issue >/dev/null

    # Reuse the project-scoped deployment key for failure diagnostics. The
    # private key remains on the controller; only its public half is stored in
    # Nova. Refuse a same-name/different-key collision instead of replacing it.
    deployment_key="/home/${TARGET_SSH_USER}/.ssh/openstack_k8s"
    [[ -s "${deployment_key}" ]] || {
      echo "project deployment SSH key is missing on the controller" >&2
      exit 1
    }
    public_key_file="$(mktemp)"
    trap '\''rm -f "${public_key_file}"'\'' EXIT
    ssh-keygen -y -f "${deployment_key}" >"${public_key_file}"
    chmod 0600 "${public_key_file}"
    expected_key="$(awk '\''{print $1 " " $2}'\'' "${public_key_file}")"
    if openstack --os-cloud capi keypair show "${WORKLOAD_SSH_KEY_NAME}" \
        >/dev/null 2>&1; then
      actual_key="$(openstack --os-cloud capi keypair show \
        -f value -c public_key "${WORKLOAD_SSH_KEY_NAME}" |
        awk '\''{print $1 " " $2}'\'')"
      [[ "${actual_key}" == "${expected_key}" ]] || {
        echo "existing workload SSH keypair does not match the project key" >&2
        exit 1
      }
    else
      openstack --os-cloud capi keypair create \
        --public-key "${public_key_file}" "${WORKLOAD_SSH_KEY_NAME}" >/dev/null
    fi
  '

temporary="/tmp/openstack-k8s-capi-clouds.yaml"
run_on "${CONTROLLER_NAME}" sudo install -o "${TARGET_SSH_USER}" \
  -g "${TARGET_SSH_USER}" -m 0600 /etc/kolla/capi-clouds.yaml "${temporary}"
limactl copy "${CONTROLLER_NAME}:${temporary}" "${SECRET_DIR}/capi-clouds.yaml"
run_on "${CONTROLLER_NAME}" rm -f "${temporary}"
chmod 600 "${SECRET_DIR}/capi-clouds.yaml"

log "Persistent OpenStack resources and CAPO application credential are ready"
