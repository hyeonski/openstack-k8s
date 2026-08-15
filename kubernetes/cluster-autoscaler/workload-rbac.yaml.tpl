apiVersion: v1
kind: ServiceAccount
metadata:
  name: ${CLUSTER_AUTOSCALER_SERVICE_ACCOUNT}
  namespace: ${CLUSTER_AUTOSCALER_WORKLOAD_NAMESPACE}
---
apiVersion: v1
kind: Secret
metadata:
  name: ${CLUSTER_AUTOSCALER_WORKLOAD_TOKEN_SECRET}
  namespace: ${CLUSTER_AUTOSCALER_WORKLOAD_NAMESPACE}
  annotations:
    kubernetes.io/service-account.name: ${CLUSTER_AUTOSCALER_SERVICE_ACCOUNT}
type: kubernetes.io/service-account-token
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cluster-autoscaler-workload
rules:
- apiGroups: [""]
  resources:
  - namespaces
  - persistentvolumeclaims
  - persistentvolumes
  - pods
  - replicationcontrollers
  - services
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list", "update", "watch"]
- apiGroups: ["resource.k8s.io"]
  resources: ["resourceslices", "deviceclasses", "resourceclaims"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods/eviction"]
  verbs: ["create"]
- apiGroups: [""]
  resources: ["pods/status"]
  verbs: ["update"]
- apiGroups: ["policy"]
  resources: ["poddisruptionbudgets"]
  verbs: ["list", "watch"]
- apiGroups: ["storage.k8s.io"]
  resources:
  - csinodes
  - storageclasses
  - csidrivers
  - csistoragecapacities
  - volumeattachments
  verbs: ["get", "list", "watch"]
- apiGroups: ["batch"]
  resources: ["jobs", "cronjobs"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["apps"]
  resources: ["daemonsets", "replicasets", "statefulsets"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["events"]
  verbs: ["create", "patch"]
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["create", "delete", "get", "update"]
- apiGroups: ["coordination.k8s.io"]
  resources: ["leases"]
  verbs: ["create", "get", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: cluster-autoscaler-workload
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-autoscaler-workload
subjects:
- kind: ServiceAccount
  name: ${CLUSTER_AUTOSCALER_SERVICE_ACCOUNT}
  namespace: ${CLUSTER_AUTOSCALER_WORKLOAD_NAMESPACE}
