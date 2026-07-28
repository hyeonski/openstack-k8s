---
# Generated for the local ARM64 evaluation environment.
kolla_base_distro: "${KOLLA_BASE_DISTRO}"
openstack_release: "${KOLLA_SERIES}"
openstack_tag_suffix: "${KOLLA_OPENSTACK_TAG_SUFFIX}"
nova_libvirt_image: "${KOLLA_NOVA_LIBVIRT_IMAGE}"
nova_libvirt_tag: "${KOLLA_NOVA_LIBVIRT_TAG}"

# The Debian Bookworm ARM64 AAVMF bundled in the 2025.2 nova-libvirt image
# faults while booting current CirrOS and Ubuntu ARM64 EFI loaders under
# Lima/VZ nested KVM. The Ubuntu 24.04 compute host firmware boots both
# correctly, so keep this local-profile workaround explicit and replaceable.
nova_libvirt_extra_volumes:
  - "/usr/share/AAVMF:/usr/share/AAVMF:ro"

network_interface: "${LIMA_MANAGEMENT_INTERFACE}"
api_interface: "${LIMA_MANAGEMENT_INTERFACE}"
tunnel_interface: "${LIMA_MANAGEMENT_INTERFACE}"
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

# This is a two-node functional lab, not an HA deployment.
enable_haproxy: "yes"
enable_keepalived: "yes"
