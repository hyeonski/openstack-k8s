#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

[[ "${HOST_PROVIDER}" == "gcp" ]] ||
  die "GCP workload API tunnel requires a GCP profile"
require_command gcloud
require_command kubectl
require_command nc
require_command ps

action="${1:-}"
management_kubeconfig="${STATE_DIR}/kubeconfigs/management.yaml"
workload_kubeconfig="${STATE_DIR}/kubeconfigs/${WORKLOAD_CLUSTER_NAME}.yaml"
tunnel_pid_file="${STATE_DIR}/workload-api-iap-tunnel.pid"
tunnel_log="${STATE_DIR}/workload-api-iap-tunnel.log"

managed_tunnel_process() {
  [[ -f "${tunnel_pid_file}" ]] || return 1
  local pid
  pid="$(<"${tunnel_pid_file}")"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  kill -0 "${pid}" 2>/dev/null || return 1
  ps -p "${pid}" -o command= 2>/dev/null |
    grep -Fq "127.0.0.1:${WORKLOAD_LOCAL_API_PORT}"
}

stop_tunnel() {
  if managed_tunnel_process; then
    local pid
    pid="$(<"${tunnel_pid_file}")"
    kill "${pid}" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 "${pid}" 2>/dev/null || break
      sleep 0.25
    done
  fi
  rm -f "${tunnel_pid_file}"
}

control_plane_endpoint() {
  kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${WORKLOAD_NAMESPACE}" get cluster "${WORKLOAD_CLUSTER_NAME}" \
    -o jsonpath='{.spec.controlPlaneEndpoint.host}'
}

rewrite_kubeconfig() {
  local endpoint="$1" current_context cluster_name
  current_context="$(kubectl --kubeconfig "${workload_kubeconfig}" config current-context)"
  cluster_name="$(
    kubectl --kubeconfig "${workload_kubeconfig}" config view -o json |
      python3 -c '
import json, sys
data = json.load(sys.stdin)
current = sys.argv[1]
for context in data.get("contexts", []):
    if context.get("name") == current:
        print(context["context"]["cluster"])
        break
else:
    raise SystemExit("current kubeconfig context has no cluster")
' "${current_context}"
  )"
  kubectl --kubeconfig "${workload_kubeconfig}" config set-cluster \
    "${cluster_name}" \
    --server="https://127.0.0.1:${WORKLOAD_LOCAL_API_PORT}" \
    --tls-server-name="${endpoint}" >/dev/null
  chmod 600 "${workload_kubeconfig}"
}

start_tunnel() {
  [[ -f "${management_kubeconfig}" ]] ||
    die "management kubeconfig is missing"
  [[ -f "${workload_kubeconfig}" ]] ||
    die "workload kubeconfig is missing"
  ensure_management_api_access

  local endpoint pid options=() option
  endpoint="$(control_plane_endpoint)"
  [[ -n "${endpoint}" ]] || die "workload control plane endpoint is empty"

  if managed_tunnel_process &&
      nc -z 127.0.0.1 "${WORKLOAD_LOCAL_API_PORT}" 2>/dev/null; then
    rewrite_kubeconfig "${endpoint}"
    return
  fi
  stop_tunnel
  if nc -z 127.0.0.1 "${WORKLOAD_LOCAL_API_PORT}" 2>/dev/null; then
    die "local port ${WORKLOAD_LOCAL_API_PORT} is already used by another process"
  fi

  while IFS= read -r option; do
    options+=("${option}")
  done < <(gcp_ssh_options)
  nohup gcloud compute ssh "${TARGET_SSH_USER}@${CONTROLLER_NAME}" \
    "${options[@]}" -- \
    -N -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -L "127.0.0.1:${WORKLOAD_LOCAL_API_PORT}:${endpoint}:6443" \
    >"${tunnel_log}" 2>&1 </dev/null &
  pid="$!"
  printf '%s\n' "${pid}" >"${tunnel_pid_file}"
  chmod 600 "${tunnel_pid_file}" "${tunnel_log}"

  for _ in {1..60}; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      sed -n '1,120p' "${tunnel_log}" >&2 || true
      die "workload API IAP SSH tunnel exited"
    fi
    if nc -z 127.0.0.1 "${WORKLOAD_LOCAL_API_PORT}" 2>/dev/null; then
      rewrite_kubeconfig "${endpoint}"
      log "Workload API IAP SSH tunnel is ready on 127.0.0.1:${WORKLOAD_LOCAL_API_PORT} for ${endpoint}:6443"
      return
    fi
    sleep 1
  done
  stop_tunnel
  die "workload API IAP SSH tunnel did not become ready"
}

case "${action}" in
  ensure) start_tunnel ;;
  stop) stop_tunnel ;;
  *) die "usage: gcp-workload-api-tunnel.sh {ensure|stop}" ;;
esac
