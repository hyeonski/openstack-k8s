#!/usr/bin/env bash

set -Eeuo pipefail
umask 077
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
set -a
source "${PROJECT_ROOT}/scripts/lib/common.sh"
set +a

action="${1:-}"
management_kubeconfig="${STATE_DIR}/kubeconfigs/management.yaml"
workload_kubeconfig="${STATE_DIR}/kubeconfigs/${WORKLOAD_CLUSTER_NAME}.yaml"
clusterctl_bin="${STATE_DIR}/bin/clusterctl"
clusterctl_config="${PROJECT_ROOT}/config/clusterctl.yaml"
cluster_template="${PROJECT_ROOT}/kubernetes/capi/workload-cluster.yaml.tpl"
cluster_manifest="${GENERATED_DIR}/${WORKLOAD_CLUSTER_NAME}.yaml"
calico_manifest="${DOWNLOAD_DIR}/calico-${CALICO_VERSION}.yaml"
calico_url="https://raw.githubusercontent.com/projectcalico/calico/${CALICO_VERSION}/manifests/calico.yaml"
machine_deployment="${WORKLOAD_CLUSTER_NAME}-md-0"
autoscaler_replicas_before_manual_scaling=""
manual_scaling_run_dir=""

require_kubectl_timeout() {
  local name="$1"
  local value="$2"
  [[ "${value}" =~ ^[1-9][0-9]*[smh]$ ]] ||
    die "${name} must be a positive kubectl duration such as 10m: ${value}"
}

require_positive_integer() {
  local name="$1"
  local value="$2"
  [[ "${value}" =~ ^[1-9][0-9]*$ ]] ||
    die "${name} must be a positive integer: ${value}"
}

require_management() {
  require_command kubectl
  require_command gcloud
  ensure_management_api_access
  [[ -f "${management_kubeconfig}" ]] || die "management kubeconfig is missing"
  [[ -x "${clusterctl_bin}" ]] || die "clusterctl is missing; install providers first"
  kubectl --kubeconfig "${management_kubeconfig}" get nodes >/dev/null
  kubectl --kubeconfig "${management_kubeconfig}" -n capo-system wait \
    --for=condition=Available deployment --all --timeout=3m >/dev/null
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    get secret "${WORKLOAD_CLUSTER_NAME}-cloud-config" >/dev/null
}

require_existing_floating_ip_route() {
  local route_destination route_next_hop route_name
  require_command gcloud
  route_name="${GCP_OPENSTACK_FLOATING_IP_ROUTE_NAME:?}"
  route_destination="$(
    gcloud compute routes describe "${route_name}" \
      --project="${GCP_PROJECT_ID}" --format='value(destRange)' 2>/dev/null || true
  )"
  route_next_hop="$(
    gcloud compute routes describe "${route_name}" \
      --project="${GCP_PROJECT_ID}" --format='value(nextHopInstance)' 2>/dev/null || true
  )"
  [[ "${route_destination}" == "${EXTERNAL_CIDR}" ]] ||
    die "GCP Floating IP route is missing or has the wrong destination"
  [[ "${route_next_hop##*/}" == "${CONTROLLER_NAME}" ]] ||
    die "GCP Floating IP route does not use the controller as next hop"
}

wait_for_secret() {
  local name="$1"
  local attempts="${2:-240}"
  local attempt
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
        get secret "${name}" >/dev/null 2>&1; then
      return
    fi
    sleep 5
  done
  die "timed out waiting for secret ${name}"
}

write_workload_kubeconfig() {
  mkdir_private "$(dirname "${workload_kubeconfig}")"
  local temporary="${workload_kubeconfig}.download"
  "${clusterctl_bin}" get kubeconfig "${WORKLOAD_CLUSTER_NAME}" \
    --namespace "${WORKLOAD_NAMESPACE}" \
    --config "${clusterctl_config}" \
    --kubeconfig "${management_kubeconfig}" >"${temporary}"
  chmod 600 "${temporary}"
  mv "${temporary}" "${workload_kubeconfig}"
  ensure_workload_api_access
}

wait_for_workload_api() {
  local attempts="${1:-240}"
  local attempt
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if kubectl --kubeconfig "${workload_kubeconfig}" get --raw=/readyz >/dev/null 2>&1; then
      return
    fi
    sleep 5
  done
  die "timed out waiting for workload Kubernetes API readiness"
}

