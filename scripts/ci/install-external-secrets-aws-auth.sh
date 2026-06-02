#!/usr/bin/env bash
set -euo pipefail

: "${EXTERNAL_SECRETS_AWS_SSM_ACCESS_KEY_ID:?EXTERNAL_SECRETS_AWS_SSM_ACCESS_KEY_ID must be provided by the protected CI environment}"
: "${EXTERNAL_SECRETS_AWS_SSM_SECRET_ACCESS_KEY:?EXTERNAL_SECRETS_AWS_SSM_SECRET_ACCESS_KEY must be provided by the protected CI environment}"

namespace_manifest="clusters/homelab/apps/external-secrets/namespace.yaml"
secret_name="aws-ssm-auth"
namespace="external-secrets"

if [[ ! -f "$namespace_manifest" ]]; then
  echo "${namespace_manifest} is missing; cannot install the External Secrets AWS auth Secret safely." >&2
  exit 1
fi

kubectl apply -f "$namespace_manifest"

kubectl -n "$namespace" create secret generic "$secret_name" \
  --from-literal=access-key-id="$EXTERNAL_SECRETS_AWS_SSM_ACCESS_KEY_ID" \
  --from-literal=secret-access-key="$EXTERNAL_SECRETS_AWS_SSM_SECRET_ACCESS_KEY" \
  --dry-run=client \
  -o yaml \
  | kubectl label --local -f - -o yaml \
      app.kubernetes.io/managed-by=github-actions \
      app.kubernetes.io/name="$secret_name" \
      app.kubernetes.io/part-of=external-secrets \
  | kubectl annotate --local -f - -o yaml \
      homelab.rst.io/secret-source=protected-ci-environment \
  | kubectl apply -f -
