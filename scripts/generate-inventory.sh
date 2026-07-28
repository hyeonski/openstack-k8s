#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

require_command limactl
instance_running "${CONTROLLER_NAME}" || die "controller is not running"
instance_running "${COMPUTE_NAME}" || die "compute is not running"
ensure_state_dirs

controller_ip="$(controller_ipv4)"
compute_ip="$(compute_ipv4)"
[[ -n "${controller_ip}" && -n "${compute_ip}" ]] ||
  die "unable to discover management IPs"

inventory_dir="${PROJECT_ROOT}/ansible/inventory/${ENV}"
mkdir -p "${inventory_dir}"
inventory="${inventory_dir}/generated-hosts.ini"

python3 - "${inventory}" "${controller_ip}" "${compute_ip}" \
  "${TARGET_SSH_USER}" <<'PY'
from pathlib import Path
import os
import sys

destination, controller_ip, compute_ip, user = sys.argv[1:]
key = f"/home/{user}/.ssh/openstack_k8s"
content = f"""[all]
controller ansible_host={controller_ip} ansible_connection=local ansible_python_interpreter=/usr/bin/python3
compute01 ansible_host={compute_ip} ansible_user={user} ansible_become=true ansible_private_key_file={key} ansible_python_interpreter=/usr/bin/python3

[control]
controller

[network]
controller

[compute]
compute01

[monitoring]
controller

[storage]
"""
path = Path(destination)
path.write_text(content, encoding="utf-8")
os.chmod(path, 0o600)
PY

cp "${inventory}" "${GENERATED_DIR}/generated-hosts.ini"
chmod 600 "${GENERATED_DIR}/generated-hosts.ini"

cat > "${GENERATED_DIR}/addresses.env" <<EOF
CONTROLLER_MANAGEMENT_IP="${controller_ip}"
COMPUTE_MANAGEMENT_IP="${compute_ip}"
EOF
chmod 600 "${GENERATED_DIR}/addresses.env"

log "Inventory generated: controller=${controller_ip}, compute=${compute_ip}"
