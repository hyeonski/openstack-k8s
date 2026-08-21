#!/usr/bin/env bash

set -Eeuo pipefail

TARGET_SSH_USER="${TARGET_SSH_USER:?}"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  ca-certificates curl git jq make openssl python3 python3-pip \
  python3-venv qemu-system-x86 qemu-utils rsync unzip xorriso

test "$(uname -m)" = "x86_64"
test -c /dev/kvm
getent group kvm >/dev/null
usermod -aG kvm "${TARGET_SSH_USER}"

echo "GCP AMD64 image-builder host is prepared"
