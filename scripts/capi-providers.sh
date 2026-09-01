#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

action="${1:-}"
management_kubeconfig="${STATE_DIR}/kubeconfigs/management.yaml"
clusterctl_dir="${STATE_DIR}/bin"
clusterctl_bin="${clusterctl_dir}/clusterctl"
clusterctl_config="${PROJECT_ROOT}/config/clusterctl.yaml"
orc_manifest="${DOWNLOAD_DIR}/orc-${ORC_VERSION}-install.yaml"
orc_url="https://github.com/k-orc/openstack-resource-controller/releases/download/${ORC_VERSION}/install.yaml"
auth_probe_template="${PROJECT_ROOT}/kubernetes/capi/openstack-auth-probe.yaml.tpl"
auth_probe_manifest="${GENERATED_DIR}/openstack-auth-probe.yaml"
auth_probe_name="${WORKLOAD_CLUSTER_NAME}-openstack-auth-probe"

clusterctl_platform() {
  local os architecture
  case "$(uname -s)" in
    Darwin) os="darwin" ;;
    Linux) os="linux" ;;
    *) die "unsupported clusterctl operating system: $(uname -s)" ;;
  esac
  case "$(uname -m)" in
    arm64|aarch64) architecture="arm64" ;;
    x86_64|amd64) architecture="amd64" ;;
    *) die "unsupported clusterctl architecture: $(uname -m)" ;;
  esac
  printf '%s-%s\n' "${os}" "${architecture}"
}

clusterctl_checksum() {
  local platform="$1"
  local variable_name
  case "${platform}" in
    darwin-arm64) variable_name="CLUSTERCTL_DARWIN_ARM64_SHA256" ;;
    darwin-amd64) variable_name="CLUSTERCTL_DARWIN_AMD64_SHA256" ;;
    linux-amd64) variable_name="CLUSTERCTL_LINUX_AMD64_SHA256" ;;
    linux-arm64) variable_name="CLUSTERCTL_LINUX_ARM64_SHA256" ;;
    *) die "unsupported clusterctl platform: ${platform}" ;;
  esac
  local checksum="${!variable_name:-}"
  [[ "${checksum}" =~ ^[0-9a-f]{64}$ ]] ||
    die "missing pinned checksum ${variable_name} for clusterctl ${platform}"
  printf '%s\n' "${checksum}"
}

ensure_clusterctl() {
  local platform checksum url
  platform="$(clusterctl_platform)"
  checksum="$(clusterctl_checksum "${platform}")"
  url="https://github.com/kubernetes-sigs/cluster-api/releases/download/${CLUSTER_API_VERSION}/clusterctl-${platform}"
  mkdir_private "${clusterctl_dir}"
  if [[ -x "${clusterctl_bin}" ]] &&
    printf '%s  %s\n' "${checksum}" "${clusterctl_bin}" |
      shasum -a 256 -c - >/dev/null 2>&1; then
    return
  fi

  ensure_pinned_download \
    "${url}" "${clusterctl_bin}" "${checksum}" 0700
}

require_management_cluster() {
  require_command kubectl
  ensure_management_api_access
  [[ -f "${management_kubeconfig}" ]] ||
    die "management kubeconfig not found: ${management_kubeconfig}"
  kubectl --kubeconfig "${management_kubeconfig}" get nodes >/dev/null
}

wait_for_deployments() {
  local namespace="$1"
  kubectl --kubeconfig "${management_kubeconfig}" -n "${namespace}" wait \
    --for=condition=Available deployment --all --timeout=10m
}

verify_providers() {
  require_management_cluster
  ensure_clusterctl

  local namespaces=(
    cert-manager
    orc-system
    capi-system
    capi-kubeadm-bootstrap-system
    capi-kubeadm-control-plane-system
    capo-system
  )
  local namespace
  for namespace in "${namespaces[@]}"; do
    kubectl --kubeconfig "${management_kubeconfig}" get namespace "${namespace}" >/dev/null
    wait_for_deployments "${namespace}"
  done

  local provider_versions
  provider_versions="$(kubectl --kubeconfig "${management_kubeconfig}" \
    get providers.clusterctl.cluster.x-k8s.io -A \
    -o jsonpath='{range .items[*]}{.type}{"/"}{.providerName}{"="}{.version}{"\n"}{end}')"
  grep -Fxq "CoreProvider/cluster-api=${CLUSTER_API_VERSION}" <<<"${provider_versions}" ||
    die "CAPI core provider version is not ${CLUSTER_API_VERSION}"
  grep -Fxq "BootstrapProvider/kubeadm=${CLUSTER_API_VERSION}" <<<"${provider_versions}" ||
    die "kubeadm bootstrap provider version is not ${CLUSTER_API_VERSION}"
  grep -Fxq "ControlPlaneProvider/kubeadm=${CLUSTER_API_VERSION}" <<<"${provider_versions}" ||
    die "kubeadm control-plane provider version is not ${CLUSTER_API_VERSION}"
  grep -Fxq "InfrastructureProvider/openstack=${CAPO_VERSION}" <<<"${provider_versions}" ||
    die "CAPO provider version is not ${CAPO_VERSION}"

  local run_dir
  run_dir="$(current_or_new_run)"
  mkdir -p "${run_dir}/m2"
  chmod 700 "${run_dir}/m2"
  printf '%s\n' "${provider_versions}" >"${run_dir}/m2/providers.txt"
  chmod 600 "${run_dir}/m2/providers.txt"
  kubectl --kubeconfig "${management_kubeconfig}" \
    get providers.clusterctl.cluster.x-k8s.io -A
  log "CAPI ${CLUSTER_API_VERSION}, CAPO ${CAPO_VERSION}, and ORC ${ORC_VERSION} are available"
}

