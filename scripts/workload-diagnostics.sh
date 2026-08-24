#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

reason="${1:-manual}"
[[ "${reason}" =~ ^[a-z0-9-]+$ ]] || die "invalid diagnostic reason: ${reason}"

management_kubeconfig="${STATE_DIR}/kubeconfigs/management.yaml"
workload_kubeconfig="${STATE_DIR}/kubeconfigs/${WORKLOAD_CLUSTER_NAME}.yaml"
clusterctl_bin="${STATE_DIR}/bin/clusterctl"
clusterctl_config="${PROJECT_ROOT}/config/clusterctl.yaml"
run_dir="$(current_or_new_run)"
status_dir="${run_dir}/m2/failures/$(utc_timestamp)-${reason}"
mkdir -p "${status_dir}"
chmod 700 "${status_dir}"

redact_bootstrap_secrets() {
  sed -E \
    -e 's/[a-z0-9]{6}\.[a-z0-9]{16}/<redacted-bootstrap-token>/g' \
    -e 's/(--certificate-key[=[:space:]]+)[0-9a-f]{64}/\1<redacted-certificate-key>/g' \
    -e 's/(token:[[:space:]]*)[[:alnum:]_.-]+/\1<redacted-token>/g' \
    -e 's/(application_credential_secret:[[:space:]]*)[^[:space:]]+/\1<redacted-application-credential>/g'
}

capture_capi() {
  [[ -f "${management_kubeconfig}" ]] || return

  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" get \
    clusters,machinedeployments,machines,kubeadmcontrolplanes,openstackclusters,openstackmachines \
    -o wide >"${status_dir}/capi-resources.txt" 2>&1 || true
  kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" get events \
    --sort-by=.lastTimestamp >"${status_dir}/capi-events.txt" 2>&1 || true

  if [[ -x "${clusterctl_bin}" ]]; then
    "${clusterctl_bin}" describe cluster "${WORKLOAD_CLUSTER_NAME}" \
      --namespace "${WORKLOAD_NAMESPACE}" \
      --config "${clusterctl_config}" \
      --kubeconfig "${management_kubeconfig}" \
      >"${status_dir}/clusterctl-describe.txt" 2>&1 || true
  fi

  local machine safe_name
  while IFS= read -r machine; do
    [[ -n "${machine}" ]] || continue
    safe_name="${machine//[^a-zA-Z0-9_.-]/_}"
    {
      kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
        describe machine "${machine}"
      kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
        describe openstackmachine "${machine}"
      kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
        describe kubeadmconfig "${machine}"
    } 2>&1 | redact_bootstrap_secrets \
      >"${status_dir}/${safe_name}-capi-describe.txt" || true
  done < <(kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    get machines -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null)

  local namespace deployment label
  while IFS=$'\t' read -r namespace deployment label; do
    kubectl --kubeconfig "${management_kubeconfig}" -n "${namespace}" logs \
      "deployment/${deployment}" --all-containers=true --tail=1200 \
      >"${status_dir}/${label}-controller.log" 2>&1 || true
  done <<'CONTROLLERS'
capi-system	capi-controller-manager	capi
capi-kubeadm-bootstrap-system	capi-kubeadm-bootstrap-controller-manager	cabpk
capo-system	capo-controller-manager	capo
CONTROLLERS
}

