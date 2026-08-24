#!/usr/bin/env bash

set -Eeuo pipefail

if [[ -z "${PROJECT_ROOT:-}" ]]; then
  PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

ENV="${ENV:-local-arm64}"
CONFIG="${CONFIG:-${PROJECT_ROOT}/config/environments/${ENV}.env}"

if [[ ! -f "${CONFIG}" ]]; then
  echo "ERROR: environment config not found: ${CONFIG}" >&2
  exit 2
fi

# shellcheck disable=SC1090
source "${CONFIG}"

HOST_PROVIDER="${HOST_PROVIDER:-lima}"
MANAGEMENT_INTERFACE="${MANAGEMENT_INTERFACE:-${LIMA_MANAGEMENT_INTERFACE:-}}"

STATE_DIR="${PROJECT_ROOT}/.state/${ENV}"
SECRET_DIR="${STATE_DIR}/secrets"
GENERATED_DIR="${STATE_DIR}/generated"
DOWNLOAD_DIR="${STATE_DIR}/downloads"
ARTIFACT_ROOT="${PROJECT_ROOT}/artifacts"
CURRENT_RUN_FILE="${STATE_DIR}/current-run"

mkdir_private() {
  local path="$1"
  mkdir -p "${path}"
  chmod 700 "${path}"
}

ensure_state_dirs() {
  umask 077
  mkdir_private "${STATE_DIR}"
  mkdir_private "${SECRET_DIR}"
  mkdir_private "${GENERATED_DIR}"
  mkdir_private "${DOWNLOAD_DIR}"
  mkdir -p "${ARTIFACT_ROOT}"
}

utc_timestamp() {
  date -u +"%Y%m%dT%H%M%SZ"
}

start_run() {
  ensure_state_dirs
  local run_id
  run_id="${ENV}-$(utc_timestamp)-$$"
  local run_dir="${ARTIFACT_ROOT}/${run_id}"
  mkdir -p "${run_dir}/logs"
  chmod 700 "${run_dir}"
  printf '%s\n' "${run_dir}" > "${CURRENT_RUN_FILE}"
  chmod 600 "${CURRENT_RUN_FILE}"
  printf '%s\n' "${run_dir}"
}

current_or_new_run() {
  ensure_state_dirs
  if [[ -f "${CURRENT_RUN_FILE}" ]]; then
    local existing
    existing="$(<"${CURRENT_RUN_FILE}")"
    if [[ -d "${existing}" ]]; then
      printf '%s\n' "${existing}"
      return
    fi
  fi
  start_run
}

log() {
  printf '[%s] %s\n' "$(date +"%H:%M:%S")" "$*"
}

warn() {
  printf 'WARN: %s\n' "$*" >&2
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  local cmd="$1"
  command -v "${cmd}" >/dev/null 2>&1 || die "required command not found: ${cmd}"
}

ensure_management_api_access() {
  if [[ "${HOST_PROVIDER}" == "gcp" ]]; then
    "${PROJECT_ROOT}/scripts/gcp-management-cluster.sh" tunnel
  fi
}

run_host_as_root() {
  if sudo -n true >/dev/null 2>&1; then
    sudo "$@"
    return
  fi
  if [[ -t 0 ]]; then
    sudo "$@"
    return
  fi

  local command_text=""
  local argument
  local quoted
  for argument in "$@"; do
    printf -v quoted '%q' "${argument}"
    command_text+="${command_text:+ }${quoted}"
  done
  osascript "${PROJECT_ROOT}/scripts/run-as-administrator.applescript" \
    "${command_text}"
}

instance_exists() {
  local name="$1"
  if [[ "${HOST_PROVIDER}" == "gcp" ]]; then
    gcloud compute instances describe "${name}" \
      --project="${GCP_PROJECT_ID}" \
      --zone="${GCP_ZONE}" \
      --format='value(name)' >/dev/null 2>&1
    return
  fi

  limactl list --json 2>/dev/null | python3 -c '
import json, sys
target = sys.argv[1]
found = False
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    item = json.loads(line)
    if item.get("name") == target:
        found = True
raise SystemExit(0 if found else 1)
' "${name}"
}

lima_network_exists() {
  local name="$1"
  limactl network list --json 2>/dev/null | python3 -c '
import json, sys
target = sys.argv[1]
found = False
for line in sys.stdin:
    line = line.strip()
    if line and json.loads(line).get("name") == target:
        found = True
raise SystemExit(0 if found else 1)
' "${name}"
}

