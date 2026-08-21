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

The persistent management host is separate from the Kolla controller because
Kolla intentionally configures that host's Docker daemon without a default
bridge, IP forwarding or Docker-managed iptables. It uses an `e2-standard-2`
instance, a 60 GiB balanced disk and reserved internal address `10.20.0.30`.

```bash
make gcp-management-host-create ENV=cloud-gcp-amd64
make management-cluster-create ENV=cloud-gcp-amd64
make management-cluster-verify ENV=cloud-gcp-amd64
```

The kind API binds to the host's internal address. Firewall access to TCP 6443
is limited to the IAP TCP-forwarding range and the `osk8s-management` target
tag. Local kubectl traffic uses an IAP tunnel on `127.0.0.1:16443`; there is no
public Kubernetes API firewall rule. The host retains the same 36,000-second
automatic STOP contract and is included in `gcp-start` and `gcp-stop` after it
exists.

To prove the complete container path, preserve the OpenStack verification
server, probe both Keystone and its Floating IP service from a kind Pod, then
remove only the temporary verification resources:

```bash
KEEP_TEST_RESOURCES=YES make openstack-verify ENV=cloud-gcp-amd64
make management-cluster-verify ENV=cloud-gcp-amd64
make openstack-verification-cleanup ENV=cloud-gcp-amd64
```

`management-cluster-destroy CONFIRM=cloud-gcp-amd64` deletes only the kind
cluster and its repository-local kubeconfig. The management VM and OpenStack
resources remain protected.

Never apply a plan containing instance replacement or disk destruction. The
configuration also uses `prevent_destroy` for the imported network, addresses
and hosts as a final safety boundary.
