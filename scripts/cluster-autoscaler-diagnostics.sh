#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

reason="${1:-manual}"
[[ "${reason}" =~ ^[a-z0-9-]+$ ]] || die "invalid diagnostic reason: ${reason}"

management_kubeconfig="${STATE_DIR}/kubeconfigs/management.yaml"
workload_kubeconfig="${STATE_DIR}/kubeconfigs/${WORKLOAD_CLUSTER_NAME}.yaml"
run_dir="$(current_or_new_run)"
status_dir="${run_dir}/m3/diagnostics/$(utc_timestamp)-${reason}"
mkdir -p "${status_dir}"
chmod 700 "${status_dir}"

redact_file() {
  local path="$1"
  local temporary="${path}.redacted"
  "${PROJECT_ROOT}/scripts/redact-output.py" <"${path}" >"${temporary}"
  chmod 600 "${temporary}"
  mv "${temporary}" "${path}"
}

if [[ -f "${management_kubeconfig}" ]]; then
  kubectl --kubeconfig "${management_kubeconfig}" -n "${CLUSTER_AUTOSCALER_NAMESPACE}" \
    get deployment,pods -o wide >"${status_dir}/autoscaler-resources.txt" 2>&1 || true
  kubectl --kubeconfig "${management_kubeconfig}" -n "${CLUSTER_AUTOSCALER_NAMESPACE}" \
    describe deployment cluster-autoscaler >"${status_dir}/autoscaler-deployment.txt" 2>&1 || true
  kubectl --kubeconfig "${management_kubeconfig}" -n "${CLUSTER_AUTOSCALER_NAMESPACE}" \
    logs deployment/cluster-autoscaler --all-containers=true --tail=2000 \
    >"${status_dir}/autoscaler.log" 2>&1 || true
  kubectl --kubeconfig "${management_kubeconfig}" -n "${CLUSTER_AUTOSCALER_NAMESPACE}" \
    get events --sort-by=.lastTimestamp >"${status_dir}/autoscaler-events.txt" 2>&1 || true
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" get \
    clusters,machinedeployments,machines,machinesets,kubeadmcontrolplanes,openstackclusters,openstackmachines \
    -o wide >"${status_dir}/capi-resources.txt" 2>&1 || true
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    get events --sort-by=.lastTimestamp >"${status_dir}/capi-events.txt" 2>&1 || true
fi

if [[ -f "${workload_kubeconfig}" ]]; then
  kubectl --kubeconfig "${workload_kubeconfig}" get nodes -o wide \
    >"${status_dir}/workload-nodes.txt" 2>&1 || true
  kubectl --kubeconfig "${workload_kubeconfig}" get pods -A -o wide \
    >"${status_dir}/workload-pods.txt" 2>&1 || true
  kubectl --kubeconfig "${workload_kubeconfig}" get events -A \
    --sort-by=.lastTimestamp >"${status_dir}/workload-events.txt" 2>&1 || true
  kubectl --kubeconfig "${workload_kubeconfig}" -n "${CLUSTER_AUTOSCALER_TEST_NAMESPACE}" \
    get pods -l "app.kubernetes.io/name=${CLUSTER_AUTOSCALER_TEST_NAME}" -o yaml \
    >"${status_dir}/test-pods.yaml" 2>&1 || true
  kubectl --kubeconfig "${workload_kubeconfig}" -n kube-system \
    get configmap cluster-autoscaler-status -o yaml \
    >"${status_dir}/autoscaler-status-configmap.yaml" 2>&1 || true
fi

# Reuse the established CAPI/Nova/guest/compute collector. It captures Nova
# show/console, Calico logs, bootstrap services and host pressure under the
# same run and applies the existing bounded redaction policy.
"${PROJECT_ROOT}/scripts/workload-diagnostics.sh" "m3-${reason}" \
  >"${status_dir}/workload-diagnostics.stdout" 2>&1 || true

while IFS= read -r path; do
  redact_file "${path}"
done < <(find "${status_dir}" -maxdepth 1 -type f -print)
chmod -R go-rwx "${status_dir}"
warn "Cluster Autoscaler diagnostics preserved at ${status_dir}"
