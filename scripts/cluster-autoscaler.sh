#!/usr/bin/env bash

set -Eeuo pipefail
umask 077
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
set -a
source "${PROJECT_ROOT}/scripts/lib/common.sh"
set +a

action="${1:-}"
[[ "${CLUSTER_AUTOSCALER_NODE_GROUP_MIN_SIZE}:${CLUSTER_AUTOSCALER_NODE_GROUP_MAX_SIZE}" == "1:3" ]] ||
  die "ADR-0016 requires the fixed worker range 1:3"
management_kubeconfig="${STATE_DIR}/kubeconfigs/management.yaml"
workload_kubeconfig="${STATE_DIR}/kubeconfigs/${WORKLOAD_CLUSTER_NAME}.yaml"
machine_deployment="${WORKLOAD_CLUSTER_NAME}-md-0"
manifest_root="${PROJECT_ROOT}/kubernetes/cluster-autoscaler"
management_template="${manifest_root}/management.yaml.tpl"
workload_rbac_template="${manifest_root}/workload-rbac.yaml.tpl"
management_manifest="${GENERATED_DIR}/cluster-autoscaler-management.yaml"
workload_rbac_manifest="${GENERATED_DIR}/cluster-autoscaler-workload-rbac.yaml"
credential_temp_dir=""

cleanup_credential_temp() {
  if [[ -z "${credential_temp_dir}" ]]; then
    return 0
  fi
  rm -f "${credential_temp_dir}/ca.crt" "${credential_temp_dir}/kubeconfig"
  rmdir "${credential_temp_dir}" 2>/dev/null || true
}
trap cleanup_credential_temp EXIT

capture_failure() {
  local reason="$1"
  "${PROJECT_ROOT}/scripts/cluster-autoscaler-diagnostics.sh" "${reason}" ||
    warn "one or more M3 diagnostic collectors failed; partial evidence was preserved"
}

require_context() {
  require_command kubectl
  require_command gcloud
  ensure_management_api_access
  require_command python3
  require_command base64
  [[ -f "${management_kubeconfig}" ]] || die "management kubeconfig is missing"
  [[ -f "${workload_kubeconfig}" ]] || die "workload kubeconfig is missing"
  ensure_workload_api_access
  kubectl --kubeconfig "${management_kubeconfig}" get --raw=/readyz >/dev/null
  kubectl --kubeconfig "${workload_kubeconfig}" get --raw=/readyz >/dev/null
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    get machinedeployment "${machine_deployment}" >/dev/null
}

render_base_manifests() {
  ensure_state_dirs
  CLUSTER_AUTOSCALER_NAMESPACE="${CLUSTER_AUTOSCALER_NAMESPACE}" \
  CLUSTER_AUTOSCALER_SERVICE_ACCOUNT="${CLUSTER_AUTOSCALER_SERVICE_ACCOUNT}" \
  CLUSTER_AUTOSCALER_WORKLOAD_NAMESPACE="${CLUSTER_AUTOSCALER_WORKLOAD_NAMESPACE}" \
  CLUSTER_AUTOSCALER_WORKLOAD_TOKEN_SECRET="${CLUSTER_AUTOSCALER_WORKLOAD_TOKEN_SECRET}" \
    "${PROJECT_ROOT}/scripts/render-template.py" \
      "${workload_rbac_template}" "${workload_rbac_manifest}"
  CLUSTER_AUTOSCALER_NAMESPACE="${CLUSTER_AUTOSCALER_NAMESPACE}" \
  CLUSTER_AUTOSCALER_SERVICE_ACCOUNT="${CLUSTER_AUTOSCALER_SERVICE_ACCOUNT}" \
  CLUSTER_AUTOSCALER_WORKLOAD_KUBECONFIG_SECRET="${CLUSTER_AUTOSCALER_WORKLOAD_KUBECONFIG_SECRET}" \
  CLUSTER_AUTOSCALER_IMAGE="${CLUSTER_AUTOSCALER_IMAGE}" \
  WORKLOAD_NAMESPACE="${WORKLOAD_NAMESPACE}" \
  WORKLOAD_CLUSTER_NAME="${WORKLOAD_CLUSTER_NAME}" \
    "${PROJECT_ROOT}/scripts/render-template.py" \
      "${management_template}" "${management_manifest}"
}

