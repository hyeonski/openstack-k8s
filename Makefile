SHELL := /bin/bash
.DEFAULT_GOAL := help

override ENV := cloud-gcp-amd64

export PROJECT_ROOT := $(CURDIR)
export ENV

.PHONY: help bootstrap-preflight preflight secrets-check inventory host-prepare kolla-sync openstack-precheck \
	gcp-bootstrap gcp-iac-init gcp-iac-validate gcp-iac-import gcp-iac-plan gcp-iac-show-plan \
	gcp-iac-apply gcp-foundation-plan gcp-foundation-show-plan gcp-foundation-apply \
	gcp-floating-ip-route-plan gcp-floating-ip-route-show-plan gcp-floating-ip-route-apply \
	gcp-status gcp-start gcp-stop gcp-host-verify gcp-deployment-key-setup \
	gcp-wait-ssh gcp-sync-inputs gcp-controller-management-prepare lab-up \
	openstack-pull openstack-deploy openstack-validate \
	openstack-post-deploy openstack-bootstrap openstack-verify openstack-verification-cleanup \
	kubernetes-image-builder-create kubernetes-image-builder-destroy \
	kubernetes-image-build kubernetes-image-upload kubernetes-image-verify \
	kubernetes-image management-cluster-create management-cluster-verify \
	management-cluster-destroy capi-providers-install capi-providers-verify \
	capi-credentials-verify workload-cluster-create workload-cluster-verify \
	workload-cluster-scale \
	workload-cluster-diagnostics workload-cluster-destroy \
	cluster-autoscaler-install cluster-autoscaler-verify \
	cluster-autoscaler-test cluster-autoscaler-diagnostics \
	status lint

help:
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
	@echo "  workload-cluster-verify   Verify the current workload cluster (WORKERS=1)"
	@echo "  workload-cluster-scale    Manually scale the MachineDeployment from 1 to 2"
	@echo "  workload-cluster-diagnostics Collect CAPI/Nova/bootstrap/compute diagnostics"
	@echo "  workload-cluster-destroy  Delete exact workload Cluster (two confirmations)"
	@echo
	@echo "M3 Cluster Autoscaler:"
	@echo "  cluster-autoscaler-install     Install pinned CA and dual-cluster RBAC"
	@echo "  cluster-autoscaler-verify      Verify image, arguments, access and min/max"
	@echo "  cluster-autoscaler-test        Run Pending Pod based 1-to-2 scale-up"
	@echo "  cluster-autoscaler-diagnostics Preserve redacted M3 failure evidence"
	@echo
	@echo "Development:"
	@echo "  lint                    Static checks that do not mutate the host"

bootstrap-preflight:
	@scripts/gcp-bootstrap-preflight.sh

preflight:
	@scripts/preflight.sh

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
	@scripts/gcp-openstack-recover.sh

gcp-wait-ssh:
	@scripts/gcp-wait-ssh.sh

gcp-openstack-recover:
	@scripts/gcp-openstack-recover.sh

gcp-deployment-key-setup:
	@scripts/setup-project-ssh.sh

gcp-sync-inputs: inventory
	@scripts/sync-to-controller.sh inputs-only

gcp-controller-management-prepare:
	@scripts/gcp-controller-management-iac.sh

secrets-check:
	@scripts/secrets-check.sh

inventory:
	@scripts/generate-inventory.sh

host-prepare: kolla-sync
	@scripts/run-host-prepare.sh

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
	@scripts/openstack-verification-cleanup.sh

kubernetes-image-builder-create:
	@scripts/kubernetes-image-builder-create.sh

kubernetes-image-builder-destroy:
	@scripts/kubernetes-image-builder-destroy.sh "$(CONFIRM)"

kubernetes-image-build:
	@scripts/build-kubernetes-image.sh

kubernetes-image-upload:
	@scripts/upload-kubernetes-image.sh

kubernetes-image-verify:
	@scripts/verify-kubernetes-image.sh

kubernetes-image: kubernetes-image-upload kubernetes-image-verify

management-cluster-create:
	@scripts/management-cluster.sh create

management-cluster-verify:
	@scripts/management-cluster.sh verify

management-cluster-destroy:
	@scripts/management-cluster.sh destroy "$(CONFIRM)"

capi-providers-install:
	@scripts/capi-providers.sh install

capi-providers-verify:
	@scripts/capi-providers.sh verify

capi-credentials-verify:
	@scripts/capi-providers.sh credentials

workload-cluster-create:
	@scripts/workload-cluster.sh create

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

cluster-autoscaler-diagnostics:
	@scripts/cluster-autoscaler.sh diagnostics

lab-up:
	@scripts/lab-up.sh "$(CONFIRM)"

status:
	@scripts/status.sh

lint:
	@scripts/lint.sh
