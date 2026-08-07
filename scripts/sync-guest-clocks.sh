#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

is_epoch() {
  [[ "${1:-}" =~ ^[0-9]+$ ]]
}

absolute_delta() {
  local left="$1"
  local right="$2"
  local delta=$((left - right))
  (( delta < 0 )) && delta=$((-delta))
  printf '%s\n' "${delta}"
}

within_window() {
  local value="$1"
  local lower="$2"
  local upper="$3"
  (( value >= lower && value <= upper ))
}

self_test() {
  is_epoch 1704067200
  ! is_epoch ""
  ! is_epoch invalid
  [[ "$(absolute_delta 10 4)" == "6" ]]
  [[ "$(absolute_delta 4 10)" == "6" ]]
  within_window 100 95 105
  within_window 95 95 105
  within_window 105 95 105
  ! within_window 94 95 105
  ! within_window 106 95 105
  echo "Guest clock helper logic passed."
}

mode="${1:-sync}"
if [[ "${mode}" == "--self-test" ]]; then
  self_test
  exit 0
fi
[[ "${mode}" == "sync" || "${mode}" == "--check-only" ]] ||
  die "usage: $0 [sync|--check-only|--self-test]"

require_command limactl
is_epoch "${MAX_CLOCK_SKEW_SECONDS}" ||
  die "MAX_CLOCK_SKEW_SECONDS must be a non-negative integer"
is_epoch "${RTC_MINIMUM_EPOCH}" ||
  die "RTC_MINIMUM_EPOCH must be a non-negative integer"

nodes=("${CONTROLLER_NAME}" "${COMPUTE_NAME}")
for node in "${nodes[@]}"; do
  instance_running "${node}" || die "${node} is not running"

  host_before="$(date -u +%s)"
  if [[ "${mode}" == "sync" ]]; then
    result="$(
      run_on "${node}" env \
        HOST_EPOCH="${host_before}" \
        MAX_CLOCK_SKEW_SECONDS="${MAX_CLOCK_SKEW_SECONDS}" \
        RTC_MINIMUM_EPOCH="${RTC_MINIMUM_EPOCH}" \
        bash -s <<'GUEST_CLOCK_SYNC'
set -Eeuo pipefail

absolute_delta() {
  local left="$1"
  local right="$2"
  local delta=$((left - right))
  (( delta < 0 )) && delta=$((-delta))
  printf '%s\n' "${delta}"
}

method="host-gate"
if command -v chronyc >/dev/null 2>&1; then
  if sudo chronyc -a makestep >/dev/null 2>&1; then
    method="chrony"
    chronyc waitsync 5 0.5 0.0 1 >/dev/null 2>&1 || true
  fi
fi

current_epoch="$(date -u +%s)"
host_delta="$(absolute_delta "${current_epoch}" "${HOST_EPOCH}")"
if (( host_delta > MAX_CLOCK_SKEW_SECONDS )); then
  rtc_epoch_file=/sys/class/rtc/rtc0/since_epoch
  [[ -r "${rtc_epoch_file}" ]] || {
    echo "ERROR: clock is ${host_delta}s from the host and VZ RTC is unavailable" >&2
    exit 1
  }
  rtc_epoch="$(tr -d '[:space:]' < "${rtc_epoch_file}")"
  [[ "${rtc_epoch}" =~ ^[0-9]+$ ]] || {
    echo "ERROR: invalid VZ RTC epoch: ${rtc_epoch}" >&2
    exit 1
  }
  (( rtc_epoch >= RTC_MINIMUM_EPOCH )) || {
    echo "ERROR: VZ RTC epoch is implausibly old: ${rtc_epoch}" >&2
    exit 1
  }
  rtc_host_delta="$(absolute_delta "${rtc_epoch}" "${HOST_EPOCH}")"
  rtc_tolerance=$((MAX_CLOCK_SKEW_SECONDS + 10))
  (( rtc_host_delta <= rtc_tolerance )) || {
    echo "ERROR: VZ RTC differs from the host by ${rtc_host_delta}s" >&2
    exit 1
  }
  sudo date -u -s "@${rtc_epoch}" >/dev/null
  method="rtc"
fi

printf '%s\t%s\n' "${method}" "$(date -u +%s)"
GUEST_CLOCK_SYNC
    )" || die "failed to synchronize ${node} clock"
    IFS=$'\t' read -r method guest_epoch <<<"${result}"
  else
    method="check-only"
    guest_epoch="$(run_on "${node}" date -u +%s)"
  fi

  is_epoch "${guest_epoch}" || die "${node} returned an invalid epoch: ${guest_epoch}"
  host_after="$(date -u +%s)"
  lower_bound=$((host_before - MAX_CLOCK_SKEW_SECONDS))
  upper_bound=$((host_after + MAX_CLOCK_SKEW_SECONDS))
  within_window "${guest_epoch}" "${lower_bound}" "${upper_bound}" || {
    skew="$(absolute_delta "${guest_epoch}" "${host_after}")"
    die "${node} clock skew is ${skew}s; maximum is ${MAX_CLOCK_SKEW_SECONDS}s"
  }
  skew="$(absolute_delta "${guest_epoch}" "${host_after}")"
  log "${node} clock is healthy: skew=${skew}s method=${method}"
done
