#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

mode="${1:-full}"
case "${mode}" in
  full|inputs-only) ;;
  *) die "usage: sync-to-controller.sh [full|inputs-only]" ;;
esac

require_command rsync
instance_running "${CONTROLLER_NAME}" || die "controller is not running"
for compute_name in "${COMPUTE_NAMES[@]}"; do
  instance_running "${compute_name}" || die "${compute_name} is not running"
done
ensure_state_dirs

require_command gcloud
require_command tar
temporary_directory="$(mktemp -d)"
archive="${temporary_directory}/openstack-k8s-sync.tar.gz"
remote_archive="/tmp/openstack-k8s-sync.tar.gz"
cleanup() {
  rm -rf "${temporary_directory}"
}
trap cleanup EXIT

COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata \
  --exclude='scripts/__pycache__' \
  -C "${PROJECT_ROOT}" -czf "${archive}" \
  ansible/ansible.cfg \
  ansible/files \
  ansible/inventory/cloud-gcp-amd64/generated-hosts.ini \
  ansible/playbooks \
  ansible/requirements.yml \
  ansible/templates \
  config/clusterctl.yaml \
  config/environments/cloud-gcp-amd64.env \
  kolla/globals-cloud-gcp-amd64.yml.tpl \
  openstack \
  scripts
copy_to "${archive}" "${CONTROLLER_NAME}" "${remote_archive}"
run_on "${CONTROLLER_NAME}" env \
  KOLLA_DEPLOY_DIR="${KOLLA_DEPLOY_DIR}" \
  TARGET_SSH_USER="${TARGET_SSH_USER}" \
  REMOTE_ARCHIVE="${remote_archive}" \
  bash -lc '
      set -Eeuo pipefail
      staging="$(mktemp -d)"
      cleanup() {
        rm -rf "${staging}"
        rm -f "${REMOTE_ARCHIVE}"
      }
      trap cleanup EXIT
      tar -xzf "${REMOTE_ARCHIVE}" -C "${staging}"
      sudo install -d -o "${TARGET_SSH_USER}" -g "${TARGET_SSH_USER}" \
        -m 0755 "${KOLLA_DEPLOY_DIR}"
      for component in ansible config kolla openstack scripts; do
        install -d -m 0755 "${KOLLA_DEPLOY_DIR}/${component}"
        rsync -a --delete --delete-excluded --exclude '__pycache__/' \
          "${staging}/${component}/" \
          "${KOLLA_DEPLOY_DIR}/${component}/"
      done
      rm -f \
        "${KOLLA_DEPLOY_DIR}/cache/images/cirros-aarch64.img" \
        "${KOLLA_DEPLOY_DIR}/cache/images/ubuntu-24.04-arm64.img"
    '

"${PROJECT_ROOT}/scripts/setup-project-ssh.sh"

if [[ "${mode}" == "inputs-only" ]]; then
  log "Deployment inputs synchronized without installing Kolla"
  exit 0
fi

run_on "${CONTROLLER_NAME}" env \
  KOLLA_VENV="${KOLLA_VENV}" \
  KOLLA_GIT_URL="${KOLLA_GIT_URL}" \
  KOLLA_GIT_REF="${KOLLA_GIT_REF}" \
  KOLLA_COLLECTION_GIT_URL="${KOLLA_COLLECTION_GIT_URL}" \
  KOLLA_COLLECTION_GIT_REF="${KOLLA_COLLECTION_GIT_REF}" \
  bash "${KOLLA_DEPLOY_DIR}/scripts/bootstrap-controller.sh"

log "Deployment inputs synchronized to controller"
