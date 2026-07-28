#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

run_dir="$(start_run)"
report="${run_dir}/preflight.txt"
exec 3>&1 4>&2
exec >"${report}" 2>&1
show_report() {
  local result="$?"
  cat "${report}" >&3
  trap - EXIT
  exit "${result}"
}
trap show_report EXIT

log "Environment: ${ENV}"
log "Project root: ${PROJECT_ROOT}"

[[ "$(uname -s)" == "Darwin" ]] || die "local-arm64 profile requires macOS"
[[ "$(uname -m)" == "arm64" ]] || die "local-arm64 profile requires an arm64 Mac"

require_command python3
require_command git
require_command make

if command -v sysctl >/dev/null 2>&1; then
  memory_bytes="$(sysctl -n hw.memsize 2>/dev/null || true)"
  if [[ "${memory_bytes}" =~ ^[0-9]+$ ]]; then
    memory_gib="$((memory_bytes / 1024 / 1024 / 1024))"
    log "Host memory: ${memory_gib} GiB"
    (( memory_gib >= 16 )) || die "at least 16 GiB host memory is required"
  else
    warn "unable to read host memory"
  fi
fi

available_kib="$(df -Pk "${PROJECT_ROOT}" | awk 'NR==2 {print $4}')"
required_kib="$((120 * 1024 * 1024))"
log "Available disk: $((available_kib / 1024 / 1024)) GiB"
(( available_kib >= required_kib )) || die "at least 120 GiB free disk is required"

if "${PROJECT_ROOT}/scripts/check-cidr-overlap.py" "${MANAGEMENT_CIDR}" "${EXTERNAL_CIDR}"; then
  log "Requested networks do not overlap configured host interfaces"
else
  if command -v limactl >/dev/null 2>&1 &&
     lima_network_exists "${LIMA_NETWORK_NAME}"; then
    warn "management CIDR is already configured by the expected Lima network"
    "${PROJECT_ROOT}/scripts/check-cidr-overlap.py" "${EXTERNAL_CIDR}"
  else
    die "network overlap detected; choose different CIDRs before continuing"
  fi
fi

if command -v brew >/dev/null 2>&1; then
  log "Homebrew: $(brew --prefix)"
else
  die "Homebrew is required for the approved host setup"
fi

if command -v limactl >/dev/null 2>&1; then
  log "Lima: $(limactl --version)"
  if lima_network_exists "${LIMA_NETWORK_NAME}"; then
    actual_dhcp_end="$(
      limactl network list --json |
        python3 -c '
import json, sys
target = sys.argv[1]
for line in sys.stdin:
    item = json.loads(line)
    if item.get("name") == target:
        print(item.get("dhcpEnd", ""))
        break
' "${LIMA_NETWORK_NAME}"
    )"
    [[ "${actual_dhcp_end}" == "${MANAGEMENT_DHCP_END}" ]] ||
      die "${LIMA_NETWORK_NAME} DHCP end is not ${MANAGEMENT_DHCP_END}"
  fi
else
  warn "Lima is not installed; run 'make host-setup ENV=${ENV}'"
fi

if [[ -x /opt/socket_vmnet/bin/socket_vmnet ]]; then
  owner="$(stat -f '%Su:%Sg' /opt/socket_vmnet/bin/socket_vmnet)"
  log "socket_vmnet: installed (${owner})"
  [[ "${owner%%:*}" == "root" ]] || die "socket_vmnet is not root-owned"
else
  warn "socket_vmnet is not installed in /opt/socket_vmnet"
fi

if [[ -f /private/etc/sudoers.d/lima ]]; then
  log "Lima sudoers: installed"
  [[ -r /private/etc/sudoers.d/lima ]] ||
    die "Lima sudoers exists but is not readable by the current user"
else
  warn "Lima sudoers is not installed"
fi

if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    log "Docker: running"
  else
    warn "Docker CLI exists but the daemon is not running; only needed for CAPO network probe"
  fi
else
  warn "Docker is not installed; only needed for the later CAPO network probe"
fi

log "Read-only preflight completed"
