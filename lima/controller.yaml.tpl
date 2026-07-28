vmType: vz
arch: aarch64
cpus: ${CONTROLLER_CPUS}
memory: "${CONTROLLER_MEMORY_GIB}GiB"
disk: "${CONTROLLER_DISK_GIB}GiB"
plain: true
containerd:
  user: false
  system: false
images:
  - location: "https://cloud-images.ubuntu.com/releases/noble/release/ubuntu-24.04-server-cloudimg-arm64.img"
    arch: aarch64
networks:
  - lima: ${LIMA_NETWORK_NAME}
    interface: ${LIMA_MANAGEMENT_INTERFACE}
user:
  name: ${TARGET_SSH_USER}
  home: /home/${TARGET_SSH_USER}
  shell: /bin/bash
  uid: 1000
ssh:
  loadDotSSHPubKeys: false
provision:
  - mode: system
    script: |
      #!/bin/bash
      set -eux
      hostnamectl set-hostname osk8s-controller
      apt-get update
      DEBIAN_FRONTEND=noninteractive apt-get install -y \
        ca-certificates curl git jq openssh-client python3 python3-pip \
        python3-venv rsync

