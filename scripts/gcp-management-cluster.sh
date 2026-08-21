#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

[[ "${HOST_PROVIDER}" == "gcp" ]] || die "GCP management cluster requires a GCP profile"
require_command gcloud
require_command kubectl
require_command curl
require_command nc
require_command shasum
require_command python3

action="${1:-}"
confirmation="${2:-}"
kind_dir="${STATE_DIR}/bin"
kind_binary="${kind_dir}/kind-linux-amd64"
kubeconfig_dir="${STATE_DIR}/kubeconfigs"
kubeconfig="${kubeconfig_dir}/management.yaml"
tunnel_pid_file="${STATE_DIR}/management-iap-tunnel.pid"
tunnel_log="${STATE_DIR}/management-iap-tunnel.log"
remote_kind="/usr/local/bin/kind"
remote_config="/tmp/openstack-k8s-kind-management.yaml"
rendered_config="${STATE_DIR}/kind-management-gcp.yaml"
kind_url="https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/kind-linux-amd64"

ensure_kind_binary() {
  mkdir_private "${kind_dir}"
  if [[ -x "${kind_binary}" ]] &&
      printf '%s  %s\n' "${KIND_LINUX_AMD64_SHA256}" "${kind_binary}" |
        shasum -a 256 -c - >/dev/null 2>&1; then
    return
  fi

  temporary="${kind_binary}.download"
  rm -f "${temporary}"
  log "Downloading kind ${KIND_VERSION} for Linux AMD64"
  curl -fL --retry 3 --output "${temporary}" "${kind_url}"
  printf '%s  %s\n' "${KIND_LINUX_AMD64_SHA256}" "${temporary}" |
    shasum -a 256 -c -
  chmod 700 "${temporary}"
  mv "${temporary}" "${kind_binary}"
}

cluster_exists() {
  instance_running "${MANAGEMENT_HOST_NAME}" &&
    run_on "${MANAGEMENT_HOST_NAME}" "${remote_kind}" get clusters 2>/dev/null |
      grep -Fxq "${MANAGEMENT_CLUSTER_NAME}"
}

cluster_api_endpoint_matches() {
  run_on "${MANAGEMENT_HOST_NAME}" docker port \
    "${MANAGEMENT_CLUSTER_NAME}-control-plane" \
    "${MANAGEMENT_REMOTE_API_PORT}/tcp" 2>/dev/null |
    grep -Fxq "${MANAGEMENT_HOST_IP}:${MANAGEMENT_REMOTE_API_PORT}"
}

cluster_tls_san_matches() {
  run_on "${MANAGEMENT_HOST_NAME}" docker exec \
    "${MANAGEMENT_CLUSTER_NAME}-control-plane" openssl x509 \
    -in /etc/kubernetes/pki/apiserver.crt -noout -ext subjectAltName \
    2>/dev/null | grep -Fq "IP Address:127.0.0.1"
}

render_kind_config() {
  ensure_state_dirs
  sed "s/__MANAGEMENT_HOST_IP__/${MANAGEMENT_HOST_IP}/g" \
    "${PROJECT_ROOT}/kubernetes/kind-management-gcp.yaml" >"${rendered_config}"
  chmod 600 "${rendered_config}"
}

tunnel_running() {
  [[ -f "${tunnel_pid_file}" ]] || return 1
  pid="$(<"${tunnel_pid_file}")"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  kill -0 "${pid}" 2>/dev/null || return 1
  ps -p "${pid}" -o command= 2>/dev/null |
    grep -Fq "start-iap-tunnel ${MANAGEMENT_HOST_NAME} ${MANAGEMENT_REMOTE_API_PORT}"
}

stop_tunnel() {
  if tunnel_running; then
    pid="$(<"${tunnel_pid_file}")"
    kill "${pid}" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 "${pid}" 2>/dev/null || break
      sleep 0.25
    done
  fi
  rm -f "${tunnel_pid_file}"
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
    "${MANAGEMENT_HOST_NAME}" "${MANAGEMENT_REMOTE_API_PORT}" \
    --local-host-port="127.0.0.1:${MANAGEMENT_LOCAL_API_PORT}" \
    --project="${GCP_PROJECT_ID}" --zone="${GCP_ZONE}" \
    --verbosity=warning >"${tunnel_log}" 2>&1 </dev/null &
  tunnel_pid="$!"
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
  run_on "${MANAGEMENT_HOST_NAME}" "${remote_kind}" get kubeconfig \
    --name "${MANAGEMENT_CLUSTER_NAME}" >"${kubeconfig}.tmp"
  chmod 600 "${kubeconfig}.tmp"
  KUBECONFIG="${kubeconfig}.tmp" kubectl config set-cluster \
    "kind-${MANAGEMENT_CLUSTER_NAME}" \
    --server="https://127.0.0.1:${MANAGEMENT_LOCAL_API_PORT}" >/dev/null
  mv "${kubeconfig}.tmp" "${kubeconfig}"
}

