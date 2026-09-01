#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

require_command gcloud
require_command kubectl
require_command curl
require_command nc
require_command shasum
require_command python3
require_command sed

action="${1:-}"
confirmation="${2:-}"
runtime_host="${MANAGEMENT_RUNTIME_HOST_NAME:-${CONTROLLER_NAME}}"
kind_dir="${STATE_DIR}/bin"
kind_binary="${kind_dir}/kind-linux-amd64"
kubeconfig_dir="${STATE_DIR}/kubeconfigs"
kubeconfig="${kubeconfig_dir}/management.yaml"
tunnel_pid_file="${STATE_DIR}/management-iap-tunnel.pid"
tunnel_log="${STATE_DIR}/management-iap-tunnel.log"
remote_kind="/usr/local/bin/kind"
remote_config="/tmp/openstack-k8s-kind-management.yaml"
remote_network_script="/usr/local/sbin/openstack-k8s-kind-network"
rendered_config="${STATE_DIR}/kind-management-gcp.yaml"
rendered_network_env="${STATE_DIR}/controller-kind-network.env"
kind_url="https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/kind-linux-amd64"

ensure_kind_binary() {
  ensure_pinned_download \
    "${kind_url}" "${kind_binary}" "${KIND_LINUX_AMD64_SHA256}" 0700
}

run_kind() {
  run_on "${runtime_host}" sudo "${remote_kind}" "$@"
}

cluster_exists() {
  instance_running "${runtime_host}" &&
    run_kind get clusters 2>/dev/null | grep -Fxq "${MANAGEMENT_CLUSTER_NAME}"
}

cluster_api_endpoint_matches() {
  run_on "${runtime_host}" sudo docker port \
    "${MANAGEMENT_CLUSTER_NAME}-control-plane" 6443/tcp 2>/dev/null |
    grep -Fxq "${MANAGEMENT_API_ADDRESS}:${MANAGEMENT_REMOTE_API_PORT}"
}

cluster_tls_san_matches() {
  local sans
  sans="$(run_on "${runtime_host}" sudo docker exec \
    "${MANAGEMENT_CLUSTER_NAME}-control-plane" openssl x509 \
    -in /etc/kubernetes/pki/apiserver.crt -noout -ext subjectAltName \
    2>/dev/null)"
  grep -Fq "IP Address:127.0.0.1" <<<"${sans}" &&
    grep -Fq "IP Address:${MANAGEMENT_API_ADDRESS}" <<<"${sans}"
}

cluster_network_matches() {
  run_on "${runtime_host}" sudo docker network inspect \
    "${MANAGEMENT_DOCKER_NETWORK}" --format '{{json .Containers}}' 2>/dev/null |
    grep -Fq "${MANAGEMENT_CLUSTER_NAME}-control-plane"
}

render_remote_inputs() {
  ensure_state_dirs
  sed \
    -e "s/__MANAGEMENT_API_ADDRESS__/${MANAGEMENT_API_ADDRESS}/g" \
    -e "s/__MANAGEMENT_REMOTE_API_PORT__/${MANAGEMENT_REMOTE_API_PORT}/g" \
    "${PROJECT_ROOT}/kubernetes/kind-management-gcp.yaml" >"${rendered_config}"
  chmod 600 "${rendered_config}"

  printf '%s\n' \
    "MANAGEMENT_DOCKER_NETWORK=${MANAGEMENT_DOCKER_NETWORK}" \
    "MANAGEMENT_DOCKER_CIDR=${MANAGEMENT_DOCKER_CIDR}" \
    "MANAGEMENT_DOCKER_BRIDGE=${MANAGEMENT_DOCKER_BRIDGE}" \
    >"${rendered_network_env}"
  chmod 600 "${rendered_network_env}"
}

