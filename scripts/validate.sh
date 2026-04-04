#!/usr/bin/env bash
set -euo pipefail

python3 -m unittest discover -s tests -p 'test_*.py' -v
./scripts/validate-skills.sh
./scripts/validate-shell.sh
./scripts/validate-nomad.sh
./scripts/validate-terraform.sh
./scripts/validate-terragrunt.sh
./scripts/validate-ansible-layout.sh
./scripts/validate-ansible.sh
