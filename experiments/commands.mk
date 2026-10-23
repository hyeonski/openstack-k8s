# Detailed commands; use root `make help` for the normal workflow.
.PHONY: graduation-s4-prepare graduation-s4-verify graduation-s4-cleanup graduation-s4-status graduation-s4-run graduation-s4-e2e graduation-s4-inject graduation-s4-observe graduation-s4-analyze graduation-s4-run-status graduation-s4-workflow-status graduation-s4-resume graduation-s1-prepare graduation-s1-verify graduation-s1-baseline graduation-s1-cleanup graduation-s1-status graduation-s1-contention graduation-s1-contention-cleanup graduation-s1-contention-status graduation-s1-auto graduation-s1-spread graduation-s1-auto-cleanup graduation-s1-auto-status graduation-foundation graduation-csi graduation-s2 graduation-s2-cleanup graduation-s3 graduation-s3-cleanup

graduation-s4-prepare:
	@bash experiments/graduation-s4.sh prepare

graduation-s4-verify:
	@bash experiments/graduation-s4.sh verify

graduation-s4-cleanup:
	@bash experiments/graduation-s4.sh cleanup

graduation-s4-status:
	@bash experiments/graduation-s4.sh status

graduation-s4-run:
	@bash experiments/graduation-s4-workflow.sh scenario

graduation-s4-e2e:
	@bash experiments/graduation-s4-workflow.sh e2e

graduation-s4-inject:
	@bash experiments/graduation-s4-run.sh run

graduation-s4-observe:
	@bash experiments/graduation-s4-run.sh observe

graduation-s4-analyze:
	@bash experiments/graduation-s4-analyze.sh

graduation-s4-run-status:
	@bash experiments/graduation-s4-run.sh status

graduation-s4-workflow-status:
	@bash experiments/graduation-s4-workflow.sh status

graduation-s4-resume:
	@bash experiments/graduation-s4-workflow.sh resume

graduation-s1-prepare:
	@bash experiments/graduation-s1.sh prepare

graduation-s1-verify:
	@bash experiments/graduation-s1.sh verify

graduation-s1-baseline:
	@bash experiments/graduation-s1.sh baseline --rate "$(or $(RATE),5)" --rounds "$(or $(ROUNDS),100000)" --warmup "$(or $(WARMUP),60)" --measure "$(or $(MEASURE),300)"

graduation-s1-cleanup:
	@bash experiments/graduation-s1.sh cleanup

graduation-s1-status:
	@bash experiments/graduation-s1.sh status

graduation-s1-contention:
	@bash experiments/graduation-s1-contention.sh run --rate "$(or $(RATE),5)" --rounds "$(or $(ROUNDS),100000)" --seconds "$(or $(SECONDS),780)"

graduation-s1-contention-cleanup:
	@bash experiments/graduation-s1-contention.sh cleanup

graduation-s1-contention-status:
	@bash experiments/graduation-s1-contention.sh status

graduation-s1-auto:
	@bash experiments/graduation-s1-auto.sh run --seconds "$(or $(SECONDS),1080)"

graduation-s1-spread:
	@bash experiments/graduation-s1-spread.sh

graduation-s1-auto-cleanup:
	@bash experiments/graduation-s1-auto.sh cleanup

graduation-s1-auto-status:
	@bash experiments/graduation-s1-auto.sh status

graduation-foundation:
	@bash experiments/graduation-foundation.sh apply

graduation-csi:
	@bash experiments/graduation-csi.sh

graduation-s2:
	@bash experiments/graduation-s2.sh run

graduation-s2-cleanup:
	@bash experiments/graduation-s2.sh cleanup

graduation-s3:
	@bash experiments/graduation-s3.sh run

graduation-s3-cleanup:
	@bash experiments/graduation-s3.sh cleanup

.PHONY: graduation-s2-status graduation-s3-status
graduation-s2-status:
	@bash experiments/graduation-s2.sh status

graduation-s3-status:
	@bash experiments/graduation-s3.sh status
