#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-${TG_AWS_REGION:-us-east-1}}"
KMS_KEY_ID="${TG_KMS_KEY_ID:-alias/homelab-opentofu}"

aws kms describe-key \
  --region "${AWS_REGION}" \
  --key-id "${KMS_KEY_ID}" \
  --query 'KeyMetadata.Arn' \
  --output text >/dev/null

echo "validated KMS key: ${KMS_KEY_ID}"