prepare_controller_runtime() {
  instance_running "${runtime_host}" ||
    die "management runtime host is stopped: ${runtime_host}"

  run_on "${runtime_host}" sudo jq -e \
    '.bridge == "none" and .iptables == false and .["ip-forward"] == false' \
    /etc/docker/daemon.json >/dev/null ||
    die "refusing to change or bypass the declared Kolla Docker daemon boundary"
  [[ "$(run_on "${runtime_host}" sysctl -n net.ipv4.ip_forward)" == "1" ]] ||
    die "controller kernel IPv4 forwarding is disabled"

  copy_to "${PROJECT_ROOT}/scripts/controller-kind-network.sh" \
    "${runtime_host}" /tmp/openstack-k8s-kind-network
  copy_to "${PROJECT_ROOT}/systemd/openstack-k8s-kind-network.service" \
    "${runtime_host}" /tmp/openstack-k8s-kind-network.service
  copy_to "${rendered_network_env}" \
    "${runtime_host}" /tmp/openstack-k8s-kind-network.env
  run_on "${runtime_host}" sudo install -m 0755 \
    /tmp/openstack-k8s-kind-network "${remote_network_script}"
  run_on "${runtime_host}" sudo install -m 0644 \
    /tmp/openstack-k8s-kind-network.service \
    /etc/systemd/system/openstack-k8s-kind-network.service
  run_on "${runtime_host}" sudo install -m 0600 \
    /tmp/openstack-k8s-kind-network.env \
    /etc/default/openstack-k8s-kind-network
  run_on "${runtime_host}" rm -f \
    /tmp/openstack-k8s-kind-network \
    /tmp/openstack-k8s-kind-network.service \
    /tmp/openstack-k8s-kind-network.env
  run_on "${runtime_host}" sudo systemctl daemon-reload
  run_on "${runtime_host}" sudo systemctl enable \
    openstack-k8s-kind-network.service >/dev/null
  run_on "${runtime_host}" sudo systemctl restart \
    openstack-k8s-kind-network.service
  run_on "${runtime_host}" sudo systemctl is-active --quiet \
    openstack-k8s-kind-network.service
}

tunnel_running() {
  managed_process_matches "${tunnel_pid_file}" "start-iap-tunnel" || return 1
  local pid
  pid="$(<"${tunnel_pid_file}")"
  ps -p "${pid}" -o command= 2>/dev/null |
    grep -Fq "start-iap-tunnel ${runtime_host} ${MANAGEMENT_REMOTE_API_PORT}"
}

stop_tunnel() {
  stop_managed_process "${tunnel_pid_file}" "start-iap-tunnel"
}

start_tunnel() {
  ensure_state_dirs
  if tunnel_running && nc -z 127.0.0.1 "${MANAGEMENT_LOCAL_API_PORT}" 2>/dev/null; then
    return
  fi
  stop_tunnel
  if nc -z 127.0.0.1 "${MANAGEMENT_LOCAL_API_PORT}" 2>/dev/null; then
    die "local port ${MANAGEMENT_LOCAL_API_PORT} is already used by another process"
  fi

  nohup gcloud compute start-iap-tunnel \
    "${runtime_host}" "${MANAGEMENT_REMOTE_API_PORT}" \
    --local-host-port="127.0.0.1:${MANAGEMENT_LOCAL_API_PORT}" \
    --project="${GCP_PROJECT_ID}" --zone="${GCP_ZONE}" \
    --verbosity=warning >"${tunnel_log}" 2>&1 </dev/null &
  local tunnel_pid="$!"
  printf '%s\n' "${tunnel_pid}" >"${tunnel_pid_file}"
  chmod 600 "${tunnel_pid_file}" "${tunnel_log}"

  for _ in {1..60}; do
    if ! kill -0 "${tunnel_pid}" 2>/dev/null; then
      sed -n '1,120p' "${tunnel_log}" >&2 || true
      die "management API IAP tunnel exited"
    fi
    if nc -z 127.0.0.1 "${MANAGEMENT_LOCAL_API_PORT}" 2>/dev/null; then
      log "Management API IAP tunnel is ready on 127.0.0.1:${MANAGEMENT_LOCAL_API_PORT}"
      return
    fi
    sleep 1
  done
  stop_tunnel
  die "management API IAP tunnel did not become ready"
}

fetch_kubeconfig() {
  mkdir_private "${kubeconfig_dir}"
  run_kind get kubeconfig --name "${MANAGEMENT_CLUSTER_NAME}" >"${kubeconfig}.tmp"
  chmod 600 "${kubeconfig}.tmp"
  KUBECONFIG="${kubeconfig}.tmp" kubectl config set-cluster \
    "kind-${MANAGEMENT_CLUSTER_NAME}" \
    --server="https://127.0.0.1:${MANAGEMENT_LOCAL_API_PORT}" >/dev/null
  mv "${kubeconfig}.tmp" "${kubeconfig}"
}

