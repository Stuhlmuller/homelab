#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-${TG_AWS_REGION:-us-east-1}}"
AWS_PROFILE_HINT="${AWS_PROFILE:-default}"

required_parameters=(
  "/homelab/dokploy/postgres_password"
  "/homelab/paperclip/better_auth_secret"
  "/homelab/traefik/cf_dns_api_token"
)

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI is required for SSM validation" >&2
  exit 1
fi

if ! aws sts get-caller-identity --output json >/dev/null 2>&1; then
  echo "AWS authentication is unavailable. Refresh it with: aws sso login --profile ${AWS_PROFILE_HINT}" >&2
  exit 1
fi

response="$(
  aws ssm get-parameters \
    --region "${AWS_REGION}" \
    --with-decryption \
    --names "${required_parameters[@]}" \
    --output json
)"

response_file="$(mktemp)"
trap 'rm -f "${response_file}"' EXIT
printf '%s' "${response}" >"${response_file}"

python3 - "${response_file}" <<'PY'
import json
from pathlib import Path
import sys

payload = json.loads(Path(sys.argv[1]).read_text())
invalid = payload.get("InvalidParameters", [])
if invalid:
    print("Missing required AWS SSM parameters:", file=sys.stderr)
    for name in invalid:
        print(f"  - {name}", file=sys.stderr)
    raise SystemExit(1)

for parameter in payload.get("Parameters", []):
    print(f"validated SSM parameter: {parameter['Name']}")
PY