create_workload_kubeconfig_secret() {
  local server endpoint port token ca_file kubeconfig_file attempts attempt
  kubectl --kubeconfig "${workload_kubeconfig}" apply -f "${workload_rbac_manifest}" >/dev/null
  attempts=60
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    token="$(kubectl --kubeconfig "${workload_kubeconfig}" \
      -n "${CLUSTER_AUTOSCALER_WORKLOAD_NAMESPACE}" get secret \
      "${CLUSTER_AUTOSCALER_WORKLOAD_TOKEN_SECRET}" \
      -o jsonpath='{.data.token}' 2>/dev/null || true)"
    if [[ -n "${token}" ]]; then
      break
    fi
    sleep 1
  done
  [[ -n "${token}" ]] || die "workload ServiceAccount token was not populated"

  endpoint="$(kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${WORKLOAD_NAMESPACE}" get cluster "${WORKLOAD_CLUSTER_NAME}" \
    -o jsonpath='{.spec.controlPlaneEndpoint.host}')"
  port="$(kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${WORKLOAD_NAMESPACE}" get cluster "${WORKLOAD_CLUSTER_NAME}" \
    -o jsonpath='{.spec.controlPlaneEndpoint.port}')"
  [[ -n "${endpoint}" && -n "${port}" ]] ||
    die "workload control plane endpoint is not available"
  server="https://${endpoint}:${port}"
  [[ "${server}" == https://* ]] || die "workload API server is not HTTPS"
  credential_temp_dir="$(mktemp -d "${SECRET_DIR}/cluster-autoscaler.XXXXXX")"
  chmod 700 "${credential_temp_dir}"
  ca_file="${credential_temp_dir}/ca.crt"
  kubeconfig_file="${credential_temp_dir}/kubeconfig"
  kubectl --kubeconfig "${workload_kubeconfig}" \
    -n "${CLUSTER_AUTOSCALER_WORKLOAD_NAMESPACE}" get secret \
    "${CLUSTER_AUTOSCALER_WORKLOAD_TOKEN_SECRET}" \
    -o jsonpath='{.data.ca\.crt}' | base64 --decode >"${ca_file}"
  chmod 600 "${ca_file}"
  KUBECONFIG="${kubeconfig_file}" kubectl config set-cluster workload \
    --server="${server}" --certificate-authority="${ca_file}" --embed-certs=true >/dev/null
  token="$(printf '%s' "${token}" | base64 --decode)"
  KUBECONFIG="${kubeconfig_file}" kubectl config set-credentials cluster-autoscaler \
    --token="${token}" >/dev/null
  KUBECONFIG="${kubeconfig_file}" kubectl config set-context workload \
    --cluster=workload --user=cluster-autoscaler \
    --namespace="${CLUSTER_AUTOSCALER_WORKLOAD_NAMESPACE}" >/dev/null
  KUBECONFIG="${kubeconfig_file}" kubectl config use-context workload >/dev/null
  chmod 600 "${kubeconfig_file}"

  kubectl --kubeconfig "${management_kubeconfig}" create namespace \
    "${CLUSTER_AUTOSCALER_NAMESPACE}" --dry-run=client -o yaml |
    kubectl --kubeconfig "${management_kubeconfig}" apply -f - >/dev/null
  kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${CLUSTER_AUTOSCALER_NAMESPACE}" create secret generic \
    "${CLUSTER_AUTOSCALER_WORKLOAD_KUBECONFIG_SECRET}" \
    --from-file="value=${kubeconfig_file}" --dry-run=client -o yaml |
    kubectl --kubeconfig "${management_kubeconfig}" apply -f - >/dev/null
  cleanup_credential_temp
  credential_temp_dir=""
}

annotate_node_group() {
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" annotate \
    machinedeployment "${machine_deployment}" \
    "cluster.x-k8s.io/cluster-api-autoscaler-node-group-min-size=${CLUSTER_AUTOSCALER_NODE_GROUP_MIN_SIZE}" \
    "cluster.x-k8s.io/cluster-api-autoscaler-node-group-max-size=${CLUSTER_AUTOSCALER_NODE_GROUP_MAX_SIZE}" \
    --overwrite >/dev/null
}

install_autoscaler() {
  require_context
  local desired available
  desired="$(kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    get machinedeployment "${machine_deployment}" -o jsonpath='{.spec.replicas}')"
  available="$(kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    get machinedeployment "${machine_deployment}" -o jsonpath='{.status.availableReplicas}')"
  [[ "${desired}" =~ ^[1-3]$ && "${available}" == "${desired}" ]] ||
    die "install requires a stable node group within 1:3; found desired=${desired} available=${available:-0}"
  render_base_manifests
  annotate_node_group
  create_workload_kubeconfig_secret
  log "Installing Cluster Autoscaler ${CLUSTER_AUTOSCALER_VERSION} in the management cluster"
  kubectl --kubeconfig "${management_kubeconfig}" apply -f "${management_manifest}" >/dev/null
  if ! kubectl --kubeconfig "${management_kubeconfig}" \
      -n "${CLUSTER_AUTOSCALER_NAMESPACE}" rollout status deployment/cluster-autoscaler \
      --timeout=5m; then
    capture_failure "install"
    die "Cluster Autoscaler deployment did not become Available"
  fi
  verify_autoscaler
}

verify_autoscaler() {
  require_context
  local min_size max_size image image_id desired available autoscaler_node node_architecture
  min_size="$(kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    get machinedeployment "${machine_deployment}" \
    -o jsonpath='{.metadata.annotations.cluster\.x-k8s\.io/cluster-api-autoscaler-node-group-min-size}')"
  max_size="$(kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    get machinedeployment "${machine_deployment}" \
    -o jsonpath='{.metadata.annotations.cluster\.x-k8s\.io/cluster-api-autoscaler-node-group-max-size}')"
  [[ "${min_size}" == "${CLUSTER_AUTOSCALER_NODE_GROUP_MIN_SIZE}" && "${max_size}" == "${CLUSTER_AUTOSCALER_NODE_GROUP_MAX_SIZE}" ]] ||
    die "unexpected MachineDeployment autoscaler range: ${min_size:-unset}:${max_size:-unset}"

  image="$(kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${CLUSTER_AUTOSCALER_NAMESPACE}" get deployment cluster-autoscaler \
    -o jsonpath='{.spec.template.spec.containers[0].image}')"
  [[ "${image}" == "${CLUSTER_AUTOSCALER_IMAGE}" ]] || die "unexpected autoscaler image: ${image}"
  desired="$(kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${CLUSTER_AUTOSCALER_NAMESPACE}" get deployment cluster-autoscaler \
    -o jsonpath='{.spec.replicas}')"
  available="$(kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${CLUSTER_AUTOSCALER_NAMESPACE}" get deployment cluster-autoscaler \
    -o jsonpath='{.status.availableReplicas}')"
  [[ "${desired}" == "1" && "${available}" == "1" ]] ||
    die "Cluster Autoscaler is not single-replica Available"

  kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${CLUSTER_AUTOSCALER_NAMESPACE}" get deployment cluster-autoscaler -o json |
    python3 -c '