openstack_external_network_id() {
  run_on "${CONTROLLER_NAME}" bash -lc '
    set -Eeuo pipefail
    source /opt/kolla-venv/bin/activate
    export OS_CLIENT_CONFIG_FILE=/etc/kolla/capi-clouds.yaml
    openstack --os-cloud capi network show public -f value -c id
  '
}

capture_failure_diagnostics() {
  local reason="$1"
  if ! "${PROJECT_ROOT}/scripts/workload-diagnostics.sh" "${reason}"; then
    warn "one or more workload diagnostic collectors failed; partial evidence was preserved"
  fi
}

wait_for_calico_ready() {
  log "Waiting up to ${WORKLOAD_CALICO_READY_TIMEOUT} for Calico node readiness"
  if ! kubectl --kubeconfig "${workload_kubeconfig}" -n kube-system wait \
      --for=condition=Ready pod -l k8s-app=calico-node \
      --timeout="${WORKLOAD_CALICO_READY_TIMEOUT}"; then
    capture_failure_diagnostics "calico-readiness-timeout"
    die "Calico nodes did not become Ready within ${WORKLOAD_CALICO_READY_TIMEOUT}"
  fi
}

wait_for_control_plane_available() {
  require_kubectl_timeout WORKLOAD_CAPI_READY_TIMEOUT "${WORKLOAD_CAPI_READY_TIMEOUT}"

  if ! kubectl --kubeconfig "${management_kubeconfig}" \
      -n "${WORKLOAD_NAMESPACE}" wait \
      --for=condition=Available "kubeadmcontrolplane/${WORKLOAD_CLUSTER_NAME}-control-plane" \
      --timeout="${WORKLOAD_CAPI_READY_TIMEOUT}"; then
    capture_failure_diagnostics "kcp-available-timeout"
    die "KubeadmControlPlane did not become Available within ${WORKLOAD_CAPI_READY_TIMEOUT}"
  fi
  if ! kubectl --kubeconfig "${management_kubeconfig}" \
      -n "${WORKLOAD_NAMESPACE}" wait \
      --for=condition=Available "cluster/${WORKLOAD_CLUSTER_NAME}" \
      --timeout="${WORKLOAD_CAPI_READY_TIMEOUT}"; then
    capture_failure_diagnostics "cluster-available-timeout"
    die "Cluster did not become Available within ${WORKLOAD_CAPI_READY_TIMEOUT}"
  fi

  local desired ready available
  IFS=$'\t' read -r desired ready available < <(
    kubectl --kubeconfig "${management_kubeconfig}" \
      -n "${WORKLOAD_NAMESPACE}" get kubeadmcontrolplane \
      "${WORKLOAD_CLUSTER_NAME}-control-plane" \
      -o jsonpath='{.spec.replicas}{"\t"}{.status.readyReplicas}{"\t"}{.status.availableReplicas}{"\n"}'
  )
  [[ "${desired}" == "1" && "${ready}" == "1" && "${available}" == "1" ]] || {
    capture_failure_diagnostics "kcp-replica-mismatch"
    die "KubeadmControlPlane replicas are desired=${desired:-0}, ready=${ready:-0}, available=${available:-0}"
  }

  IFS=$'\t' read -r desired ready available < <(
    kubectl --kubeconfig "${management_kubeconfig}" \
      -n "${WORKLOAD_NAMESPACE}" get cluster "${WORKLOAD_CLUSTER_NAME}" \
      -o jsonpath='{.status.controlPlane.desiredReplicas}{"\t"}{.status.controlPlane.readyReplicas}{"\t"}{.status.controlPlane.availableReplicas}{"\n"}'
  )
  [[ "${desired}" == "1" && "${ready}" == "1" && "${available}" == "1" ]] || {
    capture_failure_diagnostics "cluster-control-plane-mismatch"
    die "Cluster control plane replicas are desired=${desired:-0}, ready=${ready:-0}, available=${available:-0}"
  }
  log "Cluster and KubeadmControlPlane are strictly Available"
}

