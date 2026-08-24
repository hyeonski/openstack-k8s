#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

action="${1:-}"
management_kubeconfig="${STATE_DIR}/kubeconfigs/management.yaml"
workload_kubeconfig="${STATE_DIR}/kubeconfigs/${WORKLOAD_CLUSTER_NAME}.yaml"
machine_deployment="${WORKLOAD_CLUSTER_NAME}-md-0"
manifest_root="${PROJECT_ROOT}/kubernetes/cluster-autoscaler"
management_template="${manifest_root}/management.yaml.tpl"
workload_rbac_template="${manifest_root}/workload-rbac.yaml.tpl"
test_template="${manifest_root}/test-workload.yaml.tpl"
probe_template="${manifest_root}/targeted-probe.yaml.tpl"
management_manifest="${GENERATED_DIR}/cluster-autoscaler-management.yaml"
workload_rbac_manifest="${GENERATED_DIR}/cluster-autoscaler-workload-rbac.yaml"
test_manifest="${GENERATED_DIR}/cluster-autoscaler-test-workload.yaml"
probe_manifest="${GENERATED_DIR}/cluster-autoscaler-targeted-probe.yaml"
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
  if [[ "${HOST_PROVIDER}" == "gcp" ]]; then
    require_command gcloud
  else
    require_command limactl
  fi
  ensure_management_api_access
  require_command python3
  require_command base64
  [[ -f "${management_kubeconfig}" ]] || die "management kubeconfig is missing"
  [[ -f "${workload_kubeconfig}" ]] || die "workload kubeconfig is missing"
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
  local server token ca_file kubeconfig_file attempts attempt
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

  server="$(kubectl --kubeconfig "${workload_kubeconfig}" config view --minify \
    -o jsonpath='{.clusters[0].cluster.server}')"
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
  [[ ("${desired}" == "1" || "${desired}" == "2") && "${available}" == "${desired}" ]] ||
    die "install requires a stable node group within 1:2; found desired=${desired} available=${available:-0}"
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
  [[ "${min_size}" == "1" && "${max_size}" == "2" ]] ||
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
    "--scale-down-enabled=false",
    "--node-group-auto-discovery=clusterapi:namespace=" + sys.argv[1] + ",clusterName=" + sys.argv[2],
}
missing = sorted(required - set(args))
if missing or any(arg.startswith("--cloud-config") for arg in args):
    raise SystemExit(f"invalid Cluster Autoscaler arguments: missing={missing}")
' "${WORKLOAD_NAMESPACE}" "${WORKLOAD_CLUSTER_NAME}" ||
    die "Cluster Autoscaler arguments do not match ADR-0012"
  kubectl --kubeconfig "${management_kubeconfig}" auth can-i \
    --as="system:serviceaccount:${CLUSTER_AUTOSCALER_NAMESPACE}:${CLUSTER_AUTOSCALER_SERVICE_ACCOUNT}" \
    patch machinedeployments.cluster.x-k8s.io --subresource=scale \
    -n "${WORKLOAD_NAMESPACE}" |
    grep -qx yes || die "management ServiceAccount cannot patch MachineDeployment scale"
  kubectl --kubeconfig "${workload_kubeconfig}" auth can-i \
    --as="system:serviceaccount:${CLUSTER_AUTOSCALER_WORKLOAD_NAMESPACE}:${CLUSTER_AUTOSCALER_SERVICE_ACCOUNT}" \
    list pods --all-namespaces | grep -qx yes ||
    die "workload ServiceAccount cannot list Pods"
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

write_name_list() {
  local path="$1"
  shift
  printf '%s\n' "$@" | sed '/^$/d' | sort >"${path}"
  chmod 600 "${path}"
}

select_cpu_request() {
  local worker="$1" status_dir="$2"
  local node_json pods_json selection
  node_json="${GENERATED_DIR}/m3-worker-node.json"
  pods_json="${GENERATED_DIR}/m3-worker-pods.json"
  kubectl --kubeconfig "${workload_kubeconfig}" get node "${worker}" -o json >"${node_json}"
  kubectl --kubeconfig "${workload_kubeconfig}" get pods -A \
    --field-selector="spec.nodeName=${worker}" -o json >"${pods_json}"
  selection="$("${PROJECT_ROOT}/scripts/select-autoscaler-cpu.py" "${node_json}" "${pods_json}")"
  rm -f "${node_json}" "${pods_json}"
  {
    printf 'worker=%s\n' "${worker}"
    printf '%s\n' "${selection}"
  } >"${status_dir}/cpu-selection.txt"
  chmod 600 "${status_dir}/cpu-selection.txt"
  awk -F= '$1 == "selected_request_millicpu" {print $2}' <<<"${selection}"
}

