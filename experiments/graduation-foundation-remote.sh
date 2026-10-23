#!/usr/bin/env bash
# Dedicated, file-backed Cinder lab storage; never initialize an existing disk.
set -Eeuo pipefail
[[ "$(id -u)" == 0 ]] || { echo 'run as root' >&2; exit 1; }
root=/var/lib/openstack-k8s-graduation
image="${root}/cinder.img"
vg=graduation-cinder
mkdir -p "$root"
chmod 700 "$root"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq lvm2
if [[ ! -f "$root/owner" ]]; then
  [[ ! -e "$image" ]] || { echo 'unowned Cinder image' >&2; exit 1; }
  ! vgs "$vg" >/dev/null 2>&1 || { echo 'unowned volume group' >&2; exit 1; }
  printf '%s\n' openstack-k8s-graduation >"$root/owner"
fi
[[ "$(cat "$root/owner")" == openstack-k8s-graduation ]]
if [[ ! -f "$image" ]]; then
  # Allocation failure is explicit; no sparse overcommit of the controller disk.
  fallocate -l 20G "$image"
  chmod 600 "$image"
fi
cat >/usr/local/sbin/osk8s-graduation-storage <<'LOOP'
#!/usr/bin/env bash
set -Eeuo pipefail
image=/var/lib/openstack-k8s-graduation/cinder.img
[[ "$(cat /var/lib/openstack-k8s-graduation/owner)" == openstack-k8s-graduation ]]
loop=$(losetup -j "$image" -O NAME --noheadings)
if [[ -z "$loop" ]]; then loop=$(losetup --find --show "$image"); fi
[[ "$loop" != *$'\n'* ]]
if ! pvs "$loop" >/dev/null 2>&1; then
  ! vgs graduation-cinder >/dev/null 2>&1
  pvcreate "$loop"
  vgcreate graduation-cinder "$loop"
fi
[[ "$(pvs --noheadings -o vg_name "$loop" | xargs)" == graduation-cinder ]]
vgchange -ay graduation-cinder
LOOP
chmod 755 /usr/local/sbin/osk8s-graduation-storage
cat >/etc/systemd/system/osk8s-graduation-storage.service <<'UNIT'
[Unit]
Description=OpenStack Kubernetes graduation Cinder lab volume group
After=local-fs.target
Before=docker.service
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/osk8s-graduation-storage
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now osk8s-graduation-storage.service
mkdir -p /etc/kolla/globals.d
cat >/etc/kolla/globals.d/graduation.yml <<'YAML'
# Repository-owned S2/S3 functional testbed foundation.
enable_neutron_qos: "yes"
enable_cinder: "yes"
enable_cinder_backend_lvm: "yes"
enable_cinder_backup: "no"
cinder_volume_group: "graduation-cinder"
YAML
# Kolla runs as the deployment user and silently skips unreadable overrides.
# This file contains feature flags only, no credentials.
chmod 644 /etc/kolla/globals.d/graduation.yml
python3 - <<'PY'
from pathlib import Path
import re
path = Path('/opt/openstack-k8s/kolla/generated/multinode')
content = path.read_text()
if not re.search(r'(?ms)^\[storage\]\n(?:\s*|controller\s*)?(?=^\[)', content):
    raise SystemExit('unexpected storage inventory; refusing replacement')
path.write_text(re.sub(r'(?ms)^\[storage\]\n.*?(?=^\[)', '[storage]\ncontroller\n\n', content, count=1))
PY
vgs "$vg" --noheadings -o vg_name,vg_size,vg_free