import json, sys
args = json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0]["args"]
required = {
    "--cloud-provider=clusterapi",
    "--kubeconfig=/etc/cluster-autoscaler/workload/value",
    "--clusterapi-cloud-config-authoritative",
    "--scale-down-enabled=true",
    "--node-group-auto-discovery=clusterapi:namespace=" + sys.argv[1] + ",clusterName=" + sys.argv[2],
}
from pathlib import Path
policy = {line.strip()[2:] for line in Path(sys.argv[3]).read_text().splitlines()
          if line.strip().startswith("- --") and "${" not in line}
required |= policy
missing = sorted(required - set(args))
keys = [arg.split("=", 1)[0] for arg in args]
if len(keys) != len(set(keys)):
    raise SystemExit("duplicate Cluster Autoscaler flags")
if missing or any(arg.startswith("--cloud-config") for arg in args):
    raise SystemExit(f"invalid Cluster Autoscaler arguments: missing={missing}")
' "${WORKLOAD_NAMESPACE}" "${WORKLOAD_CLUSTER_NAME}" "${management_template}" ||
    die "Cluster Autoscaler arguments do not match ADR-0016"
  kubectl --kubeconfig "${management_kubeconfig}" auth can-i \
    --as="system:serviceaccount:${CLUSTER_AUTOSCALER_NAMESPACE}:${CLUSTER_AUTOSCALER_SERVICE_ACCOUNT}" \
    patch machinedeployments.cluster.x-k8s.io --subresource=scale \
    -n "${WORKLOAD_NAMESPACE}" |
    grep -qx yes || die "management ServiceAccount cannot patch MachineDeployment scale"
  kubectl --kubeconfig "${workload_kubeconfig}" auth can-i \
    --as="system:serviceaccount:${CLUSTER_AUTOSCALER_WORKLOAD_NAMESPACE}:${CLUSTER_AUTOSCALER_SERVICE_ACCOUNT}" \
    list pods --all-namespaces | grep -qx yes ||
    die "workload ServiceAccount cannot list Pods"
  kubectl --kubeconfig "${workload_kubeconfig}" auth can-i \
    --as="system:serviceaccount:${CLUSTER_AUTOSCALER_WORKLOAD_NAMESPACE}:${CLUSTER_AUTOSCALER_SERVICE_ACCOUNT}" \
    create pods --subresource=eviction --all-namespaces | grep -qx yes ||
    die "workload ServiceAccount cannot evict Pods"
  kubectl --kubeconfig "${workload_kubeconfig}" auth can-i \
    --as="system:serviceaccount:${CLUSTER_AUTOSCALER_WORKLOAD_NAMESPACE}:${CLUSTER_AUTOSCALER_SERVICE_ACCOUNT}" \
    list poddisruptionbudgets.policy --all-namespaces | grep -qx yes ||
    die "workload ServiceAccount cannot read PDBs"
  local resource
  for resource in resourceslices deviceclasses resourceclaims; do
    kubectl --kubeconfig "${workload_kubeconfig}" auth can-i \
      --as="system:serviceaccount:${CLUSTER_AUTOSCALER_WORKLOAD_NAMESPACE}:${CLUSTER_AUTOSCALER_SERVICE_ACCOUNT}" \
      list "${resource}.resource.k8s.io" --all-namespaces 2>/dev/null |
      grep -qx yes || die "workload ServiceAccount cannot list ${resource}"
  done
  kubectl --kubeconfig "${management_kubeconfig}" auth can-i \
    --as="system:serviceaccount:${CLUSTER_AUTOSCALER_NAMESPACE}:${CLUSTER_AUTOSCALER_SERVICE_ACCOUNT}" \
    list openstackmachinetemplates.infrastructure.cluster.x-k8s.io \
    -n "${WORKLOAD_NAMESPACE}" | grep -qx yes ||
    die "management ServiceAccount cannot read OpenStackMachineTemplates"
  image_id="$(kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${CLUSTER_AUTOSCALER_NAMESPACE}" get pods \
    -l app.kubernetes.io/name=cluster-autoscaler \
    -o jsonpath='{.items[0].status.containerStatuses[0].imageID}')"
  [[ "${image_id}" == *@"${CLUSTER_AUTOSCALER_IMAGE_DIGEST}" ]] ||
    die "running autoscaler imageID does not match pinned manifest digest: ${image_id}"
  autoscaler_node="$(kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${CLUSTER_AUTOSCALER_NAMESPACE}" get pods \
    -l app.kubernetes.io/name=cluster-autoscaler \
    -o jsonpath='{.items[0].spec.nodeName}')"
  node_architecture="$(kubectl --kubeconfig "${management_kubeconfig}" get node \
    "${autoscaler_node}" -o jsonpath='{.status.nodeInfo.architecture}')"
  [[ "${node_architecture}" == "${MANAGEMENT_KUBERNETES_ARCHITECTURE}" ]] ||
    die "Autoscaler is running on ${node_architecture}; expected ${MANAGEMENT_KUBERNETES_ARCHITECTURE}"
  log "Cluster Autoscaler image, arguments, RBAC and node-group range passed"
}

