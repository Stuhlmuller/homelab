#!/usr/bin/env bash
set -euo pipefail

SSH_TIMEOUT_SECONDS="${SSH_TIMEOUT_SECONDS:-5}"
INGRESS_IP="${INGRESS_IP:-10.1.0.200}"
NOMAD_HTTP_IP="${NOMAD_HTTP_IP:-10.1.0.200}"
INVENTORY_FILE="ansible/inventories/production/hosts.yml"

if [[ ! -f "${INVENTORY_FILE}" ]]; then
  echo "missing inventory file: ${INVENTORY_FILE}" >&2
  exit 1
fi

for job in nfs-csi-plugin traefik dokploy paperclip; do
  job_status="$(ssh -o BatchMode=yes -o ConnectTimeout="${SSH_TIMEOUT_SECONDS}" "${NOMAD_HTTP_IP}" "nomad job status -json ${job}")"
  job_status_file="$(mktemp)"
  printf '%s' "${job_status}" >"${job_status_file}"
  python3 - "${job}" "${job_status_file}" <<'PY'
import json
from pathlib import Path
import sys

payload = json.loads(Path(sys.argv[2]).read_text())
name = sys.argv[1]

if isinstance(payload, list):
    if not payload:
        raise SystemExit(f"Nomad job {name} did not return any status entries")
    job = next(
        (
            candidate
            for candidate in payload
            if candidate.get("Summary", {}).get("JobID") == name
        ),
        payload[0],
    )
else:
    job = payload

group_summary = job.get("Summary", {}).get("Summary", {})
running = sum(group.get("Running", 0) for group in group_summary.values())

if running < 1:
    raise SystemExit(f"Nomad job {name} has no running allocations")

print(f"validated Nomad job: {name} (running allocations: {running})")
PY
  rm -f "${job_status_file}"
done

nomad_variables="$(ssh -o BatchMode=yes -o ConnectTimeout="${SSH_TIMEOUT_SECONDS}" "${NOMAD_HTTP_IP}" 'nomad var list')"
for path in \
  "nomad/jobs/dokploy/config" \
  "nomad/jobs/paperclip/config" \
  "nomad/jobs/traefik/cf_dns_api_token"; do
  grep -q "${path}" <<<"${nomad_variables}" || {
    echo "missing Nomad variable: ${path}" >&2
    exit 1
  }
done

inventory_ips=()
while IFS= read -r ip; do
  inventory_ips+=("${ip}")
done < <(
  python3 - <<'PY'
from pathlib import Path
import re

content = Path("ansible/inventories/production/hosts.yml").read_text().splitlines()

for line in content:
    ip_match = re.match(r"^\s{10}ansible_host:\s*([0-9.]+)\s*$", line)
    if ip_match:
        print(ip_match.group(1))
PY
)

for ip in "${inventory_ips[@]}"; do
  state="$(ssh -o BatchMode=yes -o ConnectTimeout="${SSH_TIMEOUT_SECONDS}" "${ip}" 'systemctl is-active tailscaled 2>/dev/null || true')"
  if [[ "${state}" != "active" ]]; then
    echo "tailscaled is not active on ${ip}" >&2
    exit 1
  fi

  tailscale_status="$(ssh -o BatchMode=yes -o ConnectTimeout="${SSH_TIMEOUT_SECONDS}" "${ip}" 'tailscale status --json')"
  tailscale_status_file="$(mktemp)"
  printf '%s' "${tailscale_status}" >"${tailscale_status_file}"
  python3 - "${ip}" "${tailscale_status_file}" <<'PY'
import json
from pathlib import Path
import sys

ip = sys.argv[1]
status = json.loads(Path(sys.argv[2]).read_text())
backend_state = status.get("BackendState")
health_messages = status.get("Health") or []
blocking_messages = [
    message for message in health_messages
    if "locked out" in message.lower()
    or "needs login" in message.lower()
    or "logged out" in message.lower()
]

if backend_state != "Running":
    raise SystemExit(f"tailscale backend is not running on {ip}: {backend_state}")

if blocking_messages:
    raise SystemExit(
        f"tailscale session is unhealthy on {ip}: {'; '.join(blocking_messages)}"
    )

print(f"validated tailscaled on {ip} ({backend_state})")
PY
  rm -f "${tailscale_status_file}"
done

curl --fail --silent --show-error "http://${INGRESS_IP}:8080/ping" >/dev/null
echo "validated Traefik ping endpoint on ${INGRESS_IP}"

curl --fail --silent --show-error \
  --resolve "dokploy.stinkyboi.com:443:${INGRESS_IP}" \
  "https://dokploy.stinkyboi.com/api/health" >/dev/null
echo "validated Dokploy HTTPS health endpoint on ${INGRESS_IP}"

curl --fail --silent --show-error \
  --resolve "paperclip.stinkyboi.com:443:${INGRESS_IP}" \
  "https://paperclip.stinkyboi.com/api/health" >/dev/null
echo "validated Paperclip HTTPS health endpoint on ${INGRESS_IP}"