install_providers() {
  require_management_cluster
  ensure_state_dirs
  ensure_clusterctl
  ensure_pinned_download "${orc_url}" "${orc_manifest}" "${ORC_INSTALL_SHA256}"

  local run_dir
  run_dir="$(start_run)"
  mkdir -p "${run_dir}/m2"
  chmod 700 "${run_dir}/m2"

  log "Installing ORC ${ORC_VERSION}"
  kubectl --kubeconfig "${management_kubeconfig}" apply --server-side \
    -f "${orc_manifest}"
  wait_for_deployments orc-system

  log "Installing CAPI ${CLUSTER_API_VERSION} and CAPO ${CAPO_VERSION}"
  "${clusterctl_bin}" init \
    --config "${clusterctl_config}" \
    --kubeconfig "${management_kubeconfig}" \
    --core "cluster-api:${CLUSTER_API_VERSION}" \
    --bootstrap "kubeadm:${CLUSTER_API_VERSION}" \
    --control-plane "kubeadm:${CLUSTER_API_VERSION}" \
    --infrastructure "openstack:${CAPO_VERSION}"

  verify_providers
}

verify_application_credential() {
  require_management_cluster
  ensure_state_dirs
  [[ -f "${SECRET_DIR}/capi-clouds.yaml" ]] ||
    die "CAPO credential is missing: ${SECRET_DIR}/capi-clouds.yaml"
  [[ "$(stat -f '%Lp' "${SECRET_DIR}/capi-clouds.yaml")" == "600" ]] ||
    die "CAPO credential must have mode 0600"

  if ! kubectl --kubeconfig "${management_kubeconfig}" get namespace \
      "${WORKLOAD_NAMESPACE}" >/dev/null 2>&1; then
    kubectl --kubeconfig "${management_kubeconfig}" create namespace \
      "${WORKLOAD_NAMESPACE}"
  fi

  kubectl --kubeconfig "${management_kubeconfig}" create secret generic \
    "${WORKLOAD_CLUSTER_NAME}-cloud-config" \
    --namespace "${WORKLOAD_NAMESPACE}" \
    --from-file="clouds.yaml=${SECRET_DIR}/capi-clouds.yaml" \
    --dry-run=client -o yaml |
    kubectl --kubeconfig "${management_kubeconfig}" apply -f - >/dev/null

  if kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
      get pod "${auth_probe_name}" >/dev/null 2>&1; then
    die "existing authentication probe must be inspected before retry: ${auth_probe_name}"
  fi

  WORKLOAD_CLUSTER_NAME="${WORKLOAD_CLUSTER_NAME}" \
  WORKLOAD_NAMESPACE="${WORKLOAD_NAMESPACE}" \
    "${PROJECT_ROOT}/scripts/render-template.py" \
      "${auth_probe_template}" "${auth_probe_manifest}"

  kubectl --kubeconfig "${management_kubeconfig}" apply -f "${auth_probe_manifest}" >/dev/null
  if ! kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" wait \
      --for=jsonpath='{.status.phase}'=Succeeded "pod/${auth_probe_name}" --timeout=3m; then
    kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
      describe pod "${auth_probe_name}" || true
    kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
      logs "${auth_probe_name}" || true
    die "in-cluster OpenStack application credential probe failed; pod preserved"
  fi
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    logs "${auth_probe_name}"
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    delete pod "${auth_probe_name}" --wait=false >/dev/null
  log "OpenStack application credential passed from the management cluster"
}

case "${action}" in
  install) install_providers ;;
  verify) verify_providers ;;
  credentials) verify_application_credential ;;
  *) die "usage: $0 {install|verify|credentials}" ;;
esac