tune_calico_probes_for_gcp_capacity() {
  local probe_patch
  # Three nested Nova guests fully consume a GCP compute host's four
  # vCPUs during first boot. A startup probe prevents liveness from restarting
  # Calico while images, BIRD and Felix are still converging. The regular
  # probes also need enough wall time to be scheduled on a saturated GCP
  # worker; otherwise a healthy command can exceed the upstream 1s default.
  require_positive_integer WORKLOAD_CALICO_PROBE_TIMEOUT_SECONDS \
    "${WORKLOAD_CALICO_PROBE_TIMEOUT_SECONDS}"
  require_positive_integer WORKLOAD_CALICO_STARTUP_FAILURE_THRESHOLD \
    "${WORKLOAD_CALICO_STARTUP_FAILURE_THRESHOLD}"
  printf -v probe_patch \
    '{"spec":{"template":{"spec":{"containers":[{"name":"calico-node","startupProbe":{"exec":{"command":["/bin/calico-node","-felix-live","-bird-live"]},"failureThreshold":%s,"periodSeconds":10,"timeoutSeconds":%s},"livenessProbe":{"failureThreshold":12,"timeoutSeconds":%s},"readinessProbe":{"failureThreshold":12,"timeoutSeconds":%s}}]}}}}' \
    "${WORKLOAD_CALICO_STARTUP_FAILURE_THRESHOLD}" \
    "${WORKLOAD_CALICO_PROBE_TIMEOUT_SECONDS}" \
    "${WORKLOAD_CALICO_PROBE_TIMEOUT_SECONDS}" \
    "${WORKLOAD_CALICO_PROBE_TIMEOUT_SECONDS}"
  kubectl --kubeconfig "${workload_kubeconfig}" -n kube-system patch \
    daemonset calico-node --type=strategic --patch "${probe_patch}" \
    >/dev/null
}

verify_cluster() {
  require_positive_integer WORKLOAD_STATUS_TIMEOUT_SECONDS "${WORKLOAD_STATUS_TIMEOUT_SECONDS}"
  python3 "${PROJECT_ROOT}/scripts/workload_state.py" "${1:-1}" \
    --wait "${WORKLOAD_STATUS_TIMEOUT_SECONDS}"
}

prepare_cluster() {
  require_management
  ensure_workload_api_access
  tune_calico_probes_for_gcp_capacity
  wait_for_calico_ready
}

probe_cluster() {
  python3 "${PROJECT_ROOT}/scripts/test_resources.py" probe
}

create_cluster() {
  require_management
  "${PROJECT_ROOT}/scripts/gcp-openstack-recover.sh"
  require_existing_floating_ip_route
  ensure_state_dirs
  local cluster_exists="no"
  if kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
      get cluster "${WORKLOAD_CLUSTER_NAME}" >/dev/null 2>&1; then
    cluster_exists="yes"
    # Reapplying this bootstrap manifest resets MD replicas to one.
    local installed_ca
    installed_ca="$(kubectl --kubeconfig "${management_kubeconfig}" \
        -n "${CLUSTER_AUTOSCALER_NAMESPACE}" get deployment cluster-autoscaler \
        --ignore-not-found -o name)" || die "cannot inspect Cluster Autoscaler before cluster reapply"
    if [[ -n "${installed_ca}" || -f "${STATE_DIR}/worker-control.json" || \
          -f "${STATE_DIR}/worker-operation.json" ]]; then
      die "existing autoscaled cluster: create would reset worker replicas; use prepare/status or an explicit worker mode"
    fi
  fi

  local external_network_id
  external_network_id="$(openstack_external_network_id)"
  [[ -n "${external_network_id}" ]] || die "OpenStack external network ID is empty"

  WORKLOAD_CLUSTER_NAME="${WORKLOAD_CLUSTER_NAME}" \
  WORKLOAD_NAMESPACE="${WORKLOAD_NAMESPACE}" \
  WORKLOAD_POD_CIDR="${WORKLOAD_POD_CIDR}" \
  WORKLOAD_SERVICE_CIDR="${WORKLOAD_SERVICE_CIDR}" \
  WORKLOAD_NETWORK_CIDR="${WORKLOAD_NETWORK_CIDR}" \
  WORKLOAD_DNS_NAMESERVER="${WORKLOAD_DNS_NAMESERVER}" \
  WORKLOAD_SSH_KEY_NAME="${WORKLOAD_SSH_KEY_NAME}" \
  OPENSTACK_FAILURE_DOMAIN="${OPENSTACK_FAILURE_DOMAIN}" \
  OPENSTACK_EXTERNAL_NETWORK_ID="${external_network_id}" \
  KUBERNETES_VERSION="${KUBERNETES_VERSION}" \
  KUBERNETES_IMAGE_NAME="${KUBERNETES_IMAGE_NAME}" \
  KUBERNETES_CONTROL_PLANE_FLAVOR="${KUBERNETES_CONTROL_PLANE_FLAVOR}" \
  KUBERNETES_WORKER_FLAVOR="${KUBERNETES_WORKER_FLAVOR}" \
    "${PROJECT_ROOT}/scripts/render-template.py" "${cluster_template}" "${cluster_manifest}"

  if [[ "${cluster_exists}" == "yes" ]]; then
    log "Reconciling and resuming existing ${WORKLOAD_CLUSTER_NAME} baseline"
  else
    log "Creating ${WORKLOAD_CLUSTER_NAME} with one control plane and one worker"
  fi
  kubectl --kubeconfig "${management_kubeconfig}" apply -f "${cluster_manifest}"
  wait_for_secret "${WORKLOAD_CLUSTER_NAME}-kubeconfig"
  write_workload_kubeconfig
  wait_for_workload_api

  ensure_pinned_download "${calico_url}" "${calico_manifest}" "${CALICO_MANIFEST_SHA256}"
  log "Installing Calico ${CALICO_VERSION}"
  kubectl --kubeconfig "${workload_kubeconfig}" apply -f "${calico_manifest}"
  prepare_cluster
  verify_cluster 1
  probe_cluster
}