run_probe() {
  local probe_name="$1"
  local probe_url="$2"
  kubectl --kubeconfig "${kubeconfig}" delete pod "${probe_name}" \
    --ignore-not-found --wait=false >/dev/null 2>&1 || true
  kubectl --kubeconfig "${kubeconfig}" run "${probe_name}" \
    --image=busybox:1.37.0 --restart=Never --command -- \
    sh -c "wget -qO- -T 15 '${probe_url}' >/dev/null"
  if ! kubectl --kubeconfig "${kubeconfig}" wait \
      --for=jsonpath='{.status.phase}'=Succeeded "pod/${probe_name}" --timeout=180s; then
    kubectl --kubeconfig "${kubeconfig}" describe pod "${probe_name}" || true
    kubectl --kubeconfig "${kubeconfig}" logs "${probe_name}" || true
    die "management-cluster network probe failed: ${probe_url}"
  fi
  kubectl --kubeconfig "${kubeconfig}" delete pod "${probe_name}" \
    --wait=false >/dev/null
}

verify_resource_headroom() {
  local available_kib disk_available_kib
  available_kib="$(run_on "${runtime_host}" awk \
    '/^MemAvailable:/ {print $2}' /proc/meminfo)"
  disk_available_kib="$(run_on "${runtime_host}" df --output=avail / | tail -n 1 | tr -d ' ')"
  (( available_kib >= 3 * 1024 * 1024 )) ||
    die "controller has less than 3 GiB available memory after kind startup"
  (( disk_available_kib >= 20 * 1024 * 1024 )) ||
    die "controller has less than 20 GiB available disk after kind startup"
  printf '%s %s\n' "${available_kib}" "${disk_available_kib}"
}

verify_cluster() {
  instance_running "${runtime_host}" ||
    die "management runtime host is stopped; run make gcp-start"
  cluster_exists || die "kind cluster not found on ${runtime_host}: ${MANAGEMENT_CLUSTER_NAME}"
  run_on "${runtime_host}" sudo systemctl is-active --quiet \
    openstack-k8s-kind-network.service
  run_on "${runtime_host}" sudo env \
    MANAGEMENT_DOCKER_NETWORK="${MANAGEMENT_DOCKER_NETWORK}" \
    MANAGEMENT_DOCKER_CIDR="${MANAGEMENT_DOCKER_CIDR}" \
    MANAGEMENT_DOCKER_BRIDGE="${MANAGEMENT_DOCKER_BRIDGE}" \
    "${remote_network_script}" verify
  cluster_api_endpoint_matches || die "unexpected controller kind API binding"
  cluster_network_matches || die "kind node is not attached to the isolated controller network"
  cluster_tls_san_matches || die "controller kind API certificate SAN mismatch"
  [[ -f "${kubeconfig}" ]] || fetch_kubeconfig
  start_tunnel

  kubectl --kubeconfig "${kubeconfig}" get --raw=/readyz >/dev/null
  kubectl --kubeconfig "${kubeconfig}" wait \
    --for=condition=Ready nodes --all --timeout=180s
  kubectl --kubeconfig "${kubeconfig}" wait \
    --for=condition=Ready pods --all --namespace kube-system --timeout=180s

  local architecture server_version
  architecture="$(kubectl --kubeconfig "${kubeconfig}" get nodes \
    -o jsonpath='{.items[0].status.nodeInfo.architecture}')"
  [[ "${architecture}" == "${MANAGEMENT_KUBERNETES_ARCHITECTURE}" ]] ||
    die "unexpected management node architecture: ${architecture}; expected ${MANAGEMENT_KUBERNETES_ARCHITECTURE}"
  server_version="$(kubectl --kubeconfig "${kubeconfig}" version -o json |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["serverVersion"]["gitVersion"])')"
  [[ "${server_version}" == "${KIND_KUBERNETES_VERSION}" ]] ||
    die "unexpected management API version: ${server_version}"

  run_probe openstack-api-probe \
    "http://${KOLLA_INTERNAL_VIP_ADDRESS}:5000/v3/"
  local workload_probe="not-run"
  if [[ -f "${GENERATED_DIR}/verification.env" ]]; then
    # shellcheck disable=SC1090
    source "${GENERATED_DIR}/verification.env"
    run_probe workload-api-probe \
      "http://${UBUNTU_TEST_FLOATING_IP}:${PROBE_API_PORT}/"
    workload_probe="pass:${UBUNTU_TEST_FLOATING_IP}:${PROBE_API_PORT}"
  fi

  local headroom available_kib disk_available_kib run_dir
  headroom="$(verify_resource_headroom)"
  read -r available_kib disk_available_kib <<<"${headroom}"
  run_dir="$(current_or_new_run)"
  {
    echo "management_runtime_host=${runtime_host}"
    echo "management_node_ready=pass"
    echo "architecture_${MANAGEMENT_KUBERNETES_ARCHITECTURE}=pass"
    echo "kubernetes_${KIND_KUBERNETES_VERSION}=pass"
    echo "isolated_bridge=${MANAGEMENT_DOCKER_BRIDGE}"
    echo "isolated_cidr=${MANAGEMENT_DOCKER_CIDR}"
    echo "iap_api_tunnel=pass"
    echo "openstack_api_from_kind_pod=pass"
    echo "workload_api_from_kind_pod=${workload_probe}"
    echo "controller_mem_available_kib=${available_kib}"
    echo "controller_disk_available_kib=${disk_available_kib}"
  } >"${run_dir}/management-cluster-verification.txt"
  chmod 600 "${run_dir}/management-cluster-verification.txt"

  kubectl --kubeconfig "${kubeconfig}" get nodes -o wide
  log "Controller-integrated kind management cluster and network gate passed"
  printf 'Kubeconfig: %s\n' "${kubeconfig}"
}

