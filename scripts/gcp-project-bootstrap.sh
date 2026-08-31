#!/usr/bin/env bash

set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

confirmation="${1:-}"
[[ "${confirmation}" == "${ENV}" ]] ||
  die "refusing GCP API bootstrap; pass CONFIRM=${ENV}"

require_command gcloud
gcloud projects describe "${GCP_PROJECT_ID}" --format='value(projectId)' |
  grep -qx "${GCP_PROJECT_ID}" || die "create or select GCP project ${GCP_PROJECT_ID} first"

billing_enabled="$(gcloud billing projects describe "${GCP_PROJECT_ID}" \
  --format='value(billingEnabled)' 2>/dev/null || true)"
[[ "${billing_enabled}" == "True" || "${billing_enabled}" == "true" ]] ||
  die "billing is not enabled or cannot be verified for ${GCP_PROJECT_ID}"

services=(
  compute.googleapis.com
  iap.googleapis.com
  oslogin.googleapis.com
  serviceusage.googleapis.com
)
gcloud services enable "${services[@]}" --project="${GCP_PROJECT_ID}" --quiet

gcloud compute images describe "${GCP_SOURCE_IMAGE_NAME}" \
  --project="${GCP_SOURCE_IMAGE_PROJECT}" --format='value(status)' |
  grep -qx READY || die "source image is not ready: ${GCP_SOURCE_IMAGE_NAME}"
gcloud compute machine-types describe e2-standard-4 \
  --project="${GCP_PROJECT_ID}" --zone="${GCP_ZONE}" --format='value(name)' |
  grep -qx e2-standard-4 || die "e2-standard-4 is unavailable in ${GCP_ZONE}"
gcloud compute machine-types describe n2-standard-4 \
  --project="${GCP_PROJECT_ID}" --zone="${GCP_ZONE}" --format='value(name)' |
  grep -qx n2-standard-4 || die "n2-standard-4 is unavailable in ${GCP_ZONE}"

log "Required GCP APIs, source image, and machine types are ready"
