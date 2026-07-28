ARG BASE_IMAGE=quay.io/openstack.kolla/nova-libvirt:2025.2-debian-bookworm-aarch64
FROM ${BASE_IMAGE}

USER root

# Kolla installs libvirt-daemon-system without recommended packages. On the
# Debian Bookworm ARM64 2025.2 image that leaves libvirtd without dnsmasq and
# makes the daemon exit during capability discovery.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        dnsmasq-base \
    && rm -rf /var/lib/apt/lists/*

LABEL org.openstack-k8s.purpose="add-missing-dnsmasq-to-nova-libvirt"