case "${action}" in
  tunnel)
    instance_running "${runtime_host}" ||
      die "management runtime host is stopped; run make gcp-start"
    cluster_exists ||
      die "kind cluster not found on ${runtime_host}: ${MANAGEMENT_CLUSTER_NAME}"
    [[ -f "${kubeconfig}" ]] || fetch_kubeconfig
    start_tunnel
    kubectl --kubeconfig "${kubeconfig}" get --raw=/readyz >/dev/null
    ;;
  create)
    "${PROJECT_ROOT}/scripts/gcp-iac.sh" controller-management
    ensure_kind_binary
    render_remote_inputs
    prepare_controller_runtime
    copy_to "${kind_binary}" "${runtime_host}" /tmp/kind-linux-amd64
    copy_to "${rendered_config}" "${runtime_host}" "${remote_config}"
    run_on "${runtime_host}" sudo install -m 0755 \
      /tmp/kind-linux-amd64 "${remote_kind}"
    run_on "${runtime_host}" rm -f /tmp/kind-linux-amd64
    if cluster_exists && {
      ! cluster_api_endpoint_matches ||
        ! cluster_tls_san_matches ||
        ! cluster_network_matches
    }; then
      log "Recreating controller kind cluster to reconcile API, TLS and network settings"
      run_kind delete cluster --name "${MANAGEMENT_CLUSTER_NAME}"
    fi
    if cluster_exists; then
      log "Controller kind management cluster already exists; verifying it"
    else
      run_kind create cluster \
        --name "${MANAGEMENT_CLUSTER_NAME}" \
        --image "${KIND_NODE_IMAGE}" \
        --config "${remote_config}" --wait 10m
    fi
    fetch_kubeconfig
    verify_cluster
    ;;
  verify)
    verify_cluster
    ;;
  destroy)
    [[ "${confirmation}" == "${ENV}" ]] ||
      die "refusing to delete management cluster without CONFIRM=${ENV}"
    stop_tunnel
    if cluster_exists; then
      run_kind delete cluster --name "${MANAGEMENT_CLUSTER_NAME}"
    else
      log "controller kind cluster is already absent: ${MANAGEMENT_CLUSTER_NAME}"
    fi
    if instance_running "${runtime_host}"; then
      run_on "${runtime_host}" sudo systemctl disable --now \
        openstack-k8s-kind-network.service >/dev/null
      run_on "${runtime_host}" sudo env \
        MANAGEMENT_DOCKER_NETWORK="${MANAGEMENT_DOCKER_NETWORK}" \
        MANAGEMENT_DOCKER_CIDR="${MANAGEMENT_DOCKER_CIDR}" \
        MANAGEMENT_DOCKER_BRIDGE="${MANAGEMENT_DOCKER_BRIDGE}" \
        "${remote_network_script}" stop
    fi
    rm -f "$(safe_realpath_within_project "${kubeconfig}")"
    log "Controller and all OpenStack resources were preserved"
    ;;
  *)
    die "usage: gcp-management-cluster.sh {tunnel|create|verify|destroy [${ENV}]}"
    ;;
esac
