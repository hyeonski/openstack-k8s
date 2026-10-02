# Cinder CSI upstream source

The five `cinder-csi-*` / `csi-cinder-driver.yaml` manifests are vendored from
[kubernetes/cloud-provider-openstack v1.35.0](https://github.com/kubernetes/cloud-provider-openstack/tree/v1.35.0/manifests/cinder-csi-plugin).
The upstream Apache 2.0 license is included in `LICENSE`.

Local kustomize patches place the controller on the control-plane Node, omit
the unused snapshotter sidecar, and use the separately owned
`graduation-cinder-config` Secret. Plugin and sidecar image tags remain pinned
to the upstream release. No credential is included in this directory.
