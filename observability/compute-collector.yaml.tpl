extensions:
  health_check:
    endpoint: 127.0.0.1:13133
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
  filelog/system:
    include: [/hostfs/var/log/syslog]
    start_at: end
    storage: file_storage
    retry_on_failure: {enabled: true}
  filelog/kolla:
    include: [/hostfs/var/lib/docker/volumes/kolla_logs/_data/*/*.log]
    start_at: end
    include_file_path: true
    storage: file_storage
    retry_on_failure: {enabled: true}
  filelog/observability:
    include: [/hostfs/var/log/osk8s-observability/*.jsonl]
    start_at: beginning
    operators:
      - type: json_parser
        parse_to: body
        # Preserve source time when local JSONL is replayed after an outage.
        timestamp:
          parse_from: body.time
          layout_type: gotime
          layout: '2006-01-02T15:04:05.999999999Z07:00'
    storage: file_storage
    retry_on_failure: {enabled: true}
processors:
  memory_limiter:
    check_interval: 5s
    limit_mib: 384
    spike_limit_mib: 96
  resource/host:
    attributes:
      - {key: environment, value: "$${env:OSK8S_ENV}", action: upsert}
      - {key: k8s.cluster.name, value: "$${env:OSK8S_ENV}-hosts", action: upsert}
      - {key: service.name, value: osk8s-hostmetrics, action: upsert}
      - {key: service.instance.id, value: "$${env:HOSTNAME}", action: upsert}
      - {key: location, value: "$${env:GCP_ZONE}", action: upsert}
      - {key: layer, value: gce-host, action: upsert}
  batch:
    timeout: 5s
    send_batch_size: 512
  transform/redact:
    error_mode: ignore
    log_statements:
      - context: log
        statements:
          - 'replace_pattern(body, "(?i)(password|token|secret|authorization)[=: ]+[A-Za-z0-9_./+:-]{8,}", "$$1=[REDACTED]") where IsString(body)'
  redaction:
    allow_all_keys: true
    blocked_key_patterns: ['(?i).*(password|token|secret|authorization|api_key).*']
    blocked_values: ['(?i)bearer[ ]+[A-Za-z0-9._~+/-]+']
    summary: silent
exporters:
  googlemanagedprometheus:
    project: "$${env:GCP_PROJECT_ID}"
    metric:
      resource_filters:
        - {prefix: environment}
        - {prefix: layer}
        - {prefix: k8s.}
        - {prefix: host.}
        - {prefix: container.}
    # GMP requires sample order during persistent queue replay.
    sending_queue: {enabled: true, num_consumers: 1, queue_size: 1000, storage: file_storage}
  googlecloud:
    project: "$${env:GCP_PROJECT_ID}"
    log:
      default_log_name: osk8s-otel
      resource_filters:
        - {prefix: environment}
        - {prefix: layer}
        - {prefix: k8s.}
        - {prefix: service.}
        - {prefix: location}
    sending_queue: {enabled: true, queue_size: 1000, storage: file_storage}
service:
  extensions: [health_check, file_storage]
  pipelines:
    metrics:
      receivers: [hostmetrics]
      processors: [memory_limiter, resource/host, batch]
      exporters: [googlemanagedprometheus]
    logs:
      receivers: [filelog/system, filelog/kolla, filelog/observability]
      processors: [memory_limiter, resource/host, transform/redact, redaction, batch]
      exporters: [googlecloud]