check_orphan_calico_ipam() {
  local node="$1" status_dir="$2" address output
  address="$(kubectl --kubeconfig "${workload_kubeconfig}" get node "${node}" \
    -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}')"
  sleep 10
  set +e
  output="$(run_on "${CONTROLLER_NAME}" env \
    MACHINE_ADDRESS="${address}" WORKLOAD_NETWORK_CIDR="${WORKLOAD_NETWORK_CIDR}" \
    TARGET_SSH_USER="${TARGET_SSH_USER}" bash -s <<'CONTROLLER_CHECK'
set -Eeuo pipefail
router_namespace=""
while read -r namespace _; do
  if sudo ip netns exec "${namespace}" ip -4 route show "${WORKLOAD_NETWORK_CIDR}" | grep -q .; then
    router_namespace="${namespace}"
    break
  fi
done < <(sudo ip netns list)
[[ -n "${router_namespace}" ]]
deployment_key="/home/${TARGET_SSH_USER}/.ssh/openstack_k8s"
sudo ip netns exec "${router_namespace}" ssh -i "${deployment_key}" \
  -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null "ubuntu@${MACHINE_ADDRESS}" bash -s <<'GUEST_CHECK'
set -Eeuo pipefail
matches="$(ps -eo pid=,ppid=,etimes=,stat=,wchan:32=,comm=,args= | grep '[c]alico-ipam' || true)"
if [[ -n "${matches}" ]]; then
  printf '%s\n' "${matches}"
  exit 3
fi
echo "no calico-ipam process remains"
GUEST_CHECK
CONTROLLER_CHECK
  )"
  local check_status=$?
  set -e
  printf '%s\n' "${output}" >"${status_dir}/new-worker-calico-ipam.txt"
  [[ "${check_status}" -eq 0 ]] || {
    capture_failure "orphan-calico-ipam"
    die "calico-ipam process remained on new worker; state preserved"
  }
}