wait_for_pending_cpu() {
  local status_dir="$1" attempt desired lines pod status reason message
  for ((attempt = 1; attempt <= 120; attempt++)); do
    desired="$(kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
      get machinedeployment "${machine_deployment}" -o jsonpath='{.spec.replicas}')"
    [[ "${desired}" == "1" ]] || {
      capture_failure "scaled-before-pending-proof"
      die "MachineDeployment scaled before the required Pending CPU evidence was captured"
    }
    lines="$(kubectl --kubeconfig "${workload_kubeconfig}" \
      -n "${CLUSTER_AUTOSCALER_TEST_NAMESPACE}" get pods \
      -l "app.kubernetes.io/name=${CLUSTER_AUTOSCALER_TEST_NAME}" \
      -o jsonpath='{range .items[?(@.status.phase=="Pending")]}{.metadata.name}{"\t"}{range .status.conditions[?(@.type=="PodScheduled")]}{.status}{"\t"}{.reason}{"\t"}{.message}{end}{"\n"}{end}' 2>/dev/null || true)"
    while IFS=$'\t' read -r pod status reason message; do
      [[ -n "${pod}" ]] || continue
      if [[ "${status}" == "False" && "${reason}" == "Unschedulable" &&
          "${message}" == *"Insufficient cpu"* ]]; then
        desired="$(kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
          get machinedeployment "${machine_deployment}" -o jsonpath='{.spec.replicas}')"
        [[ "${desired}" == "1" ]] || continue
        printf 'pod=%s\nreason=%s\nmessage=%s\n' "${pod}" "${reason}" "${message}" \
          >"${status_dir}/pending-insufficient-cpu.txt"
        kubectl --kubeconfig "${workload_kubeconfig}" \
          -n "${CLUSTER_AUTOSCALER_TEST_NAMESPACE}" describe pod "${pod}" \
          >"${status_dir}/pending-pod-describe.txt"
        printf '%s\n' "${pod}"
        return
      fi
    done <<<"${lines}"
    sleep 1
  done
  capture_failure "pending-cpu-timeout"
  die "no Unschedulable Pod with Insufficient cpu was observed"
}

wait_for_new_machine_node() {
  local old_file="$1" attempt machine node
  for ((attempt = 1; attempt <= 360; attempt++)); do
    while IFS=$'\t' read -r machine node; do
      [[ -n "${machine}" && -n "${node}" ]] || continue
      if ! grep -Fxq "${machine}" "${old_file}"; then
        printf '%s\t%s\n' "${machine}" "${node}"
        return
      fi
    done < <(kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
      get machines -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.nodeRef.name}{"\n"}{end}' \
      2>/dev/null || true)
    sleep 5
  done
  capture_failure "new-machine-node-timeout"
  die "new Machine did not acquire a Node reference"
}

wait_for_nova_active() {
  local machine="$1" attempt status
  for ((attempt = 1; attempt <= 180; attempt++)); do
    status="$(run_on "${CONTROLLER_NAME}" env MACHINE_NAME="${machine}" bash -lc '
      set -Eeuo pipefail
      source /opt/kolla-venv/bin/activate
      export OS_CLIENT_CONFIG_FILE=/etc/kolla/capi-clouds.yaml
      openstack --os-cloud capi server show "${MACHINE_NAME}" -f value -c status
    ' 2>/dev/null || true)"
    [[ "${status}" == "ACTIVE" ]] && return
    sleep 5
  done
  capture_failure "nova-active-timeout"
  die "new Nova server did not become ACTIVE: ${machine} status=${status:-missing}"
}

