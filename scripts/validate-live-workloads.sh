#!/usr/bin/env bash
set -euo pipefail

SSH_TIMEOUT_SECONDS="${SSH_TIMEOUT_SECONDS:-5}"
INGRESS_IP="${INGRESS_IP:-10.1.0.200}"
NOMAD_HTTP_IP="${NOMAD_HTTP_IP:-10.1.0.200}"
POLICY_BOT_LOCAL_TARGET="${POLICY_BOT_LOCAL_TARGET:-http://127.0.0.1:18080}"
POLICY_BOT_FUNNEL_AUTH_PATH="${POLICY_BOT_FUNNEL_AUTH_PATH:-/api/github/auth}"
POLICY_BOT_FUNNEL_HOOK_PATH="${POLICY_BOT_FUNNEL_HOOK_PATH:-/api/github/hook}"
USE_TAILSCALE_ENDPOINTS="${USE_TAILSCALE_ENDPOINTS:-0}"
INVENTORY_FILE="ansible/inventories/production/hosts.yml"

if [[ ! -f "${INVENTORY_FILE}" ]]; then
  echo "missing inventory file: ${INVENTORY_FILE}" >&2
  exit 1
fi

for job in nfs-csi-plugin traefik dokploy paperclip policy-bot; do
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
  "nomad/jobs/policy-bot/config" \
  "nomad/jobs/paperclip/config" \
  "nomad/jobs/traefik/cf_dns_api_token"; do
  grep -q "${path}" <<<"${nomad_variables}" || {
    echo "missing Nomad variable: ${path}" >&2
    exit 1
  }
done

policy_bot_public_url="$(
  ssh -o BatchMode=yes -o ConnectTimeout="${SSH_TIMEOUT_SECONDS}" "${NOMAD_HTTP_IP}" \
    'nomad var get -item public_url nomad/jobs/policy-bot/config'
)"
policy_bot_public_url="${policy_bot_public_url%/}"

if [[ -z "${policy_bot_public_url}" ]]; then
  echo "policy-bot public_url is missing from Nomad variables" >&2
  exit 1
fi

inventory_ips=()
while IFS= read -r ip; do
  inventory_ips+=("${ip}")
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
            print(endpoint)
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
    print(endpoint)
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

policy_bot_funnel_status="$(
  ssh -o BatchMode=yes -o ConnectTimeout="${SSH_TIMEOUT_SECONDS}" "${INGRESS_IP}" \
    'tailscale funnel status || true'
)"

for path in "${POLICY_BOT_FUNNEL_AUTH_PATH}" "${POLICY_BOT_FUNNEL_HOOK_PATH}"; do
  grep -Fq "${path} proxy ${POLICY_BOT_LOCAL_TARGET}" <<<"${policy_bot_funnel_status}" || {
    echo "policy-bot Funnel path is not configured on ${INGRESS_IP}: ${path} -> ${POLICY_BOT_LOCAL_TARGET}" >&2
    printf '%s\n' "${policy_bot_funnel_status}" >&2
    exit 1
  }
done
echo "validated Policy Bot Funnel paths on ${INGRESS_IP}"

if grep -Fq "|-- / proxy ${POLICY_BOT_LOCAL_TARGET}" <<<"${policy_bot_funnel_status}"; then
  echo "policy-bot root path is unexpectedly public through Funnel on ${INGRESS_IP}" >&2
  printf '%s\n' "${policy_bot_funnel_status}" >&2
  exit 1
fi
echo "validated Policy Bot root path is not public through Funnel on ${INGRESS_IP}"

ssh -o BatchMode=yes -o ConnectTimeout="${SSH_TIMEOUT_SECONDS}" "${INGRESS_IP}" \
  "curl --fail --silent --show-error ${POLICY_BOT_LOCAL_TARGET}/api/health" >/dev/null
echo "validated Policy Bot local health endpoint on ${INGRESS_IP}"

echo "validated Policy Bot public base URL at ${policy_bot_public_url}"
