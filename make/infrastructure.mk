# Detailed commands; use root `make help` for the normal workflow.
.PHONY: help-all bootstrap-preflight preflight gcp-bootstrap gcp-iac-init gcp-iac-validate gcp-iac-import gcp-iac-plan gcp-iac-show-plan gcp-foundation-plan gcp-foundation-show-plan gcp-foundation-apply gcp-iac-apply gcp-floating-ip-route-plan gcp-floating-ip-route-show-plan gcp-floating-ip-route-apply gcp-status gcp-start gcp-stop gcp-host-verify gcp-wait-ssh gcp-openstack-recover gcp-deployment-key-setup gcp-sync-inputs gcp-controller-management-prepare secrets-check inventory host-prepare kolla-sync openstack-precheck openstack-pull openstack-deploy openstack-validate openstack-post-deploy openstack-bootstrap openstack-verify openstack-verification-cleanup kubernetes-image-builder-create kubernetes-image-builder-destroy kubernetes-image-build kubernetes-image-upload kubernetes-image-verify kubernetes-image management-cluster-create management-cluster-verify management-cluster-destroy capi-providers-install capi-providers-verify capi-credentials-verify workload-cluster-create workload-cluster-prepare workload-cluster-status workload-cluster-probe workload-cluster-verify workload-cluster-scale workload-cluster-diagnostics workload-cluster-destroy cluster-autoscaler-install cluster-autoscaler-verify cluster-autoscaler-test cluster-autoscaler-test-status cluster-autoscaler-test-cancel cluster-autoscaler-test-reconcile cluster-autoscaler-test-resume cluster-autoscaler-test-cleanup cluster-autoscaler-mode cluster-autoscaler-control-status cluster-autoscaler-control-recover cluster-autoscaler-diagnostics lab-up graduation-env-status graduation-env-ensure graduation-env-reconcile graduation-env-down status lint