case "${action}" in
  install) python3 "${PROJECT_ROOT}/scripts/autoscaler_cycle.py" install ;;
  install-unlocked)
    [[ -n "${WORKER_CONTROL_LOCK_FD:-}" && -e "/dev/fd/${WORKER_CONTROL_LOCK_FD}" ]] ||
      die "install-unlocked requires the worker control runner"
    install_autoscaler
    ;;
  verify) verify_autoscaler ;;
  test) python3 "${PROJECT_ROOT}/scripts/autoscaler_cycle.py" test ;;
  test-cleanup) python3 "${PROJECT_ROOT}/scripts/autoscaler_cycle.py" cleanup ;;
  mode) python3 "${PROJECT_ROOT}/scripts/autoscaler_cycle.py" mode "${2:?auto or fixed}" ;;
  control-status) python3 "${PROJECT_ROOT}/scripts/autoscaler_cycle.py" status ;;
  control-recover) python3 "${PROJECT_ROOT}/scripts/autoscaler_cycle.py" recover ;;
  ipam-check) check_orphan_calico_ipam "${2:?node}" "${3:?evidence directory}" ;;
  diagnostics) capture_failure "manual" ;;
  *) die "usage: $0 {install|verify|test|test-cleanup|mode auto|mode fixed|control-status|control-recover|diagnostics}" ;;
esac
