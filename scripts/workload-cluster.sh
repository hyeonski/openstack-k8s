#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

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

ensure_pinned_download() {
  local url="$1"
  local destination="$2"
  local checksum="$3"
  local temporary="${destination}.download"

  require_command curl
  require_command shasum
  mkdir_private "$(dirname "${destination}")"
  if [[ -f "${destination}" ]] &&
    printf '%s  %s\n' "${checksum}" "${destination}" | shasum -a 256 -c - >/dev/null 2>&1; then
    return
  fi
  rm -f "${temporary}"
  curl -fL --retry 3 --output "${temporary}" "${url}"
  printf '%s  %s\n' "${checksum}" "${temporary}" | shasum -a 256 -c -
  chmod 600 "${temporary}"
  mv "${temporary}" "${destination}"
}

require_management() {
  require_command kubectl
  if [[ "${HOST_PROVIDER}" == "gcp" ]]; then
    require_command gcloud
  else
    require_command limactl
  fi
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
  local expected_gateway route_info route_gateway route_destination route_next_hop route_name
  case "${HOST_PROVIDER}" in
    gcp)
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
      ;;
    lima)
      require_command route
      expected_gateway="$(controller_ipv4)"
      route_info="$(route -n get "${EXTERNAL_ALLOCATION_POOL_START}" 2>/dev/null || true)"
      route_gateway="$(awk '/gateway:/{print $2; exit}' <<<"${route_info}")"
      route_destination="$(awk '/destination:/{print $2; exit}' <<<"${route_info}")"
      if [[ "${route_destination}" == "default" || "${route_gateway}" != "${expected_gateway}" ]]; then
        die "project Floating IP route is not installed; approval is required before changing the host route"
      fi
      ;;
    *)
      die "unsupported host provider for Floating IP route verification: ${HOST_PROVIDER}"
      ;;
  esac
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

nova_server_count() {
  run_on "${CONTROLLER_NAME}" env WORKLOAD_CLUSTER_NAME="${WORKLOAD_CLUSTER_NAME}" bash -lc '
    set -Eeuo pipefail
    source /opt/kolla-venv/bin/activate
    export OS_CLIENT_CONFIG_FILE=/etc/kolla/capi-clouds.yaml
    openstack --os-cloud capi server list -f value -c Name
  ' | awk -v prefix="${WORKLOAD_CLUSTER_NAME}" 'index($0, prefix) == 1 {count++} END {print count + 0}'
}

