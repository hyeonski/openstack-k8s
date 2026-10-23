# Detailed commands; use root `make help` for the normal workflow.
.PHONY: observability-gcp-status observability-gcp-setup observability-gcp-dedupe observability-hosts-install observability-workload-guests-start observability-hosts-status observability-clusters-install observability-clusters-status observability-verify observability-publish-run

observability-gcp-status:
	@observability/gcp-setup.sh status

observability-gcp-setup:
	@observability/gcp-setup.sh apply "$(CONFIRM)"

observability-gcp-dedupe:
	@observability/gcp-setup.sh dedupe "$(CONFIRM)"

observability-hosts-install:
	@observability/deploy-hosts.sh install

observability-workload-guests-start:
	@scripts/start-workload-guests.sh

observability-hosts-status:
	@observability/deploy-hosts.sh status

observability-clusters-install:
	@observability/deploy-clusters.sh install

observability-clusters-status:
	@observability/deploy-clusters.sh status

observability-verify:
	@bash -c 'source scripts/lib/common.sh; observability/verify-live.py --project "$$GCP_PROJECT_ID" --region "$$GCP_REGION" --host-cluster "$${ENVIRONMENT_NAME}-hosts"'

observability-publish-run:
	@observability/publish-run.sh "$(RUN_DIR)"