capture_workload() {
  [[ -f "${workload_kubeconfig}" ]] || return

  kubectl --kubeconfig "${workload_kubeconfig}" get nodes -o wide \
    >"${status_dir}/workload-nodes.txt" 2>&1 || true
  kubectl --kubeconfig "${workload_kubeconfig}" get pods -A -o wide \
    >"${status_dir}/workload-pods.txt" 2>&1 || true
  kubectl --kubeconfig "${workload_kubeconfig}" get events -A \
    --sort-by=.lastTimestamp >"${status_dir}/workload-events.txt" 2>&1 || true
  kubectl --kubeconfig "${workload_kubeconfig}" -n kube-system describe daemonset calico-node \
    >"${status_dir}/calico-daemonset.txt" 2>&1 || true

  local pod safe_name
  while IFS= read -r pod; do
    [[ -n "${pod}" ]] || continue
    safe_name="${pod//[^a-zA-Z0-9_.-]/_}"
    kubectl --kubeconfig "${workload_kubeconfig}" -n kube-system describe pod "${pod}" \
      >"${status_dir}/${safe_name}-describe.txt" 2>&1 || true
    kubectl --kubeconfig "${workload_kubeconfig}" -n kube-system logs "${pod}" \
      -c calico-node --tail=500 >"${status_dir}/${safe_name}-calico-node.log" 2>&1 || true
  done < <(kubectl --kubeconfig "${workload_kubeconfig}" -n kube-system get pods \
    -l k8s-app=calico-node -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' \
    2>/dev/null)
}

capture_openstack() {
  local server_rows server_id server_name safe_name
  server_rows="$(run_on "${CONTROLLER_NAME}" \
    env WORKLOAD_CLUSTER_NAME="${WORKLOAD_CLUSTER_NAME}" bash -lc '
      set -Eeuo pipefail
      source /opt/kolla-venv/bin/activate
      export OS_CLIENT_CONFIG_FILE=/etc/kolla/capi-clouds.yaml
      openstack --os-cloud capi server list --name "${WORKLOAD_CLUSTER_NAME}" \
        -f value -c ID -c Name
    ' 2>"${status_dir}/openstack-server-list.stderr" || true)"
  printf '%s\n' "${server_rows}" >"${status_dir}/openstack-servers.txt"

  while IFS=$'\t ' read -r server_id server_name; do
    [[ -n "${server_id}" && -n "${server_name}" ]] || continue
    safe_name="${server_name//[^a-zA-Z0-9_.-]/_}"
    run_on "${CONTROLLER_NAME}" env SERVER_ID="${server_id}" bash -lc '
      set -Eeuo pipefail
      source /opt/kolla-venv/bin/activate
      export OS_CLIENT_CONFIG_FILE=/etc/kolla/capi-clouds.yaml
      openstack --os-cloud capi server show "${SERVER_ID}" -f yaml \
        -c id -c name -c status -c created -c updated -c addresses -c flavor \
        -c image -c OS-EXT-SRV-ATTR:host -c OS-EXT-SRV-ATTR:instance_name \
        -c OS-EXT-STS:power_state -c OS-EXT-STS:task_state \
        -c OS-EXT-STS:vm_state -c fault
    ' </dev/null >"${status_dir}/${safe_name}-nova-show.txt" 2>&1 || true
    run_on "${CONTROLLER_NAME}" env SERVER_ID="${server_id}" bash -lc '
      set -Eeuo pipefail
      source /opt/kolla-venv/bin/activate
      export OS_CLIENT_CONFIG_FILE=/etc/kolla/capi-clouds.yaml
      openstack --os-cloud capi console log show --lines 1200 "${SERVER_ID}"
    ' </dev/null | redact_bootstrap_secrets \
      >"${status_dir}/${safe_name}-console.log" 2>&1 || true
  done <<<"${server_rows}"

  run_on "${CONTROLLER_NAME}" bash -lc '
    set -Eeuo pipefail
    source /opt/kolla-venv/bin/activate
    export OS_CLIENT_CONFIG_FILE=/etc/kolla/clouds.yaml
    openstack --os-cloud kolla-admin compute service list
    openstack --os-cloud kolla-admin hypervisor list --long
  ' >"${status_dir}/openstack-compute.txt" 2>&1 || true
}

capture_host_health() {
  local compute_name
  run_on "${CONTROLLER_NAME}" sh -lc '
    date -u
    timedatectl show -p NTPSynchronized --value
    free -h
    swapon --show
    uptime
  ' >"${status_dir}/controller-health.txt" 2>&1 || true

  for compute_name in "${COMPUTE_NAMES[@]}"; do
    run_on "${compute_name}" bash -lc '
      date -u
      timedatectl show -p NTPSynchronized --value
      free -h
      swapon --show
      uptime
      echo "memory pressure"
      cat /proc/pressure/memory
      echo "cpu pressure"
      cat /proc/pressure/cpu
      echo "largest processes"
      ps -eo pid,rss,pcpu,comm --sort=-rss | head -20
      echo "kernel OOM records"
      sudo journalctl -k -b --no-pager |
        grep -Ei "out of memory|oom-kill|killed process" | tail -100 || true
      echo "container memory"
      sudo docker stats --no-stream --format \
        "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" || true
      echo "libvirt domains"
      sudo docker exec nova_libvirt virsh list --all || true
      sudo docker exec nova_libvirt virsh domstats --balloon --vcpu --state || true
      echo "nova-compute tail"
      sudo tail -n 500 /var/log/kolla/nova/nova-compute.log || true
    ' >"${status_dir}/${compute_name}-health.txt" 2>&1 || true
  done
}

capture_guest_bootstrap() {
  [[ -f "${management_kubeconfig}" ]] || return

  local machine_address machine_name safe_name kubernetes_service_ip
  kubernetes_service_ip="$(python3 -c '
import ipaddress, sys
print(next(ipaddress.ip_network(sys.argv[1]).hosts()))
' "${WORKLOAD_SERVICE_CIDR}")"
  while IFS=$'\t' read -r machine_name machine_address; do
    [[ -n "${machine_name}" && -n "${machine_address}" ]] || continue
    safe_name="${machine_name//[^a-zA-Z0-9_.-]/_}"
    run_on "${CONTROLLER_NAME}" env \
      MACHINE_NAME="${machine_name}" \
      MACHINE_ADDRESS="${machine_address}" \
      WORKLOAD_NETWORK_CIDR="${WORKLOAD_NETWORK_CIDR}" \
      KUBERNETES_SERVICE_IP="${kubernetes_service_ip}" \
      TARGET_SSH_USER="${TARGET_SSH_USER}" \
      bash -s 2>&1 <<'CONTROLLER_BOOTSTRAP' | redact_bootstrap_secrets \
        >"${status_dir}/${safe_name}-bootstrap.log" 2>&1 || true
set -Eeuo pipefail
router_namespace=""
while read -r namespace _; do
  [[ -n "${namespace}" ]] || continue
  if sudo ip netns exec "${namespace}" ip -4 route show "${WORKLOAD_NETWORK_CIDR}" |
      grep -q .; then
    router_namespace="${namespace}"
    break
  fi
done < <(sudo ip netns list)

if [[ -z "${router_namespace}" ]]; then
  echo "bootstrap SSH unavailable: router namespace for ${WORKLOAD_NETWORK_CIDR} not found"
  exit 1
fi

deployment_key="/home/${TARGET_SSH_USER}/.ssh/openstack_k8s"
if [[ ! -s "${deployment_key}" ]]; then
  echo "bootstrap SSH unavailable: project deployment key is missing"
  exit 1
fi

echo "machine=${MACHINE_NAME} address=${MACHINE_ADDRESS} router_namespace=${router_namespace}"
sudo ip netns exec "${router_namespace}" ssh \
  -i "${deployment_key}" \
  -o BatchMode=yes \
  -o ConnectTimeout=10 \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  "ubuntu@${MACHINE_ADDRESS}" env \
  KUBERNETES_SERVICE_IP="${KUBERNETES_SERVICE_IP}" bash -s <<'GUEST_BOOTSTRAP'
set +e
echo "identity and capacity"
hostname
date -u
uptime
free -h
swapon --show
df -h /
echo "cloud-init status"
sudo cloud-init status --long
echo "service state"
sudo systemctl --no-pager --full status cloud-final.service kubelet.service containerd.service
echo "cloud-init output"
sudo tail -n 1200 /var/log/cloud-init-output.log
echo "bootstrap service journals"
sudo journalctl -b --no-pager -n 1600 \
  -u cloud-final.service -u kubelet.service -u containerd.service
echo "containerd RunPodSandbox and cancellation records"
sudo journalctl -b --no-pager -u containerd.service | \
  grep -Ei "RunPodSandbox|sandbox.*(cancel|canceled|deadline|error)" | tail -500 || true
echo "kubelet sandbox and CNI retry records"
sudo journalctl -b --no-pager -u kubelet.service | \
  grep -Ei "sandbox|cni|network plugin|CreatePodSandbox" | tail -500 || true
echo "calico-ipam processes"
ps -eo pid,ppid,etimes,stat,wchan:32,comm,args | grep '[c]alico-ipam' || true
echo "Kubernetes API service path"
ip route get "${KUBERNETES_SERVICE_IP}" || true
ip neigh show || true
echo "worker pressure"
cat /proc/pressure/cpu
cat /proc/pressure/memory
cat /proc/loadavg
echo "CRI containers"
sudo crictl --runtime-endpoint unix:///run/containerd/containerd.sock ps -a
GUEST_BOOTSTRAP
CONTROLLER_BOOTSTRAP
  done < <(kubectl --kubeconfig "${management_kubeconfig}" -n "${WORKLOAD_NAMESPACE}" \
    get machines -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.addresses[?(@.type=="InternalIP")]}{.address}{end}{"\n"}{end}' \
    2>/dev/null)
}

capture_capi
capture_workload
capture_openstack
capture_host_health
capture_guest_bootstrap

# Apply the same bounded redaction to every text artifact as a final guard in
# case an upstream describe/log format starts repeating bootstrap credentials.
while IFS= read -r diagnostic_file; do
  redacted_file="${diagnostic_file}.redacted"
  redact_bootstrap_secrets <"${diagnostic_file}" >"${redacted_file}"
  chmod 600 "${redacted_file}"
  mv "${redacted_file}" "${diagnostic_file}"
done < <(find "${status_dir}" -maxdepth 1 -type f -print)
chmod -R go-rwx "${status_dir}"
warn "workload diagnostics preserved at ${status_dir}"
