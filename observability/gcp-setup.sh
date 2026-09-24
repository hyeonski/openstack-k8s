#!/usr/bin/env bash
# Create the independent GCP telemetry destination for this lab.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${ROOT}/scripts/lib/common.sh"

service_account="osk8s-telemetry@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
log_bucket="osk8s-observability"
log_sink="osk8s-observability"
evidence_bucket="gs://osk8s-$(gcloud projects describe "${GCP_PROJECT_ID}" --format='value(projectNumber)')-evidence"

require_command gcloud
case "${1:-}" in
  status)
    gcloud iam service-accounts describe "${service_account}" --project="${GCP_PROJECT_ID}" --format='value(email)' || true
    gcloud logging buckets describe "${log_bucket}" --project="${GCP_PROJECT_ID}" --location="${GCP_REGION}" --format='yaml(name,retentionDays)' || true
    gcloud logging sinks describe "${log_sink}" --project="${GCP_PROJECT_ID}" --format='yaml(destination,filter)' || true
    gcloud logging sinks describe _Default --project="${GCP_PROJECT_ID}" --format='yaml(exclusions)' || true
    gcloud storage buckets describe "${evidence_bucket}" --format='yaml(name,location,lifecycle)' || true
    ;;
  apply)
    [[ "${2:-}" == "${ENV}" ]] || die "pass CONFIRM=${ENV}"
    # Check all durable host changes before creating any resources.
    for host in "${CONTROLLER_NAME}" "${COMPUTE_NAMES[@]}"; do
      status="$(gcloud compute instances describe "${host}" --project="${GCP_PROJECT_ID}" \
        --zone="${GCP_ZONE}" --format='value(status)')"
      [[ "${status}" == TERMINATED ]] || die "${host} must be stopped (status=${status})"
      current="$(gcloud compute instances describe "${host}" --project="${GCP_PROJECT_ID}" \
        --zone="${GCP_ZONE}" --format='value(serviceAccounts[0].email)')"
      [[ -z "${current}" || "${current}" == "${service_account}" ]] ||
        die "${host} has another service account; refusing to replace it"
    done
    for api in logging.googleapis.com monitoring.googleapis.com telemetry.googleapis.com iam.googleapis.com storage.googleapis.com; do
      gcloud services enable "${api}" --project="${GCP_PROJECT_ID}" --quiet
    done
    if ! gcloud iam service-accounts describe "${service_account}" --project="${GCP_PROJECT_ID}" >/dev/null 2>&1; then
      gcloud iam service-accounts create osk8s-telemetry --project="${GCP_PROJECT_ID}" \
        --display-name='OpenStack Kubernetes observability writer'
    fi
    for role in roles/logging.logWriter roles/monitoring.metricWriter; do
      gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
        --member="serviceAccount:${service_account}" --role="${role}" --condition=None --quiet >/dev/null
    done
    if ! gcloud logging buckets describe "${log_bucket}" --project="${GCP_PROJECT_ID}" --location="${GCP_REGION}" >/dev/null 2>&1; then
      gcloud logging buckets create "${log_bucket}" --project="${GCP_PROJECT_ID}" \
        --location="${GCP_REGION}" --retention-days=30 \
        --description='Graduation-project infrastructure telemetry; 30-day searchable logs'
    fi
    if ! gcloud logging sinks describe "${log_sink}" --project="${GCP_PROJECT_ID}" >/dev/null 2>&1; then
      gcloud logging sinks create "${log_sink}" \
        "logging.googleapis.com/projects/${GCP_PROJECT_ID}/locations/${GCP_REGION}/buckets/${log_bucket}" \
        --project="${GCP_PROJECT_ID}" --log-filter='log_id("osk8s-otel")'
    fi
    if ! gcloud storage buckets describe "${evidence_bucket}" >/dev/null 2>&1; then
      gcloud storage buckets create "${evidence_bucket}" --project="${GCP_PROJECT_ID}" \
        --location="${GCP_REGION}" --uniform-bucket-level-access \
        --default-storage-class=STANDARD --public-access-prevention
    fi
    gcloud storage buckets add-iam-policy-binding "${evidence_bucket}" \
      --member="serviceAccount:${service_account}" --role=roles/storage.objectCreator >/dev/null
    for host in "${CONTROLLER_NAME}" "${COMPUTE_NAMES[@]}"; do
      current="$(gcloud compute instances describe "${host}" --project="${GCP_PROJECT_ID}" \
        --zone="${GCP_ZONE}" --format='value(serviceAccounts[0].email)')"
      if [[ "${current}" != "${service_account}" ]]; then
        gcloud compute instances set-service-account "${host}" --project="${GCP_PROJECT_ID}" \
          --zone="${GCP_ZONE}" --service-account="${service_account}" \
          --scopes=cloud-platform --quiet
      fi
    done
    log "GCP telemetry destination and writer identity are configured; hosts remain stopped"
    ;;
  dedupe)
    [[ "${2:-}" == "${ENV}" ]] || die "pass CONFIRM=${ENV}"
    gcloud logging sinks describe "${log_sink}" --project="${GCP_PROJECT_ID}" >/dev/null
    if gcloud logging sinks describe _Default --project="${GCP_PROJECT_ID}" --format=json |
      python3 -c 'import json,sys; sys.exit(not any(x.get("name") == "osk8s-otel-dedup" for x in json.load(sys.stdin).get("exclusions", [])))'; then
      log "_Default already excludes osk8s-otel"
    else
      gcloud logging sinks update _Default --project="${GCP_PROJECT_ID}" \
        --add-exclusion='name=osk8s-otel-dedup,description=Dedicated Seoul observability bucket,filter=log_id("osk8s-otel")'
      log "_Default now excludes osk8s-otel; dedicated bucket still receives it"
    fi
    ;;
  *) die "usage: observability/gcp-setup.sh {status|apply|dedupe CONFIRM}" ;;
esac
