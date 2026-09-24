#!/usr/bin/env bash
# Runs on an Ubuntu GCE host after config/cert files have been copied to /tmp.
set -Eeuo pipefail
[[ "$(id -u)" == 0 ]] || { echo 'root required' >&2; exit 1; }
role="${1:?controller or compute}"
project="${2:?project}"
zone="${3:?zone}"
environment="${4:?environment}"
[[ "${role}" == controller || "${role}" == compute ]] || exit 2
command -v docker >/dev/null

install -d -m 0700 /etc/osk8s-observability /var/lib/osk8s-observability
install -d -m 0755 /var/log/osk8s-observability
install -m 0600 /tmp/osk8s-otel-config.yaml /etc/osk8s-observability/config.yaml
if [[ "${role}" == controller ]]; then
  for item in ca.crt gateway.crt gateway.key; do
    install -m 0600 "/tmp/osk8s-${item}" "/etc/osk8s-observability/${item}"
  done
  listen='10.20.0.10:4317'
  install -d -m 0755 /opt/openstack-k8s/observability
  install -m 0755 /tmp/osk8s-openstack-inventory.py \
    /opt/openstack-k8s/observability/openstack-inventory.py
  install -m 0644 /tmp/osk8s-openstack-inventory.service \
    /etc/systemd/system/openstack-inventory.service
  install -m 0644 /tmp/osk8s-openstack-inventory.timer \
    /etc/systemd/system/openstack-inventory.timer
else
  listen='127.0.0.1:4317'
fi

cat >/etc/osk8s-observability/environment <<EOF
GCP_PROJECT_ID=${project}
GCP_ZONE=${zone}
OSK8S_ENV=${environment}
OTLP_LISTEN=${listen}
HOSTNAME=$(hostname)
EOF
chmod 0600 /etc/osk8s-observability/environment

cat >/etc/logrotate.d/osk8s-observability <<'EOF'
/var/log/osk8s-observability/*.jsonl {
    daily
    rotate 7
    missingok
    notifempty
    copytruncate
}
EOF
cat >/usr/local/bin/osk8s-observability-heartbeat <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '{"time":"%s","host":"%s","kind":"collector_source_heartbeat"}\n' \
  "$(date -u +%FT%TZ)" "$(hostname)" >>/var/log/osk8s-observability/heartbeat.jsonl
EOF
chmod 0755 /usr/local/bin/osk8s-observability-heartbeat
cat >/etc/systemd/system/osk8s-observability-heartbeat.service <<'EOF'
[Unit]
Description=Write a local observability heartbeat
[Service]
Type=oneshot
ExecStart=/usr/local/bin/osk8s-observability-heartbeat
EOF
cat >/etc/systemd/system/osk8s-observability-heartbeat.timer <<'EOF'
[Unit]
Description=Write source heartbeat every minute
[Timer]
OnBootSec=30s
OnUnitActiveSec=60s
AccuracySec=5s
Unit=osk8s-observability-heartbeat.service
[Install]
WantedBy=timers.target
EOF

cat >/etc/systemd/system/osk8s-otel-collector.service <<'EOF'
[Unit]
Description=OpenStack Kubernetes OpenTelemetry collector
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
EnvironmentFile=/etc/osk8s-observability/environment
ExecStartPre=-/usr/bin/docker rm -f osk8s-otel-collector
ExecStart=/usr/bin/docker run --rm --name osk8s-otel-collector --network=host --pid=host --user=0:0 --memory=512m -e GCP_PROJECT_ID -e GCP_ZONE -e OSK8S_ENV -e OTLP_LISTEN -e HOSTNAME -v /:/hostfs:ro -v /etc/osk8s-observability:/etc/otel:ro -v /var/lib/osk8s-observability:/var/lib/otelcol:rw otel/opentelemetry-collector-contrib:0.140.0 --config=/etc/otel/config.yaml
ExecStop=/usr/bin/docker stop osk8s-otel-collector
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
docker pull otel/opentelemetry-collector-contrib:0.140.0
systemctl daemon-reload
systemctl enable osk8s-otel-collector.service
systemctl restart osk8s-otel-collector.service
systemctl is-active --quiet osk8s-otel-collector.service
systemctl enable --now osk8s-observability-heartbeat.timer
if [[ "${role}" == controller ]]; then
  systemctl enable --now openstack-inventory.timer
fi
rm -f /tmp/osk8s-otel-config.yaml /tmp/osk8s-host-install.sh
if [[ "${role}" == controller ]]; then
  rm -f /tmp/osk8s-ca.crt /tmp/osk8s-gateway.crt /tmp/osk8s-gateway.key \
    /tmp/osk8s-openstack-inventory.py /tmp/osk8s-openstack-inventory.service \
    /tmp/osk8s-openstack-inventory.timer
fi
echo 'host collector active'