instance_status() {
  local name="$1"
  if [[ "${HOST_PROVIDER}" == "gcp" ]]; then
    local status
    status="$(gcloud compute instances describe "${name}" \
      --project="${GCP_PROJECT_ID}" \
      --zone="${GCP_ZONE}" \
      --format='value(status)' 2>/dev/null)" || return 1
    case "${status}" in
      RUNNING) printf '%s\n' "Running" ;;
      TERMINATED) printf '%s\n' "Stopped" ;;
      *) printf '%s\n' "${status}" ;;
    esac
    return
  fi

  limactl list --json 2>/dev/null | python3 -c '
import json, sys
target = sys.argv[1]
status = None
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    item = json.loads(line)
    if item.get("name") == target:
        status = item.get("status", "Unknown")
if status is None:
    raise SystemExit(1)
print(status)
' "${name}"
}

instance_running() {
  [[ "$(instance_status "$1" 2>/dev/null || true)" == "Running" ]]
}

guest_ipv4() {
  local name="$1"
  if [[ "${HOST_PROVIDER}" == "gcp" ]]; then
    gcloud compute instances describe "${name}" \
      --project="${GCP_PROJECT_ID}" \
      --zone="${GCP_ZONE}" \
      --format='value(networkInterfaces[0].networkIP)'
    return
  fi

  limactl shell "${name}" -- bash -lc \
    "ip -4 -o addr show dev '${LIMA_MANAGEMENT_INTERFACE}' | awk '{print \$4}' | cut -d/ -f1 | head -n1"
}

controller_ipv4() {
  if [[ -n "${CONTROLLER_MANAGEMENT_IP:-}" ]]; then
    printf '%s\n' "${CONTROLLER_MANAGEMENT_IP}"
    return
  fi
  guest_ipv4 "${CONTROLLER_NAME}"
}

compute_ipv4() {
  if [[ "${#COMPUTE_MANAGEMENT_IPS[@]}" -gt 0 ]]; then
    printf '%s\n' "${COMPUTE_MANAGEMENT_IPS[0]}"
    return
  fi
  guest_ipv4 "${COMPUTE_NAMES[0]}"
}

compute_instance_names() {
  printf '%s\n' "${COMPUTE_NAMES[@]}"
}

compute_ipv4s() {
  local index
  if [[ "${#COMPUTE_MANAGEMENT_IPS[@]}" -gt 0 ]]; then
    printf '%s\n' "${COMPUTE_MANAGEMENT_IPS[@]}"
    return
  fi
  for ((index = 0; index < ${#COMPUTE_NAMES[@]}; index++)); do
    guest_ipv4 "${COMPUTE_NAMES[index]}"
  done
}

all_instance_names() {
  printf '%s\n' "${CONTROLLER_NAME}"
  compute_instance_names
}

gcp_ssh_options() {
  printf '%s\n' "--project=${GCP_PROJECT_ID}" "--zone=${GCP_ZONE}" "--quiet"
  if [[ "${GCP_USE_IAP_TUNNEL:-no}" == "yes" ]]; then
    printf '%s\n' "--tunnel-through-iap"
  fi
}

run_on() {
  local name="$1"
  shift
  if [[ "${HOST_PROVIDER}" == "gcp" ]]; then
    local command_text=""
    local argument
    local quoted
    local options=()
    while IFS= read -r argument; do
      options+=("${argument}")
    done < <(gcp_ssh_options)
    for argument in "$@"; do
      printf -v quoted '%q' "${argument}"
      command_text+="${command_text:+ }${quoted}"
    done
    gcloud compute ssh "${TARGET_SSH_USER}@${name}" \
      "${options[@]}" --command="${command_text}"
    return
  fi
  limactl shell "${name}" -- "$@"
}

copy_to() {
  local source="$1"
  local name="$2"
  local destination="$3"
  if [[ "${HOST_PROVIDER}" == "gcp" ]]; then
    local options=()
    local option
    while IFS= read -r option; do
      options+=("${option}")
    done < <(gcp_ssh_options)
    gcloud compute scp "${options[@]}" "${source}" \
      "${TARGET_SSH_USER}@${name}:${destination}"
    return
  fi
  limactl copy "${source}" "${name}:${destination}"
}

copy_from() {
  local name="$1"
  local source="$2"
  local destination="$3"
  if [[ "${HOST_PROVIDER}" == "gcp" ]]; then
    local options=()
    local option
    while IFS= read -r option; do
      options+=("${option}")
    done < <(gcp_ssh_options)
    gcloud compute scp "${options[@]}" \
      "${TARGET_SSH_USER}@${name}:${source}" "${destination}"
    return
  fi
  limactl copy "${name}:${source}" "${destination}"
}

safe_realpath_within_project() {
  local target="$1"
  local resolved
  resolved="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${target}")"
  case "${resolved}" in
    "${PROJECT_ROOT}"/*) printf '%s\n' "${resolved}" ;;
    *) die "refusing path outside project: ${resolved}" ;;
  esac
}
