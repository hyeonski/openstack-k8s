apiVersion: v1
kind: Pod
metadata:
  name: ${WORKLOAD_CLUSTER_NAME}-openstack-auth-probe
  namespace: ${WORKLOAD_NAMESPACE}
spec:
  restartPolicy: Never
  containers:
  - name: probe
    image: busybox:1.37.0
    command:
    - sh
    - -ceu
    - |
      cloud=/etc/openstack/clouds.yaml
      auth_url=$$(awk '/auth_url:/ {print $$2; exit}' "$${cloud}")
      credential_id=$$(awk '/application_credential_id:/ {print $$2; exit}' "$${cloud}")
      credential_secret=$$(awk '/application_credential_secret:/ {print $$2; exit}' "$${cloud}")
      test -n "$${auth_url}"
      test -n "$${credential_id}"
      test -n "$${credential_secret}"
      body="{\"auth\":{\"identity\":{\"methods\":[\"application_credential\"],\"application_credential\":{\"id\":\"$${credential_id}\",\"secret\":\"$${credential_secret}\"}}}}"
      wget -qO /dev/null --header='Content-Type: application/json' \
        --post-data="$${body}" "$${auth_url%/}/auth/tokens"
      echo authenticated
    volumeMounts:
    - name: cloud-config
      mountPath: /etc/openstack
      readOnly: true
  volumes:
  - name: cloud-config
    secret:
      secretName: ${WORKLOAD_CLUSTER_NAME}-cloud-config
