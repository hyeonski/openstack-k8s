# Confirmed design decisions

| Area | Decision |
|---|---|
| Final objective | OpenStack-backed Kubernetes worker node autoscaling, then failure/latency research |
| Current scope | OpenStack host creation, Kolla deployment, and standalone verification only |
| Local VM manager | Lima |
| Lima networking | socket_vmnet `shared` named management network |
| External network | controller-local veth pair, OVS `br-ex`, routed/NATed Floating IP subnet |
| Local architecture | Ubuntu 24.04 ARM64 |
| Later architecture | separate AMD64 cloud and physical profiles |
| OpenStack/Kolla | 2025.2 |
| Neutron | ML2/Open vSwitch |
| Services | Core services plus Horizon; optional storage/orchestration/KaaS/LB/telemetry excluded |
| Deployment host | Kolla-Ansible executes inside controller; Mac repository is source of truth |
| Nested virtualization | KVM is mandatory; no QEMU fallback in this profile |
| Local sizing | controller 4/8/80, compute 4/5/80, 2 GiB guest swap each |
| Verification images | CirrOS ARM64, then Ubuntu 24.04 ARM64, sequentially |
| CAPO preflight | Kubernetes-free Docker bridge probe to OpenStack API VIP and FIP:6443 |
| Automation split | shell for host lifecycle; Ansible for OS; Kolla-Ansible for OpenStack; openstack.cloud/SDK for resources |
| Secrets | local ignored state with restrictive permissions; SOPS deferred |
| Teardown | explicit exact-name deletion; preserve secrets/artifacts and unrelated tools/VMs |

Local testing is a conditional feasibility gate. It validates topology and
automation behavior but does not establish performance results. The automation
will be re-applied, not live-migrated, when moving to cloud VMs and bare metal.

The local ARM64 hosts remain Ubuntu 24.04. Kolla containers use the official
2025.2 Debian Bookworm ARM64 images because matching Ubuntu Noble ARM64 release
tags are not published. The container base is an environment-level variable and
does not change the controller/compute topology.

The official 2025.2 Debian ARM64 `nova-libvirt` image lacks `dnsmasq-base`
because Kolla installs `libvirt-daemon-system` without recommended packages.
Libvirt fails during capability discovery without the binary. The local ARM64
profile therefore builds a pinned, single-package derivative and overrides
only `nova_libvirt_image`; all other services continue using official images.