run_probe() {
  probe_name="$1"
  probe_url="$2"
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

verify_cluster() {
  instance_running "${MANAGEMENT_HOST_NAME}" ||
    die "management host is stopped; run make gcp-start ENV=${ENV}"
  cluster_exists || die "kind cluster not found: ${MANAGEMENT_CLUSTER_NAME}"
  [[ -f "${kubeconfig}" ]] || fetch_kubeconfig
  start_tunnel

  kubectl --kubeconfig "${kubeconfig}" get --raw=/readyz >/dev/null
  kubectl --kubeconfig "${kubeconfig}" wait \
    --for=condition=Ready nodes --all --timeout=180s
  kubectl --kubeconfig "${kubeconfig}" wait \
    --for=condition=Ready pods --all --namespace kube-system --timeout=180s

  architecture="$(kubectl --kubeconfig "${kubeconfig}" get nodes \
    -o jsonpath='{.items[0].status.nodeInfo.architecture}')"
  [[ "${architecture}" == "amd64" ]] ||
    die "unexpected management node architecture: ${architecture}"
  server_version="$(kubectl --kubeconfig "${kubeconfig}" version -o json |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["serverVersion"]["gitVersion"])')"
  [[ "${server_version}" == "${KIND_KUBERNETES_VERSION}" ]] ||
    die "unexpected management API version: ${server_version}"

  run_probe openstack-api-probe \
    "http://${KOLLA_INTERNAL_VIP_ADDRESS}:5000/v3/"
  workload_probe="not-run"
  if [[ -f "${GENERATED_DIR}/verification.env" ]]; then
    # shellcheck disable=SC1090
    source "${GENERATED_DIR}/verification.env"
    run_probe workload-api-probe \
      "http://${UBUNTU_TEST_FLOATING_IP}:${PROBE_API_PORT}/"
    workload_probe="pass:${UBUNTU_TEST_FLOATING_IP}:${PROBE_API_PORT}"
  fi

  run_dir="$(current_or_new_run)"
  {
    echo "management_node_ready=pass"
    echo "architecture_amd64=pass"
    echo "kubernetes_${KIND_KUBERNETES_VERSION}=pass"
    echo "iap_api_tunnel=pass"
    echo "openstack_api_from_kind_pod=pass"
    echo "workload_api_from_kind_pod=${workload_probe}"
  } >"${run_dir}/management-cluster-verification.txt"
  chmod 600 "${run_dir}/management-cluster-verification.txt"

  kubectl --kubeconfig "${kubeconfig}" get nodes -o wide
  log "GCP kind management cluster and in-cluster network gate passed"
  printf 'Kubeconfig: %s\n' "${kubeconfig}"
}

case "${action}" in
  create)
    "${PROJECT_ROOT}/scripts/gcp-management-host.sh" create
    ensure_kind_binary
    render_kind_config
    copy_to "${kind_binary}" "${MANAGEMENT_HOST_NAME}" "/tmp/kind-linux-amd64"
    copy_to "${rendered_config}" \
      "${MANAGEMENT_HOST_NAME}" "${remote_config}"
    run_on "${MANAGEMENT_HOST_NAME}" sudo install -m 0755 \
      /tmp/kind-linux-amd64 "${remote_kind}"
    run_on "${MANAGEMENT_HOST_NAME}" rm -f /tmp/kind-linux-amd64
    if cluster_exists && \
        { ! cluster_api_endpoint_matches || ! cluster_tls_san_matches; }; then
      log "Recreating kind cluster to reconcile its private API endpoint and TLS SAN"
      run_on "${MANAGEMENT_HOST_NAME}" "${remote_kind}" delete cluster \
        --name "${MANAGEMENT_CLUSTER_NAME}"
    fi
    if cluster_exists; then
      log "kind management cluster already exists; verifying it"
    else
      run_on "${MANAGEMENT_HOST_NAME}" "${remote_kind}" create cluster \
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
    if ! instance_running "${MANAGEMENT_HOST_NAME}"; then
      gcloud compute instances start "${MANAGEMENT_HOST_NAME}" \
        --project="${GCP_PROJECT_ID}" --zone="${GCP_ZONE}" --quiet
      for _ in {1..60}; do
        run_on "${MANAGEMENT_HOST_NAME}" true >/dev/null 2>&1 && break
        sleep 5
      done
    fi
    if cluster_exists; then
      run_on "${MANAGEMENT_HOST_NAME}" "${remote_kind}" delete cluster \
        --name "${MANAGEMENT_CLUSTER_NAME}"
    else
      log "kind cluster is already absent: ${MANAGEMENT_CLUSTER_NAME}"
    fi
    rm -f "$(safe_realpath_within_project "${kubeconfig}")"
    log "Management host and all OpenStack resources were preserved"
    ;;
  *)
    die "usage: gcp-management-cluster.sh {create|verify|destroy [${ENV}]}"
    ;;
esac
