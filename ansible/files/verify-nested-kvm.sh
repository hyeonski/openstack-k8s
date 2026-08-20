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

case "$(uname -m)" in
  aarch64|arm64)
    qemu_binary="qemu-system-aarch64"
    machine_args=( -machine virt,accel=kvm -cpu host )
    console="ttyAMA0"
    ;;
  x86_64)
    qemu_binary="qemu-system-x86_64"
    machine_args=( -machine accel=kvm -cpu host )
    console="ttyS0"
    ;;
  *)
    echo "unsupported KVM verification architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

set +e
timeout 45 "${qemu_binary}" \
  "${machine_args[@]}" \
  -m 512 \
  -smp 1 \
  -nographic \
  -no-reboot \
  -kernel "${kernel}" \
  -initrd "${initrd}" \
  -append "console=${console} rdinit=/bin/sh panic=-1" \
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
