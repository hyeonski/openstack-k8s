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
      set -Eeuxo pipefail
      hostnamectl set-hostname osk8s-controller
      max_skew_seconds=${MAX_CLOCK_SKEW_SECONDS}
      minimum_rtc_epoch=${RTC_MINIMUM_EPOCH}
      [[ "$${max_skew_seconds}" =~ ^[0-9]+$$ ]] || {
        echo "ERROR: invalid maximum clock skew: $${max_skew_seconds}" >&2
        exit 1
      }
      [[ "$${minimum_rtc_epoch}" =~ ^[0-9]+$$ ]] || {
        echo "ERROR: invalid minimum RTC epoch: $${minimum_rtc_epoch}" >&2
        exit 1
      }
      rtc_epoch_file=/sys/class/rtc/rtc0/since_epoch
      [[ -r "$${rtc_epoch_file}" ]] || {
        echo "ERROR: local-arm64 requires a readable VZ RTC: $${rtc_epoch_file}" >&2
        exit 1
      }
      rtc_epoch="$$(tr -d '[:space:]' < "$${rtc_epoch_file}")"
      [[ "$${rtc_epoch}" =~ ^[0-9]+$$ ]] || {
        echo "ERROR: invalid VZ RTC epoch: $${rtc_epoch}" >&2
        exit 1
      }
      (( rtc_epoch >= minimum_rtc_epoch )) || {
        echo "ERROR: VZ RTC epoch is implausibly old: $${rtc_epoch}" >&2
        exit 1
      }
      system_epoch="$$(date -u +%s)"
      clock_delta=$$((rtc_epoch - system_epoch))
      (( clock_delta < 0 )) && clock_delta=$$((-clock_delta))
      if (( clock_delta > max_skew_seconds )); then
        date -u -s "@$${rtc_epoch}" >/dev/null
      fi
      corrected_epoch="$$(date -u +%s)"
      corrected_delta=$$((rtc_epoch - corrected_epoch))
      (( corrected_delta < 0 )) && corrected_delta=$$((-corrected_delta))
      (( corrected_delta <= max_skew_seconds )) || {
        echo "ERROR: failed to bootstrap system clock from the VZ RTC" >&2
        exit 1
      }
      apt-get update
      DEBIAN_FRONTEND=noninteractive apt-get install -y \
        ca-certificates chrony curl git jq openssh-client python3 python3-pip \
        python3-venv rsync
      if grep -Eq '^[[:space:]]*makestep[[:space:]]+' /etc/chrony/chrony.conf; then
        sed -i -E 's/^[[:space:]]*makestep[[:space:]].*/makestep 1.0 -1/' \
          /etc/chrony/chrony.conf
      else
        printf '\nmakestep 1.0 -1\n' >> /etc/chrony/chrony.conf
      fi
      systemctl enable --now chrony
      systemctl restart chrony
