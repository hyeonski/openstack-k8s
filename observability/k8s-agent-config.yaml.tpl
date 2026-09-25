extensions:
  health_check:
    endpoint: 0.0.0.0:13133
  file_storage:
    directory: /var/lib/otelcol
receivers:
  hostmetrics:
    collection_interval: 15s
    root_path: /hostfs
    scrapers:
      cpu: {}
      memory: {}
      load: {}
      disk: {}
      filesystem: {}
      network: {}
      paging: {}
  kubeletstats:
    collection_interval: 15s
    auth_type: serviceAccount
    endpoint: "https://$${env:K8S_NODE_IP}:10250"
    insecure_skip_verify: true
    metric_groups: [node, pod, container, volume]
  filelog/pods:
    include: [/var/log/pods/*/*/*.log]
    start_at: end
    include_file_path: true
    operators:
      - {type: container, id: container-parser}
    storage: file_storage
    retry_on_failure: {enabled: true}
processors:
  memory_limiter:
    check_interval: 5s
    limit_mib: 192
    spike_limit_mib: 48
  resource/agent:
    attributes:
      - {key: environment, value: ${ENVIRONMENT_NAME}, action: upsert}
      - {key: k8s.cluster.name, value: ${OBS_CLUSTER_NAME}, action: upsert}
      - {key: service.name, value: osk8s-node-agent, action: upsert}
      - {key: service.instance.id, value: "$${env:K8S_NODE_NAME}", action: upsert}
      - {key: location, value: ${GCP_ZONE}, action: upsert}
      - {key: layer, value: kubernetes-node, action: upsert}
  batch:
    timeout: 5s
    send_batch_size: 512
exporters:
  otlp/gateway:
    endpoint: 10.20.0.10:4317
    tls:
      ca_file: /etc/otel-certs/ca.crt
      cert_file: /etc/otel-certs/agent.crt
      key_file: /etc/otel-certs/agent.key
    # Include gateway startup and gRPC reconnect backoff in the retry budget.
    retry_on_failure: {enabled: true, max_elapsed_time: 10m}
    # Preserve per-source sample order when replaying a gateway outage.
    sending_queue: {enabled: true, num_consumers: 1, queue_size: 1000, storage: file_storage}
service:
  extensions: [health_check, file_storage]
  pipelines:
    metrics:
      receivers: [hostmetrics, kubeletstats]
      processors: [memory_limiter, resource/agent, batch]
      exporters: [otlp/gateway]
    logs:
      receivers: [filelog/pods]
      processors: [memory_limiter, resource/agent, batch]
      exporters: [otlp/gateway]
