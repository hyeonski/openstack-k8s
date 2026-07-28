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

.PHONY: help preflight host-setup secrets-check local-create local-up local-down \
	local-destroy inventory host-prepare kolla-sync openstack-precheck \
	openstack-pull openstack-build-overrides openstack-deploy openstack-validate \
	openstack-post-deploy openstack-bootstrap \
	openstack-verify status lint

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

status:
	@scripts/status.sh

lint:
	@scripts/lint.sh
