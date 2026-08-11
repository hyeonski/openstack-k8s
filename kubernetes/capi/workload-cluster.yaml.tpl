apiVersion: bootstrap.cluster.x-k8s.io/v1beta2
kind: KubeadmConfigTemplate
metadata:
  name: ${WORKLOAD_CLUSTER_NAME}-md-0
  namespace: ${WORKLOAD_NAMESPACE}
spec:
  template:
    spec:
      joinConfiguration:
        nodeRegistration:
          kubeletExtraArgs:
          - name: provider-id
            value: openstack:///'{{ instance_id }}'
          name: '{{ local_hostname }}'
---
apiVersion: cluster.x-k8s.io/v1beta2
kind: Cluster
metadata:
  name: ${WORKLOAD_CLUSTER_NAME}
  namespace: ${WORKLOAD_NAMESPACE}
spec:
  clusterNetwork:
    pods:
      cidrBlocks:
      - ${WORKLOAD_POD_CIDR}
    services:
      cidrBlocks:
      - ${WORKLOAD_SERVICE_CIDR}
    serviceDomain: cluster.local
  controlPlaneRef:
    apiGroup: controlplane.cluster.x-k8s.io
    kind: KubeadmControlPlane
    name: ${WORKLOAD_CLUSTER_NAME}-control-plane
  infrastructureRef:
    apiGroup: infrastructure.cluster.x-k8s.io
    kind: OpenStackCluster
    name: ${WORKLOAD_CLUSTER_NAME}
---
apiVersion: cluster.x-k8s.io/v1beta2
kind: MachineDeployment
metadata:
  name: ${WORKLOAD_CLUSTER_NAME}-md-0
  namespace: ${WORKLOAD_NAMESPACE}
spec:
  clusterName: ${WORKLOAD_CLUSTER_NAME}
  replicas: 1
  selector:
    matchLabels: null
  template:
    spec:
      bootstrap:
        configRef:
          apiGroup: bootstrap.cluster.x-k8s.io
          kind: KubeadmConfigTemplate
          name: ${WORKLOAD_CLUSTER_NAME}-md-0
      clusterName: ${WORKLOAD_CLUSTER_NAME}
      failureDomain: ${OPENSTACK_FAILURE_DOMAIN}
      infrastructureRef:
        apiGroup: infrastructure.cluster.x-k8s.io
        kind: OpenStackMachineTemplate
        name: ${WORKLOAD_CLUSTER_NAME}-md-0
      version: ${KUBERNETES_VERSION}
---
apiVersion: controlplane.cluster.x-k8s.io/v1beta2
kind: KubeadmControlPlane
metadata:
  name: ${WORKLOAD_CLUSTER_NAME}-control-plane
  namespace: ${WORKLOAD_NAMESPACE}
spec:
  kubeadmConfigSpec:
    initConfiguration:
      nodeRegistration:
        kubeletExtraArgs:
        - name: provider-id
          value: openstack:///'{{ instance_id }}'
        name: '{{ local_hostname }}'
    joinConfiguration:
      nodeRegistration:
        kubeletExtraArgs:
        - name: provider-id
          value: openstack:///'{{ instance_id }}'
        name: '{{ local_hostname }}'
  machineTemplate:
    spec:
      infrastructureRef:
        apiGroup: infrastructure.cluster.x-k8s.io
        kind: OpenStackMachineTemplate
        name: ${WORKLOAD_CLUSTER_NAME}-control-plane
  replicas: 1
  version: ${KUBERNETES_VERSION}
---
apiVersion: infrastructure.cluster.x-k8s.io/v1beta1
kind: OpenStackCluster
metadata:
  name: ${WORKLOAD_CLUSTER_NAME}
  namespace: ${WORKLOAD_NAMESPACE}
spec:
  externalNetwork:
    id: ${OPENSTACK_EXTERNAL_NETWORK_ID}
  identityRef:
    cloudName: capi
    name: ${WORKLOAD_CLUSTER_NAME}-cloud-config
  managedSecurityGroups:
    allNodesSecurityGroupRules:
    - description: Created by openstack-k8s M2 - BGP (Calico)
      direction: ingress
      etherType: IPv4
      name: BGP (Calico)
      portRangeMax: 179
      portRangeMin: 179
      protocol: tcp
      remoteManagedGroups:
      - controlplane
      - worker
    - description: Created by openstack-k8s M2 - IP-in-IP (Calico)
      direction: ingress
      etherType: IPv4
      name: IP-in-IP (Calico)
      protocol: "4"
      remoteManagedGroups:
      - controlplane
      - worker
    - description: Created by openstack-k8s M2 - internal SSH diagnostics
      direction: ingress
      etherType: IPv4
      name: SSH diagnostics
      portRangeMax: 22
      portRangeMin: 22
      protocol: tcp
      remoteIPPrefix: ${WORKLOAD_NETWORK_CIDR}
  managedSubnets:
  - cidr: ${WORKLOAD_NETWORK_CIDR}
    dnsNameservers:
    - ${WORKLOAD_DNS_NAMESERVER}
---
apiVersion: infrastructure.cluster.x-k8s.io/v1beta1
kind: OpenStackMachineTemplate
metadata:
  name: ${WORKLOAD_CLUSTER_NAME}-control-plane
  namespace: ${WORKLOAD_NAMESPACE}
spec:
  template:
    spec:
      configDrive: true
      flavor: ${KUBERNETES_CONTROL_PLANE_FLAVOR}
      image:
        filter:
          name: ${KUBERNETES_IMAGE_NAME}
      sshKeyName: ${WORKLOAD_SSH_KEY_NAME}
---
apiVersion: infrastructure.cluster.x-k8s.io/v1beta1
kind: OpenStackMachineTemplate
metadata:
  name: ${WORKLOAD_CLUSTER_NAME}-md-0
  namespace: ${WORKLOAD_NAMESPACE}
spec:
  template:
    spec:
      configDrive: true
      flavor: ${KUBERNETES_WORKER_FLAVOR}
      image:
        filter:
          name: ${KUBERNETES_IMAGE_NAME}
      sshKeyName: ${WORKLOAD_SSH_KEY_NAME}
