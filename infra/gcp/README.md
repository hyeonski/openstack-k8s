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

Never apply a plan containing instance replacement or disk destruction. The
configuration also uses `prevent_destroy` for the imported network, addresses
and hosts as a final safety boundary.
