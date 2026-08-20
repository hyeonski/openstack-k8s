---
# GCP AMD64 functional evaluation environment.
kolla_base_distro: "${KOLLA_BASE_DISTRO}"
openstack_release: "${KOLLA_SERIES}"
openstack_tag_suffix: "${KOLLA_OPENSTACK_TAG_SUFFIX}"

network_interface: "${MANAGEMENT_INTERFACE}"
api_interface: "${MANAGEMENT_INTERFACE}"
tunnel_interface: "${MANAGEMENT_INTERFACE}"
kolla_internal_vip_address: "${KOLLA_INTERNAL_VIP_ADDRESS}"
neutron_external_interface: "${EXTERNAL_INTERFACE}"
neutron_plugin_agent: "openvswitch"
enable_neutron_provider_networks: "no"
enable_neutron_agent_ha: "no"
enable_neutron_dvr: "no"

nova_compute_virt_type: "kvm"

enable_openstack_core: "yes"
enable_horizon: "yes"
enable_cinder: "no"
enable_heat: "no"
enable_magnum: "no"
enable_octavia: "no"
enable_ceilometer: "no"
enable_aodh: "no"
enable_gnocchi: "no"
enable_prometheus: "no"
enable_fluentd: "no"

glance_backend_file: "yes"
enable_glance: "yes"
enable_neutron: "yes"
enable_nova: "yes"

# This is a three-host functional lab with one controller, not an HA control
# plane. The VIP remains a GCP alias IP assigned to the controller NIC.
enable_haproxy: "yes"
enable_keepalived: "yes"
