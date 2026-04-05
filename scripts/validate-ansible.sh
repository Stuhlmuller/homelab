#!/usr/bin/env bash
set -euo pipefail

ANSIBLE_PLAYBOOK_BIN="${ANSIBLE_PLAYBOOK:-}"
if [[ -z "${ANSIBLE_PLAYBOOK_BIN}" ]]; then
  if command -v ansible-playbook >/dev/null 2>&1; then
    ANSIBLE_PLAYBOOK_BIN="$(command -v ansible-playbook)"
  elif [[ -x "$HOME/.local/pipx/venvs/ansible/bin/ansible-playbook" ]]; then
    ANSIBLE_PLAYBOOK_BIN="$HOME/.local/pipx/venvs/ansible/bin/ansible-playbook"
  fi
fi

if [[ -z "${ANSIBLE_PLAYBOOK_BIN}" ]]; then
  echo "ansible-playbook is not installed; skipping syntax check" >&2
  exit 0
fi

ANSIBLE_PYTHON_BIN="$(dirname "${ANSIBLE_PLAYBOOK_BIN}")/python"
if [[ ! -x "${ANSIBLE_PYTHON_BIN}" ]]; then
  ANSIBLE_PYTHON_BIN="$(command -v python3)"
fi

if ! "${ANSIBLE_PYTHON_BIN}" -c 'import boto3, botocore' >/dev/null 2>&1; then
  echo "Ansible controller dependencies are missing: boto3 and botocore are required for repository validation." >&2
  echo "Install them into the active Ansible runtime before bootstrapping." >&2
  exit 1
fi

ANSIBLE_CONFIG=ansible/ansible.cfg \
"${ANSIBLE_PLAYBOOK_BIN}" \
  -i ansible/inventories/production/hosts.yml \
  ansible/playbooks/bootstrap.yml \
  --syntax-check >/dev/null
