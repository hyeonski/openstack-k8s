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

Never apply a plan containing instance replacement or disk destruction. The
configuration also uses `prevent_destroy` for the imported network, addresses
and hosts as a final safety boundary.
