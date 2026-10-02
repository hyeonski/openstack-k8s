#!/usr/bin/env bash
# Runs on the controller as root; shapes only a dedicated test veth.
set -Eeuo pipefail
[[ "$(id -u)" == 0 ]]
action=${1:?}; run=${2:?}
[[ "$run" =~ ^s2-[a-f0-9]{12}$ ]]
root="/var/lib/openstack-k8s-graduation/$run"
ns=osk8s-s2
case "$action" in
  prepare)
    [[ ! -e /run/osk8s-s2-owner ]] || { echo 'S2 network already owned' >&2; exit 1; }
    ! ip link show s2-egress >/dev/null 2>&1
    ! ip netns list | awk '{print $1}' | grep -qx "$ns"
    mkdir -p "$root"
    echo "$run" >/run/osk8s-s2-owner
    ip netns add "$ns"
    ip link add s2-egress type veth peer name s2-sink
    ip link set s2-sink netns "$ns"
    ip addr add 198.18.0.1/30 dev s2-egress
    ip link set s2-egress up
    ip netns exec "$ns" ip addr add 198.18.0.2/30 dev s2-sink
    ip netns exec "$ns" ip link set lo up
    ip netns exec "$ns" ip link set s2-sink up
    ip netns exec "$ns" ip route add default via 198.18.0.1
    iptables -I FORWARD -i veth-kolla-gw -o s2-egress -j ACCEPT
    iptables -I FORWARD -i s2-egress -o veth-kolla-gw -j ACCEPT
    tc qdisc add dev s2-egress root tbf rate 20mbit burst 32kb limit 1mb
    systemd-run --unit="osk8s-s2-sink-$run" --collect \
      ip netns exec "$ns" python3 /opt/openstack-k8s/graduation-s2-workload.py sink --root "$root"
    ;;
  sample)
    [[ "$(cat /run/osk8s-s2-owner)" == "$run" ]]
    tc -s -j qdisc show dev s2-egress
    ;;
  cleanup)
    [[ -f /run/osk8s-s2-owner ]] || exit 0
    [[ "$(cat /run/osk8s-s2-owner)" == "$run" ]]
    systemctl stop "osk8s-s2-sink-$run" || true
    # Stop only the namespace whose ownership token matches this experiment.
    if ip netns list | awk '{print $1}' | grep -qx "$ns"; then
      for pid in $(ip netns pids "$ns"); do kill "$pid" 2>/dev/null || true; done
      ip netns delete "$ns"
    fi
    iptables -D FORWARD -i veth-kolla-gw -o s2-egress -j ACCEPT || true
    iptables -D FORWARD -i s2-egress -o veth-kolla-gw -j ACCEPT || true
    ip link delete s2-egress 2>/dev/null || true
    python3 - "$root" <<'PY'
import pathlib, shutil, sys
root = pathlib.Path(sys.argv[1])
if root.is_symlink():
    raise SystemExit('refusing a symlink upload directory')
if root.exists():
    shutil.rmtree(root)
PY
    rm /run/osk8s-s2-owner
    ;;
  *) exit 2 ;;
esac
