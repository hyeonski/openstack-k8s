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
[[ -r "${initrd}" ]] || {
  echo "initrd not found: ${initrd}" >&2
  exit 1
}

output="$(mktemp)"
cleanup() {
  rm -f "${output}"
}
trap cleanup EXIT

set +e
timeout 45 qemu-system-aarch64 \
  -machine virt,accel=kvm \
  -cpu host \
  -m 512 \
  -smp 1 \
  -nographic \
  -no-reboot \
  -kernel "${kernel}" \
  -initrd "${initrd}" \
  -append "console=ttyAMA0 rdinit=/bin/sh panic=-1" \
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

