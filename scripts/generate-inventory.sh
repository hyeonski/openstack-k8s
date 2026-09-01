#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

require_command gcloud
require_command python3
instance_running "${CONTROLLER_NAME}" || die "controller is not running"
for compute_name in "${COMPUTE_NAMES[@]}"; do
  instance_running "${compute_name}" || die "${compute_name} is not running"
done
ensure_state_dirs

host_keys=(controller "${COMPUTE_INVENTORY_NAMES[@]}")
host_ips=()
while IFS= read -r host_ip; do
  host_ips+=("${host_ip}")
done < <(
  run_gcp_iac output -state="${IAC_STATE_FILE}" -json host_internal_ips |
    python3 "${PROJECT_ROOT}/scripts/parse-iac-host-ips.py" "${host_keys[@]}"
)
[[ "${#host_ips[@]}" -eq "${#host_keys[@]}" ]] ||
  die "OpenTofu host outputs are missing; apply or import the GCP foundation first"
controller_ip="${host_ips[0]}"
compute_ips=("${host_ips[@]:1}")
[[ "${#compute_ips[@]}" -eq "${#COMPUTE_NAMES[@]}" ]] ||
  die "compute name and management IP counts differ"
[[ "${#COMPUTE_INVENTORY_NAMES[@]}" -eq "${#COMPUTE_NAMES[@]}" ]] ||
  die "compute name and inventory name counts differ"
[[ "${#COMPUTE_NODE_HOSTNAMES[@]}" -eq "${#COMPUTE_NAMES[@]}" ]] ||
  die "compute name and node hostname counts differ"

inventory_dir="${PROJECT_ROOT}/ansible/inventory/${ENV}"
mkdir -p "${inventory_dir}"
inventory="${inventory_dir}/generated-hosts.ini"

inventory_args=(
  "${PROJECT_ROOT}/scripts/build-ansible-inventory.py"
  "${inventory}"
  --controller-ip "${controller_ip}"
  --controller-hostname "${CONTROLLER_NAME}"
  --user "${TARGET_SSH_USER}"
)
compute_specs=()
for ((index = 0; index < ${#COMPUTE_NAMES[@]}; index++)); do
  inventory_args+=(
    --compute
    "${COMPUTE_INVENTORY_NAMES[index]},${compute_ips[index]},${COMPUTE_NODE_HOSTNAMES[index]}"
  )
  compute_specs+=("${COMPUTE_INVENTORY_NAMES[index]}=${compute_ips[index]}")
done
python3 "${inventory_args[@]}"

cp "${inventory}" "${GENERATED_DIR}/generated-hosts.ini"
chmod 600 "${GENERATED_DIR}/generated-hosts.ini"

cat > "${GENERATED_DIR}/addresses.env" <<EOF
CONTROLLER_MANAGEMENT_IP="${controller_ip}"
COMPUTE_MANAGEMENT_IPS="${compute_ips[*]}"
COMPUTE_INVENTORY_SPECS="${compute_specs[*]}"
EOF
chmod 600 "${GENERATED_DIR}/addresses.env"

log "Inventory generated: controller=${controller_ip}, computes=${compute_ips[*]}"