quiesce_autoscaler_for_manual_scaling() {
  local autoscaler_pods

  ensure_workload_api_access
  local existing_ca
  existing_ca="$(kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${CLUSTER_AUTOSCALER_NAMESPACE}" get deployment cluster-autoscaler --ignore-not-found -o name)"
  if [[ -n "${existing_ca}" ]]; then
    autoscaler_replicas_before_manual_scaling="$(kubectl \
      --kubeconfig "${management_kubeconfig}" \
      -n "${CLUSTER_AUTOSCALER_NAMESPACE}" get deployment \
      cluster-autoscaler -o jsonpath='{.spec.replicas}')"
    printf '%s\n' "${autoscaler_replicas_before_manual_scaling}" >"${run_dir}/autoscaler-original-replicas.txt"
    trap 'resume_autoscaler_after_manual_scaling || { warn "failed to restore Cluster Autoscaler; see ${manual_scaling_run_dir}"; exit 1; }' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    log "Suspending Cluster Autoscaler during manual worker scaling"
    kubectl --kubeconfig "${management_kubeconfig}" \
      -n "${CLUSTER_AUTOSCALER_NAMESPACE}" scale deployment \
      cluster-autoscaler --replicas=0 >/dev/null
    autoscaler_pods="$(kubectl --kubeconfig "${management_kubeconfig}" \
      -n "${CLUSTER_AUTOSCALER_NAMESPACE}" get pods \
      -l app.kubernetes.io/name=cluster-autoscaler -o name)"
    if [[ -n "${autoscaler_pods}" ]]; then
      kubectl --kubeconfig "${management_kubeconfig}" \
        -n "${CLUSTER_AUTOSCALER_NAMESPACE}" wait --for=delete pod \
        -l app.kubernetes.io/name=cluster-autoscaler --timeout=2m
    fi
  fi

  log "Preserving and removing repository-owned test resources before manual scaling"
  python3 "${PROJECT_ROOT}/scripts/test_resources.py" cleanup
}

resume_autoscaler_after_manual_scaling() {
  trap - EXIT
  [[ -n "${autoscaler_replicas_before_manual_scaling}" ]] || return 0

  local replicas="${autoscaler_replicas_before_manual_scaling}"
  log "Restoring Cluster Autoscaler to ${replicas} replica(s)"
  kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${CLUSTER_AUTOSCALER_NAMESPACE}" scale deployment \
    cluster-autoscaler --replicas="${replicas}" >/dev/null || return 1
  if [[ "${replicas}" != "0" ]]; then
    kubectl --kubeconfig "${management_kubeconfig}" \
      -n "${CLUSTER_AUTOSCALER_NAMESPACE}" rollout status \
      deployment/cluster-autoscaler --timeout=5m || return 1
  fi
  autoscaler_replicas_before_manual_scaling=""
  printf 'restored=%s\n' "${replicas}" >"${manual_scaling_run_dir}/autoscaler-restored.txt"
}

