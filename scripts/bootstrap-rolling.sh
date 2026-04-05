#!/usr/bin/env bash
set -euo pipefail

SKIP_UNREACHABLE="${SKIP_UNREACHABLE:-0}"
ALLOW_DEGRADED_CLUSTER="${ALLOW_DEGRADED_CLUSTER:-0}"
ANSIBLE_PLAYBOOK_BIN="${ANSIBLE_PLAYBOOK:-$HOME/.local/pipx/venvs/ansible/bin/ansible-playbook}"

if [[ ! -x "${ANSIBLE_PLAYBOOK_BIN}" ]]; then
  echo "ansible-playbook is not executable: ${ANSIBLE_PLAYBOOK_BIN}" >&2
  exit 1
fi

hosts=(zimaboard-1 zimaboard-2 zimaboard-0)

run_cluster_validation() {
  local attempt
  for attempt in {1..18}; do
    if ALLOW_DEGRADED_CLUSTER="${ALLOW_DEGRADED_CLUSTER}" ./scripts/validate-live-cluster.sh >/tmp/homelab-cluster-validate.log 2>&1; then
      cat /tmp/homelab-cluster-validate.log
      rm -f /tmp/homelab-cluster-validate.log
      return 0
    fi
    sleep 10
  done

  cat /tmp/homelab-cluster-validate.log >&2 || true
  rm -f /tmp/homelab-cluster-validate.log
  return 1
}

for host in "${hosts[@]}"; do
  host_ip="$(python3 - "${host}" <<'PY'
from pathlib import Path
import re
import sys

target = sys.argv[1]
content = Path("ansible/inventories/production/hosts.yml").read_text().splitlines()
current_host = None

for line in content:
    host_match = re.match(r"^\s{8}([a-zA-Z0-9-]+):\s*$", line)
    if host_match:
        current_host = host_match.group(1)
        continue

    ip_match = re.match(r"^\s{10}ansible_host:\s*([0-9.]+)\s*$", line)
    if ip_match and current_host == target:
        print(ip_match.group(1))
        raise SystemExit(0)
    elif ip_match:
        current_host = None

raise SystemExit(f"host {target} not found in inventory")
PY
)"

  if ! ping -c 1 -W 1 "${host_ip}" >/dev/null 2>&1; then
    if [[ "${SKIP_UNREACHABLE}" == "1" ]]; then
      echo "skipping unreachable host ${host} (${host_ip})"
      continue
    fi
    echo "host ${host} (${host_ip}) is unreachable" >&2
    exit 1
  fi

  echo "bootstrapping ${host} (${host_ip})"
  ANSIBLE_CONFIG=ansible/ansible.cfg \
    "${ANSIBLE_PLAYBOOK_BIN}" \
    -i ansible/inventories/production/hosts.yml \
    ansible/playbooks/bootstrap.yml \
    --limit "${host}"

  run_cluster_validation
done
