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

The OpenStack Floating IP route is deliberately disabled during adoption. It
is enabled only after the controller's veth/NAT external-network service has
passed its host gate:

```bash
tofu -chdir=infra/gcp plan \
  -var='enable_openstack_floating_ip_route=true'
```

Never apply a plan containing instance replacement or disk destruction. The
configuration also uses `prevent_destroy` for the imported network, addresses
and hosts as a final safety boundary.