help-all:
	@echo "  cluster-autoscaler-test-{status,cancel,reconcile,resume}  Experiment lifecycle (mutations require RUN_ID)"
	@echo "OpenStack/Kubernetes testbed automation"
	@echo
	@echo "Usage: make <target>"
	@echo
	@echo "GCP host lifecycle:"
	@echo "  bootstrap-preflight    Check auth and local tools without requiring infrastructure"
	@echo "  preflight              Read-only checks for an existing GCP foundation"
	@echo "  secrets-check          Validate local secret permissions and Git ignores"
	@echo "  status                 Show GCP instance and project state"
	@echo "  gcp-status             Show exact GCP host state and runtime limit"
	@echo "  gcp-start              Start only the declared GCP hosts"
	@echo "  gcp-stop               Stop only the declared GCP hosts"
	@echo "  gcp-host-verify        Run the GCP host readiness gate"
	@echo "  gcp-openstack-recover  Recover OpenStack services after GCP host restart"
	@echo "  gcp-deployment-key-setup Install the project key for controller-to-compute SSH"
	@echo "  gcp-sync-inputs        Sync deployment code without installing Kolla"
	@echo "  gcp-controller-management-prepare Move the private kind API gate to the controller"
	@echo
	@echo "GCP infrastructure:"
	@echo "  gcp-bootstrap          Enable required APIs in an existing billed project"
	@echo "  gcp-iac-init           Initialize OpenTofu/Terraform providers"
	@echo "  gcp-iac-validate       Validate the GCP declaration"
	@echo "  gcp-iac-import         Import existing resources without changing GCP"
	@echo "  gcp-iac-plan           Save and classify the adoption plan"
	@echo "  gcp-iac-show-plan      Display the saved adoption plan"
	@echo "  gcp-foundation-plan    Plan only safe greenfield foundation creates"
	@echo "  gcp-foundation-apply   Apply the saved foundation plan (CONFIRM=$(ENV))"
	@echo "  gcp-floating-ip-route-plan  Plan the post-host Floating IP route"
	@echo "  gcp-floating-ip-route-apply Apply the isolated route (CONFIRM=$(ENV))"
	@echo "  lab-up                 Deploy the full testbed (CONFIRM=$(ENV))"
	@echo
	@echo "OpenStack deployment:"
	@echo "  inventory              Generate the current Ansible/Kolla inventory"
	@echo "  host-prepare           Prepare Ubuntu hosts, swap and external veth/NAT"
	@echo "  kolla-sync             Sync deployment inputs to the controller"
	@echo "  openstack-precheck     Run Kolla bootstrap and prechecks"
	@echo "  openstack-pull         Cache required OpenStack images on both hosts"
	@echo "  openstack-deploy       Deploy OpenStack with Kolla-Ansible"
	@echo "  openstack-validate     Validate rendered service configurations"
	@echo "  openstack-post-deploy  Generate admin credentials"
	@echo "  openstack-bootstrap    Create networks, images and CAPO project credentials"
	@echo "  openstack-verify       Run CirrOS, Ubuntu and CAPO-network preflight"
	@echo "  openstack-verification-cleanup  Remove a preserved verification VM and Floating IP"
	@echo
	@echo "Kubernetes node image:"
	@echo "  kubernetes-image-builder-create  Create the isolated GCP AMD64 image builder"
	@echo "  kubernetes-image-build           Build and checksum the Kubernetes QCOW2"
	@echo "  kubernetes-image-builder-destroy Delete only the image builder (CONFIRM=$(ENV))"
	@echo "  kubernetes-image-upload          Upload the pinned image to Glance"
	@echo "  kubernetes-image-verify          Boot and verify the image with Nova"
	@echo "  kubernetes-image                 Upload and verify an existing built image"
	@echo
	@echo "Management cluster:"
	@echo "  management-cluster-create  Create and verify the pinned single-node kind cluster"
	@echo "  management-cluster-verify  Verify Ready state and the in-cluster OpenStack API path"
	@echo "  management-cluster-destroy Delete only the kind cluster (CONFIRM=$(ENV))"
	@echo
	@echo "CAPI/CAPO workload cluster:"
	@echo "  capi-providers-install    Install pinned CAPI, kubeadm, CAPO and ORC providers"
	@echo "  capi-providers-verify     Verify provider versions and controller readiness"
	@echo "  capi-credentials-verify   Verify the application credential from a kind Pod"
	@echo "  workload-cluster-create   Create and verify one control plane and one worker"
	@echo "  workload-cluster-prepare  Explicitly apply intended Calico probe settings"
	@echo "  workload-cluster-status   One read-only observation (WORKERS=1)"
	@echo "  workload-cluster-probe    Run owned API and per-node CNI/DNS probes"
	@echo "  workload-cluster-verify   Read-only convergence check (WORKERS=1)"
	@echo "  workload-cluster-scale    Manually scale workers within 1:3"
	@echo "  workload-cluster-diagnostics Collect CAPI/Nova/bootstrap/compute diagnostics"
	@echo "  workload-cluster-destroy  Delete exact workload Cluster (two confirmations)"
	@echo
	@echo "M3 Cluster Autoscaler:"
	@echo "  cluster-autoscaler-install     Install pinned CA and dual-cluster RBAC"
	@echo "  cluster-autoscaler-verify      Verify image, arguments, access and min/max"
	@echo "  cluster-autoscaler-test        Run automatic 1-2-3-2-1-2-1 requests test"
	@echo "  cluster-autoscaler-test-cleanup Preserve evidence, remove owned test resources"
	@echo "  cluster-autoscaler-mode        Set MODE=auto or MODE=fixed for worker control"
	@echo "  cluster-autoscaler-control-status Show recorded and actual worker control state"
	@echo "  cluster-autoscaler-control-recover Reconcile an interrupted worker operation"
	@echo "  cluster-autoscaler-diagnostics Preserve redacted M3 failure evidence"
	@echo
	@echo "Observability (1-4):"
	@echo "  observability-gcp-status       Inspect independent telemetry storage and identity"
	@echo "  observability-gcp-setup        Create storage/identity while hosts are stopped (CONFIRM=$(ENV))"
	@echo "  observability-gcp-dedupe       Exclude dedicated telemetry logs from _Default (CONFIRM=$(ENV))"
	@echo "  observability-workload-guests-start Start current CAPI VMs left SHUTOFF after GCE boot"
	@echo "  observability-hosts-install   Install GCE host collectors and Nova inventory timer"
	@echo "  observability-clusters-install Install collectors in management and workload clusters"
	@echo "  observability-verify          Query recent GCP metrics/logs for missing data"
	@echo "  observability-publish-run     Publish RUN_DIR correlation manifest to GCS"
	@echo
	@echo "Graduation experiments:"
	@echo "  graduation-env-status   Inspect exact existing GCP hosts and last environment record"
	@echo "  graduation-env-ensure   Verify the existing testbed; start only stopped hosts and guests"
	@echo "  graduation-env-reconcile Recheck exact hosts after an interrupted preparation"
	@echo "  graduation-env-down    Stop only hosts started by this environment run"
	@echo "  graduation-s4-prepare  Fix two workers; apply worker MHC and HTTP test service"
	@echo "  graduation-s4-verify   Recheck MHC scope, Pod placement and HTTP responses"
	@echo "  graduation-s4-cleanup  Remove owned S4 resources and restore worker control"
	@echo "  graduation-s4-status   Show locally recorded S4 preparation state"
	@echo "  graduation-s4-run      Prepare, inject, analyze and clean S4 on an already Ready environment"
	@echo "  graduation-s4-e2e      Ensure existing environment, run S4, then stop only owned GCP hosts"
	@echo "  graduation-s4-inject   Low-level exact Nova worker stop and service/capacity observation"
	@echo "  graduation-s4-observe  Continue observation after interruption without stopping a VM again"
	@echo "  graduation-s4-analyze  Rebuild JSON/CSV/report table from immutable S4 run evidence"
	@echo "  graduation-s4-run-status Show locally recorded S4 experiment state"
	@echo "  graduation-s4-workflow-status Show the composite S4 workflow state"
	@echo "  graduation-s4-resume Resume an interrupted S4 workflow without another VM stop"
	@echo "  graduation-s1-prepare Fix two workers and create the S1 CPU HTTP service"
	@echo "  graduation-s1-verify Recheck the S1 service and Pod-to-Nova identity"
	@echo "  graduation-s1-baseline Run a direct Service baseline from the workload control plane"
	@echo "  graduation-s1-contention Run S1 same-compute CPU contention and manual Pod relocation"
	@echo "  graduation-s1-auto Detect sustained contention and relocate to an eligible worker"
	@echo "  graduation-s1-spread Place a new empty test worker on the alternate compute"
	@echo "  graduation-foundation Enable Neutron QoS and dedicated Cinder lab storage"
	@echo "  graduation-csi Install the pinned Cinder CSI driver and StorageClass"
	@echo "  graduation-s2 Compare shared egress contention, fixed and adaptive QoS"
	@echo "  graduation-s3 Fence a disconnected worker and recover the same PostgreSQL volume"
	@echo "  graduation-s1-contention-cleanup Remove a leftover S1 competitor VM and load Job"
	@echo "  graduation-s1-cleanup Remove S1 resources and restore worker control"
	@echo "  graduation-s1-status Show the local S1 preparation record"
	@echo
	@echo "Development:"
	@echo "  lint                    Static checks that do not mutate the host"

