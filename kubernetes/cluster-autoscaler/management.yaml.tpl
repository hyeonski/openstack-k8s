apiVersion: v1
kind: Namespace
metadata:
  name: ${CLUSTER_AUTOSCALER_NAMESPACE}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ${CLUSTER_AUTOSCALER_SERVICE_ACCOUNT}
  namespace: ${CLUSTER_AUTOSCALER_NAMESPACE}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: cluster-autoscaler-management
  namespace: ${WORKLOAD_NAMESPACE}
rules:
- apiGroups: ["cluster.x-k8s.io"]
  resources:
  - machinedeployments
  - machines
  - machinesets
  - machinepools
  verbs: ["get", "list", "update", "watch"]
- apiGroups: ["cluster.x-k8s.io"]
  resources: ["machinedeployments/scale", "machinepools/scale"]
  verbs: ["get", "patch", "update"]
- apiGroups: ["infrastructure.cluster.x-k8s.io"]
  resources: ["openstackmachinetemplates"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: cluster-autoscaler-management
  namespace: ${WORKLOAD_NAMESPACE}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: cluster-autoscaler-management
subjects:
- kind: ServiceAccount
  name: ${CLUSTER_AUTOSCALER_SERVICE_ACCOUNT}
  namespace: ${CLUSTER_AUTOSCALER_NAMESPACE}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
  namespace: ${CLUSTER_AUTOSCALER_NAMESPACE}
  labels:
    app.kubernetes.io/name: cluster-autoscaler
    app.kubernetes.io/part-of: openstack-k8s-m3
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: cluster-autoscaler
  template:
    metadata:
      labels:
        app.kubernetes.io/name: cluster-autoscaler
    spec:
      serviceAccountName: ${CLUSTER_AUTOSCALER_SERVICE_ACCOUNT}
      terminationGracePeriodSeconds: 10
      securityContext:
        fsGroup: 65534
        fsGroupChangePolicy: OnRootMismatch
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: cluster-autoscaler
        image: ${CLUSTER_AUTOSCALER_IMAGE}
        imagePullPolicy: IfNotPresent
        command: ["/cluster-autoscaler"]
        args:
        - --cloud-provider=clusterapi
        - --kubeconfig=/etc/cluster-autoscaler/workload/value
        - --clusterapi-cloud-config-authoritative
        - --node-group-auto-discovery=clusterapi:namespace=${WORKLOAD_NAMESPACE},clusterName=${WORKLOAD_CLUSTER_NAME}
        - --scale-down-enabled=false
        - --leader-elect=true
        - --v=4
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            memory: 256Mi
        securityContext:
          allowPrivilegeEscalation: false
          capabilities:
            drop: ["ALL"]
          readOnlyRootFilesystem: true
        volumeMounts:
        - name: workload-kubeconfig
          mountPath: /etc/cluster-autoscaler/workload
          readOnly: true
      tolerations:
      - key: node-role.kubernetes.io/control-plane
        effect: NoSchedule
      volumes:
      - name: workload-kubeconfig
        secret:
          secretName: ${CLUSTER_AUTOSCALER_WORKLOAD_KUBECONFIG_SECRET}
          defaultMode: 0440
