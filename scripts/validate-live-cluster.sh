#!/usr/bin/env bash
set -euo pipefail

ALLOW_DEGRADED_CLUSTER="${ALLOW_DEGRADED_CLUSTER:-0}"
PING_TIMEOUT_SECONDS="${PING_TIMEOUT_SECONDS:-1}"
SSH_TIMEOUT_SECONDS="${SSH_TIMEOUT_SECONDS:-5}"
USE_TAILSCALE_ENDPOINTS="${USE_TAILSCALE_ENDPOINTS:-0}"
INVENTORY_FILE="ansible/inventories/production/hosts.yml"

if [[ ! -f "${INVENTORY_FILE}" ]]; then
  echo "missing inventory file: ${INVENTORY_FILE}" >&2
  exit 1
fi

inventory_hosts=()
while IFS= read -r record; do
  inventory_hosts+=("${record}")
done < <(
  python3 - "${USE_TAILSCALE_ENDPOINTS}" <<'PY'
from pathlib import Path
import re
import sys

use_tailscale = sys.argv[1] == "1"
content = Path("ansible/inventories/production/hosts.yml").read_text().splitlines()
current_host = None
current_ip = None
current_tailscale_ip = None

for line in content:
    host_match = re.match(r"^\s{8}([a-zA-Z0-9-]+):\s*$", line)
    if host_match:
        if current_host and current_ip:
            endpoint = current_tailscale_ip if use_tailscale and current_tailscale_ip else current_ip
            print(f"{current_host} {endpoint}")
        current_host = host_match.group(1)
        current_ip = None
        current_tailscale_ip = None
        continue

    ip_match = re.match(r"^\s{10}ansible_host:\s*([0-9.]+)\s*$", line)
    if ip_match and current_host:
        current_ip = ip_match.group(1)
        continue

    tailscale_match = re.match(r"^\s{10}tailscale_ip:\s*([0-9.]+)\s*$", line)
    if tailscale_match and current_host:
        current_tailscale_ip = tailscale_match.group(1)

if current_host and current_ip:
    endpoint = current_tailscale_ip if use_tailscale and current_tailscale_ip else current_ip
    print(f"{current_host} {endpoint}")
PY
)

reachable_hosts=()
failed_hosts=()

for record in "${inventory_hosts[@]}"; do
  name="${record%% *}"
  ip="${record##* }"

  echo "checking ${name} (${ip})"

  ping_ok=1
  if ! ping -c 1 -W "${PING_TIMEOUT_SECONDS}" "${ip}" >/dev/null 2>&1; then
    echo "  ping failed; continuing with SSH validation"
    ping_ok=0
  fi

  if ! ssh -o BatchMode=yes -o ConnectTimeout="${SSH_TIMEOUT_SECONDS}" "${ip}" \
    'systemctl is-active nomad consul docker >/dev/null'; then
    echo "  ssh or service check failed"
    failed_hosts+=("${name}:${ip}:ssh")
    continue
  fi

  if [[ "${ping_ok}" == "1" ]]; then
    echo "  host is reachable and core services are active"
  else
    echo "  host is reachable over SSH and core services are active"
  fi
  reachable_hosts+=("${name}:${ip}")
done

if [[ "${#reachable_hosts[@]}" -eq 0 ]]; then
  echo "no reachable hosts were found" >&2
  exit 1
fi

if [[ "${#failed_hosts[@]}" -gt 0 && "${ALLOW_DEGRADED_CLUSTER}" != "1" ]]; then
  echo "cluster host reachability validation failed:" >&2
  printf '  - %s\n' "${failed_hosts[@]}" >&2
  exit 1
fi

controller_ip="${reachable_hosts[0]#*:}"

run_remote_check() {
  local description="$1"
  local command="$2"
  local stderr_file
  local output

  stderr_file="$(mktemp)"
  if ! output="$(ssh -o BatchMode=yes -o ConnectTimeout="${SSH_TIMEOUT_SECONDS}" "${controller_ip}" "${command}" 2>"${stderr_file}")"; then
    echo "failed to query ${description} from ${controller_ip}" >&2
    cat "${stderr_file}" >&2
    rm -f "${stderr_file}"
    exit 1
  fi

  rm -f "${stderr_file}"
  printf '%s' "${output}"
}

nomad_members="$(run_remote_check "Nomad server membership" 'nomad server members -json')"
nomad_nodes="$(run_remote_check "Nomad node status" 'nomad node status -json')"
consul_members="$(run_remote_check "Consul members" 'consul members')"

nomad_members_file="$(mktemp)"
nomad_nodes_file="$(mktemp)"
consul_members_file="$(mktemp)"
trap 'rm -f "${nomad_members_file}" "${nomad_nodes_file}" "${consul_members_file}"' EXIT

printf '%s' "${nomad_members}" >"${nomad_members_file}"
printf '%s' "${nomad_nodes}" >"${nomad_nodes_file}"
printf '%s' "${consul_members}" >"${consul_members_file}"

python3 - "${ALLOW_DEGRADED_CLUSTER}" "${nomad_members_file}" "${nomad_nodes_file}" "${consul_members_file}" <<'PY'
import json
from pathlib import Path
import sys

allow_degraded = sys.argv[1] == "1"
nomad_members = json.loads(Path(sys.argv[2]).read_text())
nomad_nodes = json.loads(Path(sys.argv[3]).read_text())
consul_member_lines = [
    line for line in Path(sys.argv[4]).read_text().splitlines()
    if line.strip()
]
if consul_member_lines and consul_member_lines[0].startswith("Node"):
    consul_member_lines = consul_member_lines[1:]

alive_nomad = [member for member in nomad_members if member.get("Status") == "alive"]
ready_nodes = [node for node in nomad_nodes if node.get("Status") == "ready"]
alive_consul = []
for line in consul_member_lines:
    columns = line.split()
    if len(columns) >= 3 and columns[2] == "alive":
        alive_consul.append(line)

print(f"Nomad servers alive: {len(alive_nomad)}/{len(nomad_members)}")
print(f"Nomad nodes ready: {len(ready_nodes)}/{len(nomad_nodes)}")
print(f"Consul servers alive: {len(alive_consul)}/{len(consul_member_lines)}")

if allow_degraded:
    if len(alive_nomad) < 2 or len(ready_nodes) < 2 or len(alive_consul) < 2:
        raise SystemExit("degraded cluster validation failed; quorum is not healthy enough")
else:
    if len(alive_nomad) != len(nomad_members) or len(ready_nodes) != len(nomad_nodes) or len(alive_consul) != len(consul_member_lines):
        raise SystemExit("strict cluster validation failed; at least one member is down")
PY
