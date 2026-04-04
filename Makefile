SHELL := /bin/bash
TG_TF_PATH ?= tofu
ANSIBLE_PLAYBOOK ?= /Users/themanofrod/.local/pipx/venvs/ansible/bin/ansible-playbook

.PHONY: lint test validate survey format format-check validate-terraform validate-nomad validate-structure validate-skills ansible-syntax bootstrap reconcile-tailscale bootstrap-rolling plan apply validate-live validate-ssm validate-kms validate-live-cluster validate-live-workloads unlock-state deploy-live

lint: format-check validate-terraform validate-nomad validate-structure ansible-syntax

test: validate-structure

validate: lint test

survey:
	./scripts/survey-cluster.sh

format:
	terragrunt hcl fmt --working-dir terraform/live/homelab
	nomad fmt nomad/jobs
	tofu fmt -recursive terraform

format-check:
	terragrunt hcl fmt --check --working-dir terraform/live/homelab
	nomad fmt -check nomad/jobs
	tofu fmt -check -recursive terraform

validate-terraform:
	./scripts/validate-terraform.sh

validate-nomad:
	./scripts/validate-nomad.sh

validate-structure:
	python3 -m unittest discover -s tests -p 'test_*.py'
	./scripts/validate-skills.sh
	./scripts/validate-ansible-layout.sh

validate-skills:
	./scripts/validate-skills.sh

ansible-syntax:
	./scripts/validate-ansible.sh

bootstrap:
	ANSIBLE_CONFIG=ansible/ansible.cfg $(ANSIBLE_PLAYBOOK) -i ansible/inventories/production/hosts.yml ansible/playbooks/bootstrap.yml

reconcile-tailscale:
	ANSIBLE_CONFIG=ansible/ansible.cfg $(ANSIBLE_PLAYBOOK) -i ansible/inventories/production/hosts.yml ansible/playbooks/reconcile-tailscale.yml

bootstrap-rolling:
	./scripts/bootstrap-rolling.sh

plan:
	TG_TF_PATH=$(TG_TF_PATH) terragrunt run --all --tf-path $(TG_TF_PATH) plan --working-dir terraform/live/homelab

apply:
	TG_TF_PATH=$(TG_TF_PATH) terragrunt run --all --non-interactive --tf-path $(TG_TF_PATH) apply --working-dir terraform/live/homelab

validate-ssm:
	./scripts/validate-aws-ssm.sh

validate-kms:
	./scripts/validate-aws-kms.sh

validate-live-cluster:
	./scripts/validate-live-cluster.sh

validate-live-workloads:
	./scripts/validate-live-workloads.sh

validate-live: validate-ssm validate-kms validate-live-cluster validate-live-workloads

unlock-state:
	./scripts/unlock-terragrunt-unit.sh $(UNIT) $(LOCK_ID)

deploy-live:
	./scripts/deploy-live.sh
