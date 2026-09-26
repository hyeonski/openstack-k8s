apiVersion: cluster.x-k8s.io/v1beta2
kind: MachineHealthCheck
metadata:
  name: graduation-s4-worker
  namespace: ${WORKLOAD_NAMESPACE}
  labels:
    openstack-k8s.dev/experiment: graduation-s4
spec:
  clusterName: ${WORKLOAD_CLUSTER_NAME}
  selector:
    matchLabels:
      cluster.x-k8s.io/deployment-name: ${WORKLOAD_CLUSTER_NAME}-md-0
  checks:
    nodeStartupTimeoutSeconds: 900
    unhealthyNodeConditions:
    - type: Ready
      status: Unknown
      timeoutSeconds: 120
    - type: Ready
      status: "False"
      timeoutSeconds: 120
  remediation:
    triggerIf:
      unhealthyLessThanOrEqualTo: 1