bootstrap-preflight:
	@scripts/gcp-preflight.sh bootstrap

preflight:
	@scripts/gcp-preflight.sh

gcp-bootstrap:
	@scripts/gcp-project-bootstrap.sh "$(CONFIRM)"

gcp-iac-init:
	@scripts/gcp-iac.sh init

gcp-iac-validate:
	@scripts/gcp-iac.sh validate

gcp-iac-import:
	@scripts/gcp-iac.sh import

gcp-iac-plan:
	@scripts/gcp-iac.sh plan

gcp-iac-show-plan:
	@scripts/gcp-iac.sh show-plan

gcp-foundation-plan:
	@scripts/gcp-iac.sh foundation-plan

gcp-foundation-show-plan:
	@scripts/gcp-iac.sh foundation-show-plan

gcp-foundation-apply:
	@scripts/gcp-iac.sh foundation-apply "$(CONFIRM)"

gcp-iac-apply: gcp-foundation-apply

gcp-floating-ip-route-plan:
	@scripts/gcp-iac.sh route-plan

gcp-floating-ip-route-show-plan:
	@scripts/gcp-iac.sh route-show-plan

gcp-floating-ip-route-apply:
	@scripts/gcp-iac.sh route-apply "$(CONFIRM)"

gcp-status:
	@scripts/gcp-hosts.sh status

gcp-start:
	@scripts/gcp-hosts.sh start

gcp-stop:
	@scripts/gcp-hosts.sh stop

gcp-host-verify:
	@scripts/gcp-hosts.sh verify

gcp-wait-ssh:
	@scripts/gcp-hosts.sh wait-ssh

gcp-openstack-recover:
	@scripts/gcp-openstack-recover.sh

gcp-deployment-key-setup:
	@scripts/setup-project-ssh.sh

gcp-sync-inputs: inventory
	@scripts/sync-to-controller.sh inputs-only

