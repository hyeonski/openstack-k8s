#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

action="${1:-}"
kind_dir="${STATE_DIR}/bin"
kind_bin="${kind_dir}/kind"
kubeconfig_dir="${STATE_DIR}/kubeconfigs"
kubeconfig="${kubeconfig_dir}/management.yaml"
kind_url="https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/kind-darwin-arm64"

ensure_kind() {
  require_command curl
  require_command shasum
  mkdir_private "${kind_dir}"

  if [[ -x "${kind_bin}" ]] && \
    printf '%s  %s\n' "${KIND_DARWIN_ARM64_SHA256}" "${kind_bin}" | shasum -a 256 -c - >/dev/null 2>&1; then
    return
  fi

  local temporary="${kind_bin}.download"
  rm -f "${temporary}"
  log "Downloading kind ${KIND_VERSION} for Darwin ARM64"
  curl -fL --retry 3 --output "${temporary}" "${kind_url}"
  printf '%s  %s\n' "${KIND_DARWIN_ARM64_SHA256}" "${temporary}" | shasum -a 256 -c -
  chmod 700 "${temporary}"
  mv "${temporary}" "${kind_bin}"
}

cluster_exists() {
  "${kind_bin}" get clusters 2>/dev/null | grep -Fxq "${MANAGEMENT_CLUSTER_NAME}"
}

verify_cluster() {
  require_command kubectl
  require_command python3
  [[ -f "${kubeconfig}" ]] || die "management kubeconfig not found: ${kubeconfig}"
  cluster_exists || die "kind cluster not found: ${MANAGEMENT_CLUSTER_NAME}"

  kubectl --kubeconfig "${kubeconfig}" wait \
    --for=condition=Ready nodes --all --timeout=180s
  kubectl --kubeconfig "${kubeconfig}" wait \
    --for=condition=Ready pods --all --namespace kube-system --timeout=180s

  local architecture
  architecture="$(kubectl --kubeconfig "${kubeconfig}" get nodes \
    -o jsonpath='{.items[0].status.nodeInfo.architecture}')"
  [[ "${architecture}" == "arm64" ]] || die "unexpected kind node architecture: ${architecture}"

  local version_json server_version node_count node_name kubelet_version
  version_json="$(kubectl --kubeconfig "${kubeconfig}" version -o json)"
  server_version="$(python3 -c '
import json, sys
print(json.load(sys.stdin)["serverVersion"]["gitVersion"])
' <<<"${version_json}")"
  [[ "${server_version}" == "${KIND_KUBERNETES_VERSION}" ]] ||
    die "unexpected kind API server version: ${server_version}; expected ${KIND_KUBERNETES_VERSION}"

  node_count=0
  while IFS=$'\t' read -r node_name kubelet_version; do
    [[ -n "${node_name}" ]] || continue
    node_count=$((node_count + 1))
    [[ "${kubelet_version}" == "${KIND_KUBERNETES_VERSION}" ]] ||
      die "unexpected kubelet version on ${node_name}: ${kubelet_version}; expected ${KIND_KUBERNETES_VERSION}"
  done < <(kubectl --kubeconfig "${kubeconfig}" get nodes \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.nodeInfo.kubeletVersion}{"\n"}{end}')
  (( node_count > 0 )) || die "management cluster has no nodes"

  local probe="openstack-api-probe"
  cleanup_probe() {
    kubectl --kubeconfig "${kubeconfig}" delete pod "${probe}" \
      --ignore-not-found --wait=false >/dev/null 2>&1 || true
  }
  trap cleanup_probe EXIT
  cleanup_probe

  kubectl --kubeconfig "${kubeconfig}" run "${probe}" \
    --image=busybox:1.37.0 --restart=Never --command -- \
    sh -c "wget -qO- -T 15 http://${KOLLA_INTERNAL_VIP_ADDRESS}:5000/v3/ >/dev/null"
  kubectl --kubeconfig "${kubeconfig}" wait \
    --for=jsonpath='{.status.phase}'=Succeeded "pod/${probe}" --timeout=180s
  cleanup_probe
  trap - EXIT

  kubectl --kubeconfig "${kubeconfig}" get nodes -o wide
  printf 'API server and kubelet version: %s\n' "${KIND_KUBERNETES_VERSION}"
  log "kind management cluster and in-cluster OpenStack API path passed"
  printf 'Kubeconfig: %s\n' "${kubeconfig}"
}

case "${action}" in
  create)
    ensure_kind
    require_command docker
    docker info >/dev/null 2>&1 || die "Docker daemon is not ready"
    if cluster_exists; then
      die "kind cluster already exists: ${MANAGEMENT_CLUSTER_NAME}"
    fi
    mkdir_private "${kubeconfig_dir}"
    log "Creating single-node kind management cluster ${MANAGEMENT_CLUSTER_NAME}"
    "${kind_bin}" create cluster \
      --name "${MANAGEMENT_CLUSTER_NAME}" \
      --image "${KIND_NODE_IMAGE}" \
      --kubeconfig "${kubeconfig}" \
      --wait 5m
    chmod 600 "${kubeconfig}"
    verify_cluster
    ;;
  verify)
    ensure_kind
    verify_cluster
    ;;
  destroy)
    [[ "${2:-}" == "${ENV}" ]] || \
      die "refusing to delete management cluster without CONFIRM=${ENV}"
    ensure_kind
    if cluster_exists; then
      "${kind_bin}" delete cluster --name "${MANAGEMENT_CLUSTER_NAME}"
    else
      log "kind cluster is already absent: ${MANAGEMENT_CLUSTER_NAME}"
    fi
    rm -f "$(safe_realpath_within_project "${kubeconfig}")"
    ;;
  *)
    die "usage: $0 {create|verify|destroy [${ENV}]}"
    ;;
esac
