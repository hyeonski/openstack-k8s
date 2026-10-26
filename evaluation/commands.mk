# Detailed commands; use root `make help` for the normal workflow.
.PHONY: graduation-evaluation-freeze graduation-evaluation-run graduation-evaluation-status graduation-evaluation-verify

graduation-evaluation-freeze:
	@bash evaluation/graduation-evaluation.sh freeze

graduation-evaluation-run:
	@bash evaluation/graduation-evaluation.sh run --campaign "$(CAMPAIGN)"

graduation-evaluation-status:
	@bash evaluation/graduation-evaluation.sh status --campaign "$(CAMPAIGN)"

graduation-evaluation-verify:
	@python3 evaluation/graduation_evaluation_verify.py "$(CAMPAIGN)" $(if $(filter 1,$(PARTIAL)),--partial,)

# Fresh commands keep the historical profile on its original entry point.
.PHONY: graduation-fresh-schedule graduation-fresh-validate graduation-fresh-freeze graduation-fresh-run graduation-fresh-report graduation-fresh-status graduation-fresh-resume-cleanup
FRESH_PROFILE ?= config/graduation-evaluation-fresh.json
FRESH_STAGE ?= preparation

graduation-fresh-schedule:
	@python3 evaluation/fresh_campaign.py schedule --profile "$(FRESH_PROFILE)"

graduation-fresh-validate:
	@python3 evaluation/fresh_campaign.py validate --profile "$(FRESH_PROFILE)"

graduation-fresh-freeze:
	@bash evaluation/graduation-evaluation.sh --fresh freeze --profile "$(FRESH_PROFILE)" --stage "$(FRESH_STAGE)" --campaign "$(CAMPAIGN)" $(if $(SCENARIO),--scenario "$(SCENARIO)",) $(if $(POLICY_MANIFEST),--policy-manifest "$(POLICY_MANIFEST)",) $(if $(PILOT_CAMPAIGN),--pilot-campaign "$(PILOT_CAMPAIGN)",) $(if $(PREVIOUS_CAMPAIGN),--previous-campaign "$(PREVIOUS_CAMPAIGN)",)

graduation-fresh-run:
	@bash evaluation/graduation-evaluation.sh --fresh run --campaign "$(CAMPAIGN)" $(if $(LIMIT),--limit "$(LIMIT)",) $(if $(CASE),--case "$(CASE)",)

graduation-fresh-resume-cleanup:
	@bash evaluation/graduation-evaluation.sh --fresh resume-cleanup --campaign "$(CAMPAIGN)" --case "$(CASE)"

graduation-fresh-report:
	@python3 evaluation/fresh_campaign.py report --campaign "$(CAMPAIGN)"

graduation-fresh-status:
	@python3 evaluation/fresh_campaign.py status --campaign "$(CAMPAIGN)"
