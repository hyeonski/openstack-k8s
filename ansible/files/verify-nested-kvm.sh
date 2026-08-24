#!/usr/bin/env bash

set -Eeuo pipefail

[[ -c /dev/kvm ]] || {
  echo "/dev/kvm is not a character device" >&2
  exit 1
}

kernel="/boot/vmlinuz-$(uname -r)"
initrd="/boot/initrd.img-$(uname -r)"
[[ -r "${kernel}" ]] || {
  echo "kernel not found: ${kernel}" >&2
  exit 1
}

initrd_args=()
kernel_append="panic=-1"
if [[ -r "${initrd}" ]]; then
  initrd_args=( -initrd "${initrd}" )
  kernel_append+=" rdinit=/bin/sh"
else
  echo "initrd not found; verifying direct kernel boot: ${initrd}" >&2
fi

output="$(mktemp)"
cleanup() {
  rm -f "${output}"
}
trap cleanup EXIT

[[ "$(uname -m)" == "x86_64" ]] || {
  echo "GCP KVM verification requires x86_64; found $(uname -m)" >&2
  exit 1
}
qemu_binary="qemu-system-x86_64"
machine_args=( -machine accel=kvm -cpu host )
console="ttyS0"

set +e
timeout 45 "${qemu_binary}" \
  "${machine_args[@]}" \
  -m 512 \
  -smp 1 \
  -nographic \
  -no-reboot \
  -kernel "${kernel}" \
  "${initrd_args[@]}" \
  -append "console=${console} ${kernel_append}" \
  >"${output}" 2>&1
result=$?
set -e

if grep -Eq 'Booting Linux|Linux version|Run /init' "${output}"; then
  echo "Nested KVM boot succeeded"
  exit 0
fi

echo "Nested KVM boot did not reach the Linux kernel (qemu exit ${result})" >&2
tail -n 100 "${output}" >&2
exit 1