run_targeted_probe() {
  local node="$1" status_dir="$2"
  CLUSTER_AUTOSCALER_TARGETED_PROBE_NAME="${CLUSTER_AUTOSCALER_TARGETED_PROBE_NAME}" \
  CLUSTER_AUTOSCALER_TEST_NAMESPACE="${CLUSTER_AUTOSCALER_TEST_NAMESPACE}" \
  CLUSTER_AUTOSCALER_TEST_IMAGE="${CLUSTER_AUTOSCALER_TEST_IMAGE}" \
  CLUSTER_AUTOSCALER_TARGET_NODE="${node}" \
    "${PROJECT_ROOT}/scripts/render-template.py" "${probe_template}" "${probe_manifest}"
  kubectl --kubeconfig "${workload_kubeconfig}" apply -f "${probe_manifest}" >/dev/null
  if ! kubectl --kubeconfig "${workload_kubeconfig}" \
      -n "${CLUSTER_AUTOSCALER_TEST_NAMESPACE}" wait \
      --for=jsonpath='{.status.phase}'=Succeeded \
      "pod/${CLUSTER_AUTOSCALER_TARGETED_PROBE_NAME}" --timeout=5m; then
    capture_failure "targeted-cni-dns"
    die "new-worker targeted CNI/DNS probe failed; Pod preserved"
  fi
  kubectl --kubeconfig "${workload_kubeconfig}" \
    -n "${CLUSTER_AUTOSCALER_TEST_NAMESPACE}" get pod \
    "${CLUSTER_AUTOSCALER_TARGETED_PROBE_NAME}" -o wide \
    >"${status_dir}/targeted-cni-dns-probe.txt"
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

test_scale_up() {
  verify_autoscaler
  local desired available run_dir status_dir worker cpu_request pending_pod
  local new_identity new_machine new_node started finished
  desired="$(kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    get machinedeployment "${machine_deployment}" -o jsonpath='{.spec.replicas}')"
  available="$(kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    get machinedeployment "${machine_deployment}" -o jsonpath='{.status.availableReplicas}')"
  [[ "${desired}" == "1" && "${available}" == "1" ]] ||
    die "M3 test requires desired=1 available=1; found desired=${desired} available=${available:-0}"
  if kubectl --kubeconfig "${workload_kubeconfig}" \
      -n "${CLUSTER_AUTOSCALER_TEST_NAMESPACE}" get deployment \
      "${CLUSTER_AUTOSCALER_TEST_NAME}" >/dev/null 2>&1; then
    die "existing M3 test workload must be inspected before retry"
  fi
  if kubectl --kubeconfig "${workload_kubeconfig}" \
      -n "${CLUSTER_AUTOSCALER_TEST_NAMESPACE}" get pod \
      "${CLUSTER_AUTOSCALER_TARGETED_PROBE_NAME}" >/dev/null 2>&1; then
    die "existing M3 targeted probe must be inspected before retry"
  fi

  run_dir="$(current_or_new_run)"
  status_dir="${run_dir}/m3"
  mkdir -p "${status_dir}"
  chmod 700 "${status_dir}"
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    get machines -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' |
    sort >"${status_dir}/machines-before.txt"
  kubectl --kubeconfig "${workload_kubeconfig}" get nodes \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' |
    sort >"${status_dir}/nodes-before.txt"
  worker="$(kubectl --kubeconfig "${workload_kubeconfig}" get nodes \
    -l '!node-role.kubernetes.io/control-plane' \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')"
  [[ "$(wc -l <<<"${worker}" | tr -d ' ')" == "1" ]] || die "expected exactly one worker"
  cpu_request="$(select_cpu_request "${worker}" "${status_dir}")"
  [[ "${cpu_request}" =~ ^[1-9][0-9]*$ ]] || die "invalid selected CPU request"

  CLUSTER_AUTOSCALER_TEST_NAME="${CLUSTER_AUTOSCALER_TEST_NAME}" \
  CLUSTER_AUTOSCALER_TEST_NAMESPACE="${CLUSTER_AUTOSCALER_TEST_NAMESPACE}" \
  CLUSTER_AUTOSCALER_TEST_IMAGE="${CLUSTER_AUTOSCALER_TEST_IMAGE}" \
  CLUSTER_AUTOSCALER_TEST_CPU_REQUEST="${cpu_request}m" \
    "${PROJECT_ROOT}/scripts/render-template.py" "${test_template}" "${test_manifest}"
  started="$(date +%s)"
  printf 'status=in_progress\nstarted_utc=%s\nstarted_epoch=%s\n' \
    "$(date -u +%FT%TZ)" "${started}" >"${status_dir}/scale-up-timing.txt"
  log "Creating two ${cpu_request}m CPU Pods on one worker"
  kubectl --kubeconfig "${workload_kubeconfig}" apply -f "${test_manifest}" >/dev/null
  pending_pod="$(wait_for_pending_cpu "${status_dir}")"
  log "Observed ${pending_pod}: Unschedulable due to Insufficient cpu"

  if ! kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" wait \
      --for=jsonpath='{.spec.replicas}'=2 "machinedeployment/${machine_deployment}" \
      --timeout="${WORKLOAD_CAPI_READY_TIMEOUT}"; then
    capture_failure "autoscaler-scale-up-timeout"
    die "Cluster Autoscaler did not change MachineDeployment from 1 to 2"
  fi
  new_identity="$(wait_for_new_machine_node "${status_dir}/machines-before.txt")"
  IFS=$'\t' read -r new_machine new_node <<<"${new_identity}"
  printf 'machine=%s\nnode=%s\n' "${new_machine}" "${new_node}" \
    >"${status_dir}/new-worker.txt"
  wait_for_nova_active "${new_machine}"
  kubectl --kubeconfig "${workload_kubeconfig}" wait --for=condition=Ready \
    "node/${new_node}" --timeout="${WORKLOAD_NODE_READY_TIMEOUT}"
  local calico_pod
  calico_pod="$(kubectl --kubeconfig "${workload_kubeconfig}" -n kube-system get pods \
    -l k8s-app=calico-node --field-selector="spec.nodeName=${new_node}" \
    -o jsonpath='{.items[0].metadata.name}')"
  kubectl --kubeconfig "${workload_kubeconfig}" -n kube-system wait \
    --for=condition=Ready "pod/${calico_pod}" --timeout="${WORKLOAD_CALICO_READY_TIMEOUT}"
  run_targeted_probe "${new_node}" "${status_dir}"
  kubectl --kubeconfig "${workload_kubeconfig}" \
    -n "${CLUSTER_AUTOSCALER_TEST_NAMESPACE}" wait \
    --for=condition=Available "deployment/${CLUSTER_AUTOSCALER_TEST_NAME}" --timeout=5m
  kubectl --kubeconfig "${workload_kubeconfig}" \
    -n "${CLUSTER_AUTOSCALER_TEST_NAMESPACE}" get pods \
    -l "app.kubernetes.io/name=${CLUSTER_AUTOSCALER_TEST_NAME}" -o wide \
    >"${status_dir}/test-pods-after-scale-up.txt"
  grep -q "${new_node}" "${status_dir}/test-pods-after-scale-up.txt" || {
    capture_failure "pending-pod-not-on-new-worker"
    die "the previously Pending workload did not run on the new worker"
  }

  "${PROJECT_ROOT}/scripts/workload-cluster.sh" verify 2
  check_orphan_calico_ipam "${new_node}" "${status_dir}"
  kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${CLUSTER_AUTOSCALER_NAMESPACE}" logs deployment/cluster-autoscaler --tail=1000 \
    >"${status_dir}/autoscaler-scale-up.log"
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" get \
    machinedeployments,machines,openstackmachines -o wide >"${status_dir}/capi-after-scale-up.txt"
  kubectl --kubeconfig "${workload_kubeconfig}" get nodes -o wide \
    >"${status_dir}/nodes-after-scale-up.txt"
  finished="$(date +%s)"
  printf 'status=passed\nstarted_epoch=%s\nready_epoch=%s\nelapsed_seconds=%s\n' \
    "${started}" "${finished}" "$((finished - started))" >"${status_dir}/scale-up-timing.txt"
  chmod -R go-rwx "${status_dir}"
  log "M3 Pending Pod scale-up passed; new worker=${new_node} artifact=${status_dir}"
}

case "${action}" in
  install) install_autoscaler ;;
  verify) verify_autoscaler ;;
  test) test_scale_up ;;
  diagnostics) capture_failure "manual" ;;
  *) die "usage: $0 {install|verify|test|diagnostics}" ;;
esac
