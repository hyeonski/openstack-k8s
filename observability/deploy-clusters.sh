#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${ROOT}/scripts/lib/common.sh"
action="${1:-}"
namespace=osk8s-observability
management_kubeconfig="${STATE_DIR}/kubeconfigs/management.yaml"
workload_kubeconfig="${STATE_DIR}/kubeconfigs/${WORKLOAD_CLUSTER_NAME}.yaml"
cert_dir="${SECRET_DIR}/observability"

refresh_workload_kubeconfig() {
  local temporary="${workload_kubeconfig}.download"
  [[ -x "${STATE_DIR}/bin/clusterctl" ]] || die "clusterctl is missing"
  "${STATE_DIR}/bin/clusterctl" get kubeconfig "${WORKLOAD_CLUSTER_NAME}" \
    --namespace "${WORKLOAD_NAMESPACE}" \
    --config "${ROOT}/config/clusterctl.yaml" \
    --kubeconfig "${management_kubeconfig}" >"${temporary}"
  chmod 600 "${temporary}"
  mv "${temporary}" "${workload_kubeconfig}"
}

deploy_one() {
  local cluster="$1" kubeconfig="$2" agent_config cluster_config agent_template
  [[ -f "${kubeconfig}" ]] || die "missing kubeconfig: ${kubeconfig}"
  agent_config="${GENERATED_DIR}/otel-${cluster}-agent.yaml"
  cluster_config="${GENERATED_DIR}/otel-${cluster}-state.yaml"
  agent_template="${ROOT}/observability/k8s-agent-config.yaml.tpl"
  if [[ "${cluster}" == "${WORKLOAD_CLUSTER_NAME}" ]]; then
    agent_template="${ROOT}/observability/k8s-workload-agent-config.yaml.tpl"
  fi
  ENVIRONMENT_NAME="${ENV}" GCP_ZONE="${GCP_ZONE}" OBS_CLUSTER_NAME="${cluster}" \
    python3 "${ROOT}/scripts/render-template.py" \
      "${agent_template}" "${agent_config}"
  ENVIRONMENT_NAME="${ENV}" GCP_ZONE="${GCP_ZONE}" OBS_CLUSTER_NAME="${cluster}" \
    python3 "${ROOT}/scripts/render-template.py" \
      "${ROOT}/observability/k8s-cluster-config.yaml.tpl" "${cluster_config}"
  kubectl --kubeconfig "${kubeconfig}" create namespace "${namespace}" \
    --dry-run=client -o yaml | kubectl --kubeconfig "${kubeconfig}" apply -f - >/dev/null
  kubectl --kubeconfig "${kubeconfig}" -n "${namespace}" create configmap node-agent-config \
    --from-file="config.yaml=${agent_config}" --dry-run=client -o yaml |
    kubectl --kubeconfig "${kubeconfig}" apply -f - >/dev/null
  kubectl --kubeconfig "${kubeconfig}" -n "${namespace}" create configmap cluster-state-config \
    --from-file="config.yaml=${cluster_config}" --dry-run=client -o yaml |
    kubectl --kubeconfig "${kubeconfig}" apply -f - >/dev/null
  kubectl --kubeconfig "${kubeconfig}" -n "${namespace}" create secret generic gateway-client-tls \
    --from-file="ca.crt=${cert_dir}/ca.crt" \
    --from-file="agent.crt=${cert_dir}/agent.crt" \
    --from-file="agent.key=${cert_dir}/agent.key" --dry-run=client -o yaml |
    kubectl --kubeconfig "${kubeconfig}" apply -f - >/dev/null
  kubectl --kubeconfig "${kubeconfig}" apply -f "${ROOT}/observability/k8s-collectors.yaml" \
    --server-side --field-manager=osk8s-observability >/dev/null
  kubectl --kubeconfig "${kubeconfig}" -n "${namespace}" \
    rollout restart daemonset/node-agent deployment/cluster-state >/dev/null
  kubectl --kubeconfig "${kubeconfig}" -n "${namespace}" \
    rollout status daemonset/node-agent --timeout=5m
  kubectl --kubeconfig "${kubeconfig}" -n "${namespace}" \
    rollout status deployment/cluster-state --timeout=5m
}

case "${action}" in
  install)
    require_command kubectl
    ensure_state_dirs
    "${ROOT}/observability/deploy-hosts.sh" certs
    ensure_management_api_access
    refresh_workload_kubeconfig
    ensure_workload_api_access
    deploy_one management "${management_kubeconfig}"
    deploy_one "${WORKLOAD_CLUSTER_NAME}" "${workload_kubeconfig}"
    ;;
  status)
    require_command kubectl
    ensure_management_api_access
    ensure_workload_api_access
    for kubeconfig in "${management_kubeconfig}" "${workload_kubeconfig}"; do
      kubectl --kubeconfig "${kubeconfig}" -n "${namespace}" \
        get daemonset/node-agent deployment/cluster-state -o wide
      kubectl --kubeconfig "${kubeconfig}" -n "${namespace}" get pods -o wide
    done
    ;;
  *) die "usage: observability/deploy-clusters.sh {install|status}" ;;
esac
