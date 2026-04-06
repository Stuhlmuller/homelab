#!/usr/bin/env bash
set -euo pipefail

required_files=(
  "ansible/collections/requirements.yml"
  "ansible/inventories/production/hosts.yml"
  "ansible/inventories/production/group_vars/all.yml"
  "ansible/playbooks/bootstrap.yml"
  "ansible/roles/consul/templates/consul.hcl.j2"
  "ansible/roles/nomad/templates/nomad.hcl.j2"
)

for file in "${required_files[@]}"; do
  [[ -f "$file" ]] || {
    echo "missing required Ansible file: $file" >&2
    exit 1
  }
done

grep -q '10.1.0.199' ansible/inventories/production/hosts.yml
grep -q '10.1.0.200' ansible/inventories/production/hosts.yml
grep -q '10.1.0.201' ansible/inventories/production/hosts.yml
grep -q '10.1.0.202' ansible/inventories/production/hosts.yml
grep -q 'retry_join' ansible/roles/nomad/templates/nomad.hcl.j2
grep -q 'node_class' ansible/roles/nomad/templates/nomad.hcl.j2
