vmType: vz
arch: aarch64
cpus: ${IMAGE_BUILDER_CPUS}
memory: "${IMAGE_BUILDER_MEMORY_GIB}GiB"
disk: "${IMAGE_BUILDER_DISK_GIB}GiB"
nestedVirtualization: true
plain: true
containerd:
  user: false
  system: false
images:
  - location: "https://cloud-images.ubuntu.com/releases/noble/release/ubuntu-24.04-server-cloudimg-arm64.img"
    arch: aarch64
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
      hostnamectl set-hostname osk8s-image-builder
      apt-get update
      DEBIAN_FRONTEND=noninteractive apt-get install -y \
        ca-certificates curl git jq libvirt-daemon-system make openssl \
        python3 python3-pip python3-venv qemu-efi-aarch64 qemu-system-arm \
        qemu-utils rsync unzip xorriso
      install -d -m 0755 /var/lib/libvirt/images
      truncate -s 64M /var/lib/libvirt/images/capi.fd
      truncate -s 64M /var/lib/libvirt/images/capi-nvmram.fd
      dd if=/usr/share/qemu-efi-aarch64/QEMU_EFI.fd \
        of=/var/lib/libvirt/images/capi.fd conv=notrunc
      usermod -aG kvm ${TARGET_SSH_USER}
      chown ${TARGET_SSH_USER}:kvm \
        /var/lib/libvirt/images/capi.fd \
        /var/lib/libvirt/images/capi-nvmram.fd
      chmod 0660 \
        /var/lib/libvirt/images/capi.fd \
        /var/lib/libvirt/images/capi-nvmram.fd
      test -c /dev/kvm
