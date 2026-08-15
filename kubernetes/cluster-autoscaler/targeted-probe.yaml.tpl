apiVersion: v1
kind: Pod
metadata:
  name: ${CLUSTER_AUTOSCALER_TARGETED_PROBE_NAME}
  namespace: ${CLUSTER_AUTOSCALER_TEST_NAMESPACE}
  labels:
    app.kubernetes.io/part-of: openstack-k8s-m3
spec:
  nodeName: ${CLUSTER_AUTOSCALER_TARGET_NODE}
  restartPolicy: Never
  terminationGracePeriodSeconds: 0
  containers:
  - name: dns
    image: ${CLUSTER_AUTOSCALER_TEST_IMAGE}
    imagePullPolicy: IfNotPresent
    command:
    - sh
    - -ceu
    - nslookup kubernetes.default.svc.cluster.local >/dev/null
