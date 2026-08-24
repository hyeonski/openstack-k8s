# GCP host infrastructure

This configuration adopts the existing `openstack-k8s` project resources. It
must be imported before any plan is considered authoritative. The import path
does not create, update, stop or restart a GCP resource.

The 10-hour cost-control limit is part of the declared contract:

```hcl
max_run_duration_seconds = 36000
instance_termination_action = "STOP"
```

Run from the repository root:

```bash
make gcp-iac-init ENV=cloud-gcp-amd64
make gcp-iac-import ENV=cloud-gcp-amd64
make gcp-iac-plan ENV=cloud-gcp-amd64
```

The OpenStack Floating IP route was deliberately disabled during adoption. The
controller veth/NAT host gate, OpenStack bootstrap and image metadata checks
passed on 2026-08-21, so `openstack.auto.tfvars` now keeps the route enabled.
Confirm that the full plan is empty after any route change:

```bash
make gcp-iac-plan ENV=cloud-gcp-amd64
```

The Kubernetes node image is built on a disposable `n2-standard-4` instance
with an 80 GiB disk and nested KVM. Its plan is checked separately so creation
may add only `google_compute_instance.image_builder`, and deletion may remove
only that instance. The builder inherits the same 36,000-second automatic STOP
contract as the persistent OpenStack hosts.

```bash
make kubernetes-image-builder-create ENV=cloud-gcp-amd64
make kubernetes-image-build ENV=cloud-gcp-amd64
make kubernetes-image-upload ENV=cloud-gcp-amd64
make kubernetes-image-verify ENV=cloud-gcp-amd64
make kubernetes-image-builder-destroy \
  ENV=cloud-gcp-amd64 CONFIRM=cloud-gcp-amd64
```

The QCOW2 image, checksum and build metadata remain under
`.state/cloud-gcp-amd64/images` after the builder is deleted. A normal full
plan must return to `No changes` after deletion.

The management cluster runs on the Kolla controller. Kolla's Docker daemon
keeps `bridge=none`, `ip-forward=false` and `iptables=false`; the integration
does not modify or restart that daemon. A dedicated systemd unit creates the
standard Docker `kind` network with CIDR `172.30.0.0/24`, bridge
`br-kind-mgmt`, and explicit forwarding and masquerade rules.

```bash
make gcp-controller-management-prepare ENV=cloud-gcp-amd64
make management-cluster-create ENV=cloud-gcp-amd64
make management-cluster-verify ENV=cloud-gcp-amd64
make capi-providers-install ENV=cloud-gcp-amd64
make capi-providers-verify ENV=cloud-gcp-amd64
make capi-credentials-verify ENV=cloud-gcp-amd64
```

The kind API binds to `10.20.0.10:16443`. Firewall access is limited to the IAP
TCP-forwarding range and the `osk8s-controller-management` target tag. Local
kubectl traffic uses an IAP tunnel on `127.0.0.1:16443`; there is no public
Kubernetes API firewall rule. The existing controller retains its
36,000-second automatic STOP contract.

Provider, workload and autoscaler commands re-establish the IAP tunnel inside
their own process lifetime. They do not depend on a background tunnel left by
an earlier Make invocation. The verified provider set is CAPI/CABPK/KCP
v1.13.4, CAPO v0.14.6 and ORC v2.4.0; an in-cluster probe also verified the
OpenStack application credential against Keystone.

To prove the complete container path, preserve the OpenStack verification
server, probe both Keystone and its Floating IP service from a kind Pod, then
remove only the temporary verification resources:

```bash
KEEP_TEST_RESOURCES=YES make openstack-verify ENV=cloud-gcp-amd64
make management-cluster-verify ENV=cloud-gcp-amd64
make openstack-verification-cleanup ENV=cloud-gcp-amd64
```

`management-cluster-destroy CONFIRM=cloud-gcp-amd64` deletes only the kind
cluster, repository-local kubeconfig and dedicated bridge/NAT. The controller
and OpenStack resources remain protected.

Never apply a plan containing instance replacement or disk destruction. The
configuration also uses `prevent_destroy` for the imported network, addresses
and hosts as a final safety boundary.
