# The controller external-network host gate and OpenStack bootstrap passed on
# 2026-08-21. Keep the Neutron Floating IP range routed through the controller
# for guest verification and the following CAPO checkpoints.
enable_openstack_floating_ip_route = true

# The Kolla Docker daemon deliberately has no bridge or iptables management.
# Keep the kind management cluster on its own lifecycle-managed host.
enable_management_host = true