scale_workers() {
  local target="${1:-2}" desired run_dir started
  [[ "${target}" =~ ^[1-3]$ ]] || die "WORKERS must be within 1:3"
  require_management
  ensure_workload_api_access
  run_dir="$(current_or_new_run)/manual-$(utc_timestamp)-$$"
  mkdir_private "${run_dir}"
  # EXIT runs after the function's local variables have left scope on failure.
  manual_scaling_run_dir="${run_dir}"
  quiesce_autoscaler_for_manual_scaling
  desired="$(kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    get machinedeployment "${machine_deployment}" -o jsonpath='{.spec.replicas}')"
  [[ "${desired}" =~ ^[1-3]$ ]] || die "existing desired replicas outside 1:3: ${desired}"
  if [[ -n "${WORKER_CONTROL_EXPECTED_FROM:-}" && "${desired}" != "${WORKER_CONTROL_EXPECTED_FROM}" ]]; then
    die "worker desired replicas changed while suspending CA: expected ${WORKER_CONTROL_EXPECTED_FROM}, found ${desired}"
  fi
  started="$(date +%s)"
  printf 'status=in_progress\nfrom=%s\nto=%s\nstarted_epoch=%s\n' \
    "${desired}" "${target}" "${started}" >"${run_dir}/timing.txt"
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    scale machinedeployment "${machine_deployment}" --replicas="${target}"
  verify_cluster "${target}"
  probe_cluster
  printf 'status=passed\nfinished_epoch=%s\n' "$(date +%s)" >>"${run_dir}/timing.txt"
  resume_autoscaler_after_manual_scaling
}

destroy_cluster() {
  [[ "${2:-}" == "${ENV}" ]] ||
    die "refusing workload deletion without CONFIRM=${ENV}"
  [[ "${3:-}" == "${WORKLOAD_CLUSTER_NAME}" ]] ||
    die "refusing workload deletion without CONFIRM_CLUSTER=${WORKLOAD_CLUSTER_NAME}"
  require_management
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    delete cluster "${WORKLOAD_CLUSTER_NAME}" --wait=true --timeout=30m
  "${PROJECT_ROOT}/scripts/gcp-workload-api-tunnel.sh" stop
  log "deleted only Cluster ${WORKLOAD_NAMESPACE}/${WORKLOAD_CLUSTER_NAME}; namespace and secrets preserved"
}

case "${action}" in
  create) python3 "${PROJECT_ROOT}/scripts/autoscaler_cycle.py" create ;;
  create-unlocked)
    [[ -n "${WORKER_CONTROL_LOCK_FD:-}" && -e "/dev/fd/${WORKER_CONTROL_LOCK_FD}" ]] ||
      die "create-unlocked requires the worker control runner"
    create_cluster
    ;;
  status) python3 "${PROJECT_ROOT}/scripts/workload_state.py" "${2:-1}" ;;
  verify) verify_cluster "${2:-1}" ;;
  prepare) prepare_cluster ;;
  probe) python3 "${PROJECT_ROOT}/scripts/autoscaler_cycle.py" probe ;;
  capi-ready)
    require_management
    wait_for_control_plane_available
    ;;
  scale) python3 "${PROJECT_ROOT}/scripts/autoscaler_cycle.py" manual "${2:-2}" ;;
  scale-unlocked)
    [[ -n "${WORKER_CONTROL_LOCK_FD:-}" && -e "/dev/fd/${WORKER_CONTROL_LOCK_FD}" ]] ||
      die "scale-unlocked requires the worker control runner"
    scale_workers "${2:-2}"
    ;;
  diagnostics)
    require_management
    if [[ -f "${workload_kubeconfig}" ]]; then
      ensure_workload_api_access
    fi
    capture_failure_diagnostics "manual"
    ;;
  destroy) python3 "${PROJECT_ROOT}/scripts/autoscaler_cycle.py" destroy "${2:-}" "${3:-}" ;;
  destroy-unlocked)
    [[ -n "${WORKER_CONTROL_LOCK_FD:-}" && -e "/dev/fd/${WORKER_CONTROL_LOCK_FD}" ]] ||
      die "destroy-unlocked requires the worker control runner"
    destroy_cluster "$@"
    ;;
  *) die "usage: $0 {create|prepare|status [workers]|verify [workers]|probe|capi-ready|scale|diagnostics|destroy CONFIRM CONFIRM_CLUSTER}" ;;
esac