gcp-controller-management-prepare:
	@scripts/gcp-iac.sh controller-management

secrets-check:
	@scripts/secrets-check.sh

inventory:
	@scripts/generate-inventory.sh

host-prepare: kolla-sync
	@scripts/run-controller.sh prepare-hosts

kolla-sync: inventory
	@scripts/sync-to-controller.sh

openstack-precheck: kolla-sync
	@scripts/configure-kolla.sh
	@scripts/run-kolla.sh bootstrap-servers
	@scripts/run-kolla.sh prechecks

openstack-pull: kolla-sync
	@scripts/configure-kolla.sh
	@scripts/run-kolla.sh pull

openstack-deploy: kolla-sync
	@scripts/configure-kolla.sh
	@scripts/run-kolla.sh deploy

openstack-validate:
	@scripts/configure-kolla.sh
	@scripts/run-kolla.sh validate-config

openstack-post-deploy:
	@scripts/run-kolla.sh post-deploy
	@scripts/fetch-admin-clouds.sh

openstack-bootstrap:
	@scripts/bootstrap-openstack.sh

openstack-verify:
	@scripts/openstack-verify.sh

openstack-verification-cleanup:
	@scripts/openstack-verify.sh cleanup

kubernetes-image-builder-create:
	@scripts/gcp-image-builder.sh create

kubernetes-image-builder-destroy:
	@scripts/gcp-image-builder.sh delete "$(CONFIRM)"

kubernetes-image-build:
	@scripts/build-kubernetes-image.sh

kubernetes-image-upload:
	@scripts/upload-kubernetes-image.sh

kubernetes-image-verify:
	@scripts/verify-kubernetes-image.sh

kubernetes-image: kubernetes-image-upload kubernetes-image-verify

management-cluster-create:
	@scripts/gcp-management-cluster.sh create

management-cluster-verify:
	@scripts/gcp-management-cluster.sh verify

management-cluster-destroy:
	@scripts/gcp-management-cluster.sh destroy "$(CONFIRM)"

capi-providers-install:
	@scripts/capi-providers.sh install

capi-providers-verify:
	@scripts/capi-providers.sh verify

capi-credentials-verify:
	@scripts/capi-providers.sh credentials

workload-cluster-create:
	@scripts/workload-cluster.sh create

workload-cluster-prepare:
	@scripts/workload-cluster.sh prepare

workload-cluster-status:
	@scripts/workload-cluster.sh status "$(or $(WORKERS),1)"

workload-cluster-probe:
	@scripts/workload-cluster.sh probe

workload-cluster-verify:
	@scripts/workload-cluster.sh verify "$(or $(WORKERS),1)"

workload-cluster-scale:
	@scripts/workload-cluster.sh scale "$(or $(WORKERS),2)"

workload-cluster-diagnostics:
	@scripts/workload-cluster.sh diagnostics

workload-cluster-destroy:
	@scripts/workload-cluster.sh destroy "$(CONFIRM)" "$(CONFIRM_CLUSTER)"

cluster-autoscaler-install:
	@scripts/cluster-autoscaler.sh install

cluster-autoscaler-verify:
	@scripts/cluster-autoscaler.sh verify

cluster-autoscaler-test:
	@scripts/cluster-autoscaler.sh test

cluster-autoscaler-test-status cluster-autoscaler-test-cancel cluster-autoscaler-test-reconcile cluster-autoscaler-test-resume:
	@scripts/cluster-autoscaler.sh $(patsubst cluster-autoscaler-%,%,$@)

cluster-autoscaler-test-cleanup:
	@scripts/cluster-autoscaler.sh test-cleanup

cluster-autoscaler-mode:
	@scripts/cluster-autoscaler.sh mode "$(MODE)"

cluster-autoscaler-control-status:
	@scripts/cluster-autoscaler.sh control-status

cluster-autoscaler-control-recover:
	@scripts/cluster-autoscaler.sh control-recover

cluster-autoscaler-diagnostics:
	@scripts/cluster-autoscaler.sh diagnostics

lab-up:
	@scripts/lab-up.sh "$(CONFIRM)"

graduation-env-status:
	@bash scripts/graduation-env.sh status

graduation-env-ensure:
	@bash scripts/graduation-env.sh ensure

graduation-env-reconcile:
	@bash scripts/graduation-env.sh reconcile

graduation-env-down:
	@bash scripts/graduation-env.sh down

status:
	@scripts/status.sh

lint:
	@scripts/lint.sh
