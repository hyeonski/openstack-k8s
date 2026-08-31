#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

ensure_state_dirs
ensure_deployment_ssh_key
key="$(deployment_ssh_private_key)"
require_command gcloud

pubkey="$(<"${key}.pub")"
metadata_file="${SECRET_DIR}/deployment_ssh_metadata"
printf '%s:%s\n' "${TARGET_SSH_USER}" "${pubkey}" >"${metadata_file}"
chmod 600 "${metadata_file}"

while IFS= read -r node; do
  gcloud compute instances add-metadata "${node}" \
    --project="${GCP_PROJECT_ID}" \
    --zone="${GCP_ZONE}" \
    --metadata-from-file="ssh-keys=${metadata_file}" \
    --quiet
done < <(all_instance_names)

tmpkey="/tmp/openstack-k8s-deployment-key"
copy_to "${key}" "${CONTROLLER_NAME}" "${tmpkey}"
run_on "${CONTROLLER_NAME}" bash -lc \
  "umask 077; mkdir -p ~/.ssh; install -m 600 '${tmpkey}' ~/.ssh/openstack_k8s; rm -f '${tmpkey}'"

controller_ip="$(controller_ipv4)"
index=0
for compute_ip in "${COMPUTE_MANAGEMENT_IPS[@]}"; do
  compute_name="${COMPUTE_INVENTORY_NAMES[index]}"
  connected="no"
  for _attempt in {1..12}; do
    if run_on "${CONTROLLER_NAME}" ssh \
        -i "/home/${TARGET_SSH_USER}/.ssh/openstack_k8s" \
        -o BatchMode=yes \
        -o ConnectTimeout=5 \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        "${TARGET_SSH_USER}@${compute_ip}" true; then
      connected="yes"
      break
    fi
    sleep 5
  done
  [[ "${connected}" == "yes" ]] ||
    die "controller ${controller_ip} cannot authenticate to ${compute_name} (${compute_ip})"
  index=$((index + 1))
done

log "Project-scoped deployment SSH key installed and verified"
