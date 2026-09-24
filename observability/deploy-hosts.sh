#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${ROOT}/scripts/lib/common.sh"
action="${1:-}"
cert_dir="${SECRET_DIR}/observability"

make_certs() {
  require_command openssl
  ensure_state_dirs
  mkdir_private "${cert_dir}"
  if [[ -f "${cert_dir}/ca.crt" ]]; then
    for name in ca.key gateway.crt gateway.key agent.crt agent.key; do
      [[ -f "${cert_dir}/${name}" ]] || die "incomplete observability certificate set"
    done
    return
  fi
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 1095 \
    -subj '/CN=osk8s-observability-ca' \
    -keyout "${cert_dir}/ca.key" -out "${cert_dir}/ca.crt" >/dev/null 2>&1
  openssl req -newkey rsa:3072 -sha256 -nodes \
    -subj '/CN=osk8s-controller' -keyout "${cert_dir}/gateway.key" \
    -out "${cert_dir}/gateway.csr" >/dev/null 2>&1
  printf '%s\n' 'subjectAltName=IP:10.20.0.10,DNS:osk8s-controller' 'extendedKeyUsage=serverAuth' \
    >"${cert_dir}/gateway.ext"
  openssl x509 -req -in "${cert_dir}/gateway.csr" -CA "${cert_dir}/ca.crt" \
    -CAkey "${cert_dir}/ca.key" -CAserial "${cert_dir}/ca.srl" -CAcreateserial -days 365 -sha256 \
    -extfile "${cert_dir}/gateway.ext" -out "${cert_dir}/gateway.crt" >/dev/null 2>&1
  openssl req -newkey rsa:3072 -sha256 -nodes \
    -subj '/CN=osk8s-cluster-collector' -keyout "${cert_dir}/agent.key" \
    -out "${cert_dir}/agent.csr" >/dev/null 2>&1
  printf '%s\n' 'extendedKeyUsage=clientAuth' >"${cert_dir}/agent.ext"
  openssl x509 -req -in "${cert_dir}/agent.csr" -CA "${cert_dir}/ca.crt" \
    -CAkey "${cert_dir}/ca.key" -CAserial "${cert_dir}/ca.srl" -days 365 -sha256 \
    -extfile "${cert_dir}/agent.ext" -out "${cert_dir}/agent.crt" >/dev/null 2>&1
  chmod 0600 "${cert_dir}"/*
}

case "${action}" in
  certs) make_certs ;;
  install)
    require_command gcloud
    make_certs
    for host in "${CONTROLLER_NAME}" "${COMPUTE_NAMES[@]}"; do
      instance_running "${host}" || die "${host} is stopped; start lab hosts first"
      if [[ "${host}" == "${CONTROLLER_NAME}" ]]; then
        role=controller
        template="${ROOT}/observability/host-collector.yaml.tpl"
        for name in ca.crt gateway.crt gateway.key; do
          copy_to "${cert_dir}/${name}" "${host}" "/tmp/osk8s-${name}"
        done
        for name in openstack-inventory.py openstack-inventory.service openstack-inventory.timer; do
          copy_to "${ROOT}/observability/${name}" "${host}" "/tmp/osk8s-${name}"
        done
      else
        role=compute
        template="${ROOT}/observability/compute-collector.yaml.tpl"
      fi
      ensure_state_dirs
      rendered="${GENERATED_DIR}/otel-${role}.yaml"
      python3 "${ROOT}/scripts/render-template.py" "${template}" "${rendered}"
      copy_to "${rendered}" "${host}" /tmp/osk8s-otel-config.yaml
      copy_to "${ROOT}/observability/host-install.sh" "${host}" /tmp/osk8s-host-install.sh
      run_on "${host}" sudo bash /tmp/osk8s-host-install.sh \
        "${role}" "${GCP_PROJECT_ID}" "${GCP_ZONE}" "${ENV}"
    done
    ;;
  status)
    for host in "${CONTROLLER_NAME}" "${COMPUTE_NAMES[@]}"; do
      if instance_running "${host}"; then
        run_on "${host}" sudo systemctl --no-pager status osk8s-otel-collector.service || true
      else
        warn "${host} stopped: no live collector"
      fi
    done
    ;;
  *) die "usage: observability/deploy-hosts.sh {certs|install|status}" ;;
esac
