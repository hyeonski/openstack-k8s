extensions:
  health_check:
    endpoint: 0.0.0.0:13133
  file_storage:
    directory: /var/lib/otelcol
receivers:
  k8s_cluster:
    collection_interval: 15s
    node_conditions_to_report: [Ready, MemoryPressure, DiskPressure, PIDPressure, NetworkUnavailable]
    allocatable_types_to_report: [cpu, memory, ephemeral-storage, pods]
  k8sobjects:
    auth_type: serviceAccount
    objects:
      - {name: events, mode: watch, group: events.k8s.io}
processors:
  memory_limiter:
    check_interval: 5s
    limit_mib: 192
    spike_limit_mib: 48
  resource/cluster:
    attributes:
      - {key: environment, value: ${ENVIRONMENT_NAME}, action: upsert}
      - {key: k8s.cluster.name, value: ${OBS_CLUSTER_NAME}, action: upsert}
      - {key: service.name, value: osk8s-cluster-state, action: upsert}
      - {key: service.instance.id, value: ${OBS_CLUSTER_NAME}, action: upsert}
      - {key: location, value: ${GCP_ZONE}, action: upsert}
      - {key: layer, value: kubernetes-cluster, action: upsert}
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
    sending_queue: {enabled: true, queue_size: 1000, storage: file_storage}
service:
  extensions: [health_check, file_storage]
  pipelines:
    metrics:
      receivers: [k8s_cluster]
      processors: [memory_limiter, resource/cluster, batch]
      exporters: [otlp/gateway]
    logs:
      receivers: [k8sobjects]
      processors: [memory_limiter, resource/cluster, batch]
      exporters: [otlp/gateway]
