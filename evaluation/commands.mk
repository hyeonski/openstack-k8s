# Detailed commands; use root `make help` for the normal workflow.
.PHONY: graduation-evaluation-freeze graduation-evaluation-run graduation-evaluation-status graduation-evaluation-verify

graduation-evaluation-freeze:
	@bash evaluation/graduation-evaluation.sh freeze

graduation-evaluation-run:
	@bash evaluation/graduation-evaluation.sh run --campaign "$(CAMPAIGN)"

graduation-evaluation-status:
	@bash evaluation/graduation-evaluation.sh status --campaign "$(CAMPAIGN)"

graduation-evaluation-verify:
	@python3 evaluation/graduation_evaluation_verify.py "$(CAMPAIGN)"
