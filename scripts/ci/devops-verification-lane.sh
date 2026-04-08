#!/usr/bin/env bash
set -euo pipefail

required_commands=(aws terragrunt tofu unzip)
for cmd in "${required_commands[@]}"; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "missing required command: ${cmd}" >&2
    exit 1
  fi
done

echo "toolchain check passed: ${required_commands[*]}"

AWS_REGION="${AWS_REGION:-us-east-1}"
KMS_KEY_ID="${TG_KMS_KEY_ID:-alias/homelab-opentofu}"
WORKING_DIR="${WORKING_DIR:-terraform/live/homelab}"
TG_TF_PATH="${TG_TF_PATH:-tofu}"

echo "running AWS STS identity check"
aws sts get-caller-identity --output json >/tmp/aws-sts-identity.json

# Validate the exact permission path needed by HOM-209 without printing key material.
echo "running AWS KMS GenerateDataKey check against ${KMS_KEY_ID}"
aws kms generate-data-key \
  --region "${AWS_REGION}" \
  --key-id "${KMS_KEY_ID}" \
  --key-spec AES_256 \
  --query 'KeyId' \
  --output text >/tmp/kms-generate-data-key.txt

echo "running Terragrunt init path check"
terragrunt run --all --tf-path "${TG_TF_PATH}" init --working-dir "${WORKING_DIR}" -- -backend=false -input=false

echo "running Terragrunt plan path check"
terragrunt run --all --tf-path "${TG_TF_PATH}" plan --working-dir "${WORKING_DIR}" -- -refresh=false -lock=false -input=false -no-color

echo "DevOps verification lane checks completed successfully"
