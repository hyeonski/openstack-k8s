#!/usr/bin/env bash

set -Eeuo pipefail

TARGET_SSH_USER="${TARGET_SSH_USER:?}"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates conntrack curl docker.io jq socat
systemctl enable --now docker
usermod -aG docker "${TARGET_SSH_USER}"

test "$(uname -m)" = "x86_64"
test "$(stat -fc %T /sys/fs/cgroup)" = "cgroup2fs"
docker info >/dev/null

echo "GCP management host is prepared"
