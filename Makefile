SHELL := /bin/bash
.DEFAULT_GOAL := help

ENV ?= local-arm64
CONFIG := config/environments/$(ENV).env

ifeq ($(wildcard $(CONFIG)),)
$(error Unknown ENV "$(ENV)": missing $(CONFIG))
endif

export PROJECT_ROOT := $(CURDIR)
export ENV
export CONFIG

.PHONY: help preflight host-setup secrets-check local-create local-up local-health local-down \
	local-destroy inventory host-prepare kolla-sync openstack-precheck \
	openstack-pull openstack-build-overrides openstack-deploy openstack-validate \
	openstack-post-deploy openstack-bootstrap openstack-verify \
	kubernetes-image-builder-create kubernetes-image-builder-destroy \
	kubernetes-image-build kubernetes-image-upload kubernetes-image-verify \
	kubernetes-image management-cluster-create management-cluster-verify \
	management-cluster-destroy status lint

help:
	@echo "OpenStack/Kubernetes testbed automation"
	@echo
	@echo "Usage: make <target> ENV=local-arm64"
	@echo
	@echo "Host and VM lifecycle:"
	@echo "  preflight              Read-only host and configuration checks"
	@echo "  host-setup             Install Lima/socket_vmnet prerequisites (privileged)"
	@echo "  secrets-check          Validate local secret permissions and Git ignores"
	@echo "  local-create           Create the Lima controller and compute instances"
	@echo "  local-up               Start project instances"
	@echo "  local-health           Verify host networking and deployed OpenStack readiness"
	@echo "  local-down             Remove the route and stop project instances"
	@echo "  local-destroy          Delete only project Lima instances (CONFIRM=$(ENV))"
	@echo "  status                 Show instance, network and local state"
	@echo
	@echo "OpenStack deployment:"
	@echo "  inventory              Generate the current Ansible/Kolla inventory"
	@echo "  host-prepare           Prepare Ubuntu hosts, swap and external veth/NAT"
	@echo "  kolla-sync             Sync deployment inputs to the controller"
	@echo "  openstack-precheck     Run Kolla bootstrap and prechecks"
	@echo "  openstack-pull         Cache required OpenStack images on both hosts"
	@echo "  openstack-build-overrides Build the local nova-libvirt corrective image"
	@echo "  openstack-deploy       Deploy OpenStack with Kolla-Ansible"
	@echo "  openstack-validate     Validate rendered service configurations"
	@echo "  openstack-post-deploy  Generate admin credentials"
	@echo "  openstack-bootstrap    Create networks, images and CAPO project credentials"
	@echo "  openstack-verify       Run CirrOS, Ubuntu and CAPO-network preflight"
	@echo
	@echo "Kubernetes node image:"
	@echo "  kubernetes-image-builder-create  Create the isolated ARM64 image builder"
	@echo "  kubernetes-image-build           Build and checksum the Kubernetes QCOW2"
	@echo "  kubernetes-image-builder-destroy Delete only the image builder (CONFIRM=$(ENV))"
	@echo "  kubernetes-image-upload          Upload the pinned image to Glance"
	@echo "  kubernetes-image-verify          Boot and verify the image with Nova"
	@echo "  kubernetes-image                 Upload and verify an existing built image"
	@echo
	@echo "Local management cluster:"
	@echo "  management-cluster-create  Create and verify the pinned single-node kind cluster"
	@echo "  management-cluster-verify  Verify Ready state and the in-cluster OpenStack API path"
	@echo "  management-cluster-destroy Delete only the local kind cluster (CONFIRM=$(ENV))"
	@echo
	@echo "Development:"
	@echo "  lint                    Static checks that do not mutate the host"

preflight:
	@scripts/host-preflight.sh

host-setup:
	@scripts/host-setup.sh

secrets-check:
	@scripts/secrets-check.sh

local-create:
	@scripts/local-create.sh

local-up:
	@scripts/local-up.sh

local-health:
	@scripts/local-health.sh

local-down:
	@scripts/local-down.sh

local-destroy:
	@scripts/local-destroy.sh "$(CONFIRM)"

inventory:
	@scripts/generate-inventory.sh

host-prepare: kolla-sync
	@scripts/run-controller.sh ansible-playbook \
		-i /opt/openstack-k8s/ansible/inventory/$(ENV)/generated-hosts.ini \
		/opt/openstack-k8s/ansible/playbooks/prepare-hosts.yml

kolla-sync: inventory
	@scripts/sync-to-controller.sh

openstack-precheck: kolla-sync
	@scripts/configure-kolla.sh
	@scripts/run-kolla.sh bootstrap-servers
	@scripts/run-kolla.sh prechecks

openstack-pull: kolla-sync
	@scripts/configure-kolla.sh --base-images
	@scripts/run-kolla.sh pull

openstack-build-overrides: kolla-sync
	@scripts/build-kolla-overrides.sh

openstack-deploy: openstack-build-overrides
	@scripts/configure-kolla.sh
	@scripts/run-kolla.sh deploy

openstack-validate:
	@scripts/run-kolla.sh validate-config

openstack-post-deploy:
	@scripts/run-kolla.sh post-deploy
	@scripts/fetch-admin-clouds.sh

openstack-bootstrap:
	@scripts/bootstrap-openstack.sh

openstack-verify:
	@scripts/openstack-verify.sh

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

status:
	@scripts/status.sh

lint:
	@scripts/lint.sh
