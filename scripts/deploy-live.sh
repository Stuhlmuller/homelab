#!/usr/bin/env bash
set -euo pipefail

ALLOW_DEGRADED_CLUSTER="${ALLOW_DEGRADED_CLUSTER:-0}"
SKIP_BOOTSTRAP="${SKIP_BOOTSTRAP:-0}"
TG_TF_PATH="${TG_TF_PATH:-tofu}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --allow-degraded-cluster)
      ALLOW_DEGRADED_CLUSTER=1
      shift
      ;;
    --skip-bootstrap)
      SKIP_BOOTSTRAP=1
      shift
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

make validate
./scripts/validate-aws-ssm.sh
./scripts/validate-aws-kms.sh
ALLOW_DEGRADED_CLUSTER="${ALLOW_DEGRADED_CLUSTER}" ./scripts/validate-live-cluster.sh

if [[ "${SKIP_BOOTSTRAP}" != "1" ]]; then
  SKIP_UNREACHABLE="${ALLOW_DEGRADED_CLUSTER}" \
  ALLOW_DEGRADED_CLUSTER="${ALLOW_DEGRADED_CLUSTER}" \
  ./scripts/bootstrap-rolling.sh
fi

terragrunt run --all --tf-path "${TG_TF_PATH}" plan --working-dir terraform/live/homelab
terragrunt run --all --non-interactive --tf-path "${TG_TF_PATH}" apply --working-dir terraform/live/homelab

./scripts/validate-live-workloads.sh
