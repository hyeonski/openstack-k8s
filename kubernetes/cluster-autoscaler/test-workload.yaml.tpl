apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${CLUSTER_AUTOSCALER_TEST_NAME}
  namespace: ${CLUSTER_AUTOSCALER_TEST_NAMESPACE}
  labels:
    app.kubernetes.io/name: ${CLUSTER_AUTOSCALER_TEST_NAME}
    app.kubernetes.io/part-of: openstack-k8s-m3
spec:
  replicas: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: ${CLUSTER_AUTOSCALER_TEST_NAME}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: ${CLUSTER_AUTOSCALER_TEST_NAME}
    spec:
      terminationGracePeriodSeconds: 0
      containers:
      - name: load
        image: ${CLUSTER_AUTOSCALER_TEST_IMAGE}
        imagePullPolicy: IfNotPresent
        command: ["sh", "-ceu", "trap : TERM INT; sleep infinity & wait"]
        resources:
          requests:
            cpu: ${CLUSTER_AUTOSCALER_TEST_CPU_REQUEST}
            memory: 16Mi
          limits:
            cpu: ${CLUSTER_AUTOSCALER_TEST_CPU_REQUEST}
            memory: 32Mi
