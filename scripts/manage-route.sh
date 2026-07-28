#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

action="${1:-}"
[[ "${action}" == "add" || "${action}" == "delete" ]] ||
  die "usage: $0 add|delete"

if ! instance_running "${CONTROLLER_NAME}"; then
  [[ "${action}" == "delete" ]] && exit 0
  die "controller instance is not running"
fi

ensure_state_dirs
route_state="${STATE_DIR}/route-gateway"
gateway="$(controller_ipv4)"
if [[ -z "${gateway}" && "${action}" == "delete" && -f "${route_state}" ]]; then
  gateway="$(<"${route_state}")"
fi
if [[ -z "${gateway}" ]]; then
  if [[ "${action}" == "delete" ]]; then
    log "Controller has no management IP and no project route was recorded"
    exit 0
  fi
  die "unable to determine controller management IP"
fi

route_info="$(route -n get "${EXTERNAL_ALLOCATION_POOL_START}" 2>/dev/null || true)"
route_gateway="$(awk '/gateway:/{print $2; exit}' <<<"${route_info}")"
route_destination="$(awk '/destination:/{print $2; exit}' <<<"${route_info}")"

case "${action}" in
  add)
    if [[ "${route_gateway}" == "${gateway}" ]]; then
      log "Floating IP route already installed"
      exit 0
    fi
    if [[ -n "${route_destination}" &&
          "${route_destination}" != "default" &&
          "${route_gateway}" != "${gateway}" ]]; then
      die "refusing to replace existing route via ${route_gateway}"
    fi
    run_host_as_root route -n add -net "${EXTERNAL_CIDR}" "${gateway}"
    printf '%s\n' "${gateway}" > "${route_state}"
    chmod 600 "${route_state}"
    ;;
  delete)
    if [[ "${route_destination}" != "default" &&
          "${route_gateway}" == "${gateway}" ]]; then
      run_host_as_root route -n delete -net "${EXTERNAL_CIDR}" "${gateway}"
      rm -f "${route_state}"
    else
      log "No project-owned Floating IP route to remove"
      rm -f "${route_state}"
    fi
    ;;
esac