wait_for_node_count() {
  local expected="$1"
  local attempts="${2:-360}"
  local attempt count
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    count="$(kubectl --kubeconfig "${workload_kubeconfig}" get nodes \
      -o name 2>/dev/null | wc -l | tr -d ' ')"
    if [[ "${count}" == "${expected}" ]]; then
      if ! kubectl --kubeconfig "${workload_kubeconfig}" wait \
          --for=condition=Ready nodes --all --timeout="${WORKLOAD_NODE_READY_TIMEOUT}"; then
        capture_failure_diagnostics "node-ready-timeout"
        die "workload nodes did not become Ready within ${WORKLOAD_NODE_READY_TIMEOUT}"
      fi
      return
    fi
    sleep 5
  done
  capture_failure_diagnostics "node-count-timeout"
  die "timed out waiting for ${expected} workload nodes; found ${count:-0}"
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

wait_for_available_workers() {
  local expected="$1"
  local attempts="${2:-360}"
  local attempt available
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    available="$(kubectl --kubeconfig "${management_kubeconfig}" \
      -n "${WORKLOAD_NAMESPACE}" get machinedeployment "${machine_deployment}" \
      -o jsonpath='{.status.availableReplicas}' 2>/dev/null || true)"
    if [[ "${available}" == "${expected}" ]]; then
      return
    fi
    sleep 5
  done
  capture_failure_diagnostics "worker-available-timeout"
  die "timed out waiting for ${expected} available workers; found ${available:-0}"
}

wait_for_machine_identity() {
  local expected="$1"
  local attempts="${2:-360}"
  local attempt machine_count complete_count
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    machine_count="$(kubectl --kubeconfig "${management_kubeconfig}" \
      -n "${WORKLOAD_NAMESPACE}" get machines \
      -l "cluster.x-k8s.io/cluster-name=${WORKLOAD_CLUSTER_NAME}" \
      -o name 2>/dev/null | wc -l | tr -d ' ')"
    complete_count="$(kubectl --kubeconfig "${management_kubeconfig}" \
      -n "${WORKLOAD_NAMESPACE}" get machines \
      -l "cluster.x-k8s.io/cluster-name=${WORKLOAD_CLUSTER_NAME}" \
      -o jsonpath='{range .items[*]}{range .status.addresses[?(@.type=="InternalIP")]}{.address}{end}{"\t"}{.spec.providerID}{"\n"}{end}' \
      2>/dev/null | awk -F '\t' '$1 != "" && $2 ~ /^openstack:\/\/\// {count++} END {print count + 0}')"
    if [[ "${machine_count}" == "${expected}" && "${complete_count}" == "${expected}" ]]; then
      return
    fi
    sleep 5
  done
  capture_failure_diagnostics "machine-identity-timeout"
  die "timed out waiting for ${expected} Machines with InternalIP and OpenStack providerID; found ${complete_count:-0}/${machine_count:-0}"
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

run_management_api_probe() {
  local endpoint probe_name
  endpoint="$(kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${WORKLOAD_NAMESPACE}" get cluster "${WORKLOAD_CLUSTER_NAME}" \
    -o jsonpath='{.spec.controlPlaneEndpoint.host}')"
  [[ -n "${endpoint}" ]] || die "workload control plane endpoint is empty"
  probe_name="${WORKLOAD_CLUSTER_NAME}-api-probe"
  if kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
      get pod "${probe_name}" >/dev/null 2>&1; then
    die "existing workload API probe must be inspected before retry: ${probe_name}"
  fi
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" run \
    "${probe_name}" --image=busybox:1.37.0 --restart=Never --command -- \
    sh -ceu "nc -z -w 15 '${endpoint}' 6443"
  if ! kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" wait \
      --for=jsonpath='{.status.phase}'=Succeeded "pod/${probe_name}" --timeout=3m; then
    kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
      describe pod "${probe_name}" || true
    die "management-to-workload API probe failed; pod preserved"
  fi
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    delete pod "${probe_name}" --wait=false >/dev/null
}

run_cni_probe() {
  local probe_name="${WORKLOAD_CLUSTER_NAME}-cni-probe"
  if kubectl --kubeconfig "${workload_kubeconfig}" -n default get pod \
      "${probe_name}" >/dev/null 2>&1; then
    die "existing CNI probe must be inspected before retry: ${probe_name}"
  fi
  kubectl --kubeconfig "${workload_kubeconfig}" -n default run "${probe_name}" \
    --image=busybox:1.37.0 --restart=Never --command -- \
    sh -ceu 'nslookup kubernetes.default.svc.cluster.local >/dev/null'
  if ! kubectl --kubeconfig "${workload_kubeconfig}" -n default wait \
      --for=jsonpath='{.status.phase}'=Succeeded "pod/${probe_name}" --timeout=5m; then
    kubectl --kubeconfig "${workload_kubeconfig}" -n default describe pod \
      "${probe_name}" || true
    die "workload DNS/CNI probe failed; pod preserved"
  fi
  kubectl --kubeconfig "${workload_kubeconfig}" -n default delete pod \
    "${probe_name}" --wait=false >/dev/null
}

tune_calico_probes_for_local_capacity() {
  local probe_patch
  # Three nested Nova guests fully consume the local compute profile's four
  # vCPUs during first boot. A startup probe prevents liveness from restarting
  # Calico while images, BIRD and Felix are still converging. The regular
  # probes also need enough wall time to be scheduled on a saturated local
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

capture_status() {
  local expected_workers="$1"
  local run_dir status_dir
  run_dir="$(current_or_new_run)"
  status_dir="${run_dir}/m2"
  mkdir -p "${status_dir}"
  chmod 700 "${status_dir}"

  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" get \
    clusters,machinedeployments,machines,kubeadmcontrolplanes,openstackclusters,openstackmachines \
    -o wide >"${status_dir}/capi-resources-workers-${expected_workers}.txt"
  kubectl --kubeconfig "${workload_kubeconfig}" get nodes -o wide \
    >"${status_dir}/workload-nodes-workers-${expected_workers}.txt"
  kubectl --kubeconfig "${workload_kubeconfig}" get pods -A -o wide \
    >"${status_dir}/workload-pods-workers-${expected_workers}.txt"
  run_on "${CONTROLLER_NAME}" env WORKLOAD_CLUSTER_NAME="${WORKLOAD_CLUSTER_NAME}" bash -lc '
    set -Eeuo pipefail
    source /opt/kolla-venv/bin/activate
    export OS_CLIENT_CONFIG_FILE=/etc/kolla/capi-clouds.yaml
    openstack --os-cloud capi server list --name "${WORKLOAD_CLUSTER_NAME}"
  ' >"${status_dir}/openstack-servers-workers-${expected_workers}.txt"
}

verify_cluster() {
  local expected_workers="${1:-1}"
  local expected_nodes expected_machines node_count machine_count server_count
  expected_nodes=$((expected_workers + 1))
  expected_machines="${expected_nodes}"

  require_kubectl_timeout WORKLOAD_NODE_READY_TIMEOUT "${WORKLOAD_NODE_READY_TIMEOUT}"
  require_kubectl_timeout WORKLOAD_CALICO_READY_TIMEOUT "${WORKLOAD_CALICO_READY_TIMEOUT}"

  require_management
  [[ -f "${workload_kubeconfig}" ]] || die "workload kubeconfig is missing"
  wait_for_machine_identity "${expected_machines}"
  if [[ "${HOST_PROVIDER}" == "lima" ]]; then
    "${PROJECT_ROOT}/scripts/workload-clock.sh" check
  fi
  tune_calico_probes_for_local_capacity
  wait_for_available_workers "${expected_workers}"
  wait_for_node_count "${expected_nodes}"
  wait_for_control_plane_available

  node_count="$(kubectl --kubeconfig "${workload_kubeconfig}" get nodes -o name | wc -l | tr -d ' ')"
  [[ "${node_count}" == "${expected_nodes}" ]] || die "unexpected workload node count: ${node_count}"
  machine_count="$(kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    get machines -o name | wc -l | tr -d ' ')"
  [[ "${machine_count}" == "${expected_machines}" ]] || die "unexpected Machine count: ${machine_count}"
  server_count="$(nova_server_count)"
  [[ "${server_count}" == "${expected_machines}" ]] || die "unexpected Nova server count: ${server_count}"

  while IFS=$'\t' read -r node version architecture provider_id; do
    [[ "${version}" == "${KUBERNETES_VERSION}" ]] ||
      die "unexpected Kubernetes version on ${node}: ${version}"
    [[ "${architecture}" == "${WORKLOAD_KUBERNETES_ARCHITECTURE}" ]] ||
      die "unexpected architecture on ${node}: ${architecture}; expected ${WORKLOAD_KUBERNETES_ARCHITECTURE}"
    [[ "${provider_id}" == openstack:///* ]] || die "missing OpenStack providerID on ${node}"
  done < <(kubectl --kubeconfig "${workload_kubeconfig}" get nodes \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.nodeInfo.kubeletVersion}{"\t"}{.status.nodeInfo.architecture}{"\t"}{.spec.providerID}{"\n"}{end}')

  wait_for_calico_ready
  kubectl --kubeconfig "${workload_kubeconfig}" -n kube-system wait \
    --for=condition=Ready pod -l k8s-app=calico-kube-controllers --timeout=5m
  run_management_api_probe
  run_cni_probe
  capture_status "${expected_workers}"

  "${clusterctl_bin}" describe cluster "${WORKLOAD_CLUSTER_NAME}" \
    --namespace "${WORKLOAD_NAMESPACE}" \
    --config "${clusterctl_config}" \
    --kubeconfig "${management_kubeconfig}"
  kubectl --kubeconfig "${workload_kubeconfig}" get nodes -o wide
  log "workload cluster passed with ${expected_workers} Ready worker(s)"
}

create_cluster() {
  require_management
  require_existing_floating_ip_route
  ensure_state_dirs
  if kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
      get cluster "${WORKLOAD_CLUSTER_NAME}" >/dev/null 2>&1; then
    die "workload Cluster already exists: ${WORKLOAD_NAMESPACE}/${WORKLOAD_CLUSTER_NAME}"
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

  log "Creating ${WORKLOAD_CLUSTER_NAME} with one control plane and one worker"
  kubectl --kubeconfig "${management_kubeconfig}" apply -f "${cluster_manifest}"
  wait_for_secret "${WORKLOAD_CLUSTER_NAME}-kubeconfig"
  write_workload_kubeconfig
  wait_for_workload_api

  ensure_pinned_download "${calico_url}" "${calico_manifest}" "${CALICO_MANIFEST_SHA256}"
  log "Installing Calico ${CALICO_VERSION}"
  kubectl --kubeconfig "${workload_kubeconfig}" apply -f "${calico_manifest}"
  verify_cluster 1
}

scale_workers_up() {
  require_management
  [[ -f "${workload_kubeconfig}" ]] || die "workload kubeconfig is missing"

  local available desired started finished run_dir timing_file timing_status
  run_dir="$(current_or_new_run)"
  mkdir -p "${run_dir}/m2"
  chmod 700 "${run_dir}/m2"
  timing_file="${run_dir}/m2/manual-scale-1-to-2.txt"

  desired="$(kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${WORKLOAD_NAMESPACE}" get machinedeployment "${machine_deployment}" \
    -o jsonpath='{.spec.replicas}')"
  available="$(kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${WORKLOAD_NAMESPACE}" get machinedeployment "${machine_deployment}" \
    -o jsonpath='{.status.availableReplicas}')"
  if [[ "${desired}" == "2" ]]; then
    log "${machine_deployment} already desires two workers; resuming verification from available=${available:-0}"
    timing_status="$(awk -F= '$1 == "status" { print $2; exit }' "${timing_file}" 2>/dev/null || true)"
    started="$(awk -F= '$1 == "started_epoch" { print $2; exit }' "${timing_file}" 2>/dev/null || true)"
    verify_cluster 2
    if [[ "${timing_status}" == "in_progress" && "${started}" =~ ^[0-9]+$ ]]; then
      finished="$(date +%s)"
      {
        printf 'status=passed_after_resume\n'
        printf 'started_epoch=%s\n' "${started}"
        printf 'ready_epoch=%s\n' "${finished}"
        printf 'elapsed_seconds=%s\n' "$((finished - started))"
      } >"${timing_file}"
      chmod 600 "${timing_file}"
    elif [[ -z "${timing_status}" ]]; then
      {
        printf 'status=verified_at_two\n'
        printf 'verified_utc=%s\n' "$(date -u +%FT%TZ)"
      } >"${timing_file}"
      chmod 600 "${timing_file}"
    fi
    return
  fi
  [[ "${desired}" == "1" && "${available}" == "1" ]] ||
    die "manual scale requires desired=1 and available=1; found desired=${desired}, available=${available:-0}"

  started="$(date +%s)"
  {
    printf 'status=in_progress\n'
    printf 'started_epoch=%s\n' "${started}"
    printf 'started_utc=%s\n' "$(date -u +%FT%TZ)"
  } >"${timing_file}"
  chmod 600 "${timing_file}"

  log "Scaling ${machine_deployment} from 1 to 2 workers"
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    scale machinedeployment "${machine_deployment}" --replicas=2
  verify_cluster 2
  finished="$(date +%s)"

  {
    printf 'status=passed\n'
    printf 'started_epoch=%s\n' "${started}"
    printf 'ready_epoch=%s\n' "${finished}"
    printf 'elapsed_seconds=%s\n' "$((finished - started))"
  } >"${timing_file}"
}

scale_workers_down() {
  require_management
  [[ -f "${workload_kubeconfig}" ]] || die "workload kubeconfig is missing"

  local desired available started finished run_dir timing_file
  run_dir="$(current_or_new_run)"
  mkdir -p "${run_dir}/m3"
  chmod 700 "${run_dir}/m3"
  timing_file="${run_dir}/m3/manual-scale-2-to-1.txt"
  desired="$(kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${WORKLOAD_NAMESPACE}" get machinedeployment "${machine_deployment}" \
    -o jsonpath='{.spec.replicas}')"
  available="$(kubectl --kubeconfig "${management_kubeconfig}" \
    -n "${WORKLOAD_NAMESPACE}" get machinedeployment "${machine_deployment}" \
    -o jsonpath='{.status.availableReplicas}')"
  if [[ "${desired}" == "1" ]]; then
    log "${machine_deployment} already desires one worker; verifying cleanup"
    verify_cluster 1
    return
  fi
  [[ "${desired}" == "2" && "${available}" == "2" ]] ||
    die "scale-down preparation requires desired=2 available=2; found desired=${desired}, available=${available:-0}"

  started="$(date +%s)"
  printf 'status=in_progress\nstarted_epoch=%s\nstarted_utc=%s\n' \
    "${started}" "$(date -u +%FT%TZ)" >"${timing_file}"
  chmod 600 "${timing_file}"
  log "Scaling ${machine_deployment} from 2 to 1 worker for the M3 baseline"
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    scale machinedeployment "${machine_deployment}" --replicas=1
  verify_cluster 1
  finished="$(date +%s)"
  printf 'status=passed\nstarted_epoch=%s\nready_epoch=%s\nelapsed_seconds=%s\n' \
    "${started}" "${finished}" "$((finished - started))" >"${timing_file}"
  chmod 600 "${timing_file}"
}

scale_workers() {
  case "${1:-2}" in
    1) scale_workers_down ;;
    2) scale_workers_up ;;
    *) die "WORKERS must be 1 or 2 for workload-cluster-scale" ;;
  esac
}

destroy_cluster() {
  [[ "${2:-}" == "${ENV}" ]] ||
    die "refusing workload deletion without CONFIRM=${ENV}"
  [[ "${3:-}" == "${WORKLOAD_CLUSTER_NAME}" ]] ||
    die "refusing workload deletion without CONFIRM_CLUSTER=${WORKLOAD_CLUSTER_NAME}"
  require_management
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    delete cluster "${WORKLOAD_CLUSTER_NAME}" --wait=true --timeout=30m
  log "deleted only Cluster ${WORKLOAD_NAMESPACE}/${WORKLOAD_CLUSTER_NAME}; namespace and secrets preserved"
}

case "${action}" in
  create) create_cluster ;;
  verify) verify_cluster "${2:-1}" ;;
  capi-ready)
    require_management
    wait_for_control_plane_available
    ;;
  scale) scale_workers "${2:-2}" ;;
  diagnostics) capture_failure_diagnostics "manual" ;;
  destroy) destroy_cluster "$@" ;;
  *) die "usage: $0 {create|verify [workers]|capi-ready|scale|diagnostics|destroy CONFIRM CONFIRM_CLUSTER}" ;;
esac
