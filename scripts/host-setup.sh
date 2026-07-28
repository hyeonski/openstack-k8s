#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

[[ "$(uname -s)" == "Darwin" ]] || die "host setup is macOS-only"
require_command brew
require_command git
require_command make

if [[ "${CONFIRM_HOST_SETUP:-}" != "YES" ]]; then
  if [[ -t 0 ]]; then
    echo "This will install Lima, root-owned socket_vmnet, and a restricted Lima sudoers file."
    read -r -p "Type YES to continue: " answer
    [[ "${answer}" == "YES" ]] || die "host setup cancelled"
  else
    die "set CONFIRM_HOST_SETUP=YES for non-interactive host setup"
  fi
fi

if ! command -v limactl >/dev/null 2>&1; then
  log "Installing Lima with Homebrew"
  brew install lima
else
  log "Lima already installed: $(limactl --version)"
fi

if [[ ! -x /opt/socket_vmnet/bin/socket_vmnet ]]; then
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "${tmpdir}"' EXIT
  log "Building socket_vmnet ${SOCKET_VMNET_VERSION}"
  git clone --depth 1 --branch "${SOCKET_VMNET_VERSION}" \
    https://github.com/lima-vm/socket_vmnet.git "${tmpdir}/socket_vmnet"
  make -C "${tmpdir}/socket_vmnet"
  run_host_as_root make -C "${tmpdir}/socket_vmnet" \
    PREFIX=/opt/socket_vmnet install.bin
else
  log "socket_vmnet already installed"
fi

[[ "$(stat -f '%Su' /opt/socket_vmnet/bin/socket_vmnet)" == "root" ]] ||
  die "/opt/socket_vmnet/bin/socket_vmnet must be root-owned"

if ! lima_network_exists "${LIMA_NETWORK_NAME}"; then
  log "Creating Lima network ${LIMA_NETWORK_NAME} (${MANAGEMENT_GATEWAY_CIDR})"
  limactl network create "${LIMA_NETWORK_NAME}" \
    --mode shared \
    --gateway "${MANAGEMENT_GATEWAY_CIDR}"
fi
"${PROJECT_ROOT}/scripts/configure-lima-network.rb" \
  "${HOME}/.lima/_config/networks.yaml" \
  "${LIMA_NETWORK_NAME}" "${MANAGEMENT_DHCP_END}"

sudoers_tmp="$(mktemp)"
trap 'rm -f "${sudoers_tmp}"; [[ -n "${tmpdir:-}" ]] && rm -rf "${tmpdir}"' EXIT
limactl sudoers > "${sudoers_tmp}"
run_host_as_root visudo -cf "${sudoers_tmp}"
run_host_as_root install -o root -g admin -m 0440 \
  "${sudoers_tmp}" /private/etc/sudoers.d/lima
run_host_as_root visudo -cf /private/etc/sudoers.d/lima

log "Host prerequisites installed. Run 'make preflight ENV=${ENV}'."
