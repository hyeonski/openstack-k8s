SHELL := /bin/bash
.DEFAULT_GOAL := help
override ENV := cloud-gcp-amd64
export PROJECT_ROOT := $(CURDIR)
export ENV

# Infrastructure -> scenarios. Telemetry and repeated evaluation are opt-in commands.
include make/infrastructure.mk
include experiments/commands.mk
include observability/commands.mk
include evaluation/commands.mk

.PHONY: help help-experiments help-observability help-evaluation lab-start lab-status lab-stop experiment experiment-foundation

help:
	@echo "OpenStack + Kubernetes testbed"
	@echo ""
	@echo "Start here: README.md (code map and first deployment)"
	@echo "Choose ENV_OVERRIDE_FILE for your existing deployment before running commands."
	@echo ""
	@echo "  make lab-up CONFIRM=<environment>  First deployment; see README prerequisites"
	@echo "  make lab-start                    Start/recover the existing testbed"
	@echo "  make lab-status                   Inspect hosts and recorded environment state"
	@echo "  make experiment SCENARIO=s1       Run a scenario; s1, s2, s3, s4"
	@echo "  make lab-stop                     Stop only hosts started by this environment run"
	@echo "  make lint                         Offline checks"
	@echo ""
	@echo "  make help-experiments             Scenario prerequisites, status and cleanup"
	@echo "  make help-observability           Optional continuous telemetry"
	@echo "  make help-evaluation              Optional frozen repeat/comparison campaign"
	@echo "  make help-all                     Low-level infrastructure and diagnostic commands"

lab-start: graduation-env-ensure
lab-status: graduation-env-status
lab-stop: graduation-env-down

experiment:
	@bash experiments/run.sh "$(SCENARIO)" "$(or $(ACTION),run)"

experiment-foundation:
	@$(MAKE) --no-print-directory graduation-foundation
	@$(MAKE) --no-print-directory graduation-csi

help-experiments:
	@echo "Start with make lab-start. S2/S3 additionally need make experiment-foundation once."
	@echo "  make experiment SCENARIO=s1|s2|s3|s4 [ACTION=run|status|cleanup]"
	@echo "  make experiment SCENARIO=s4 ACTION=resume"
	@echo "Runs include fixture preparation where needed and cleanup after success."
	@echo "On failure, evidence and ownership records remain: inspect status, then cleanup/resume."
	@echo "The environment stays running. lab-stop refuses unfinished experiments."
	@echo "S1 runs automatic relocation; baseline/manual comparison commands: make help-all."
	@echo "Code: experiments/; procedure: docs/graduation/experiments.md"

help-observability:
	@echo "Optional OTel + Cloud Monitoring/Logging + GCS; not required for scenario decisions."
	@echo "Setup changes IAM/storage and host identity: follow observability/README.md."
	@echo "  make observability-gcp-status"
	@echo "  make observability-hosts-status observability-clusters-status"
	@echo "  make observability-verify"
	@echo "Local experiment evidence is retained even without cloud telemetry."

help-evaluation:
	@echo "Optional fixed-profile repeat/comparison/negative tests; separate from a single experiment."
	@echo "Read docs/graduation/final-evaluation.md and config/graduation-evaluation.json first."
	@echo "  make graduation-evaluation-freeze"
	@echo "  make graduation-evaluation-status CAMPAIGN=<absolute-path>"
	@echo "  make graduation-evaluation-run CAMPAIGN=<absolute-path>"
	@echo "  make graduation-evaluation-verify CAMPAIGN=<absolute-path>"
	@echo "Code: evaluation/. Existing frozen campaigns retain their original code hashes."
	@echo "Fresh F-repeated: make graduation-fresh-schedule (offline; main29 + preparation8)."
	@echo "Read docs/graduation/fresh-evaluation-implementation.md; draft parameters block live freeze."
