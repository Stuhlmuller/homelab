#!/usr/bin/env bash
set -euo pipefail
umask 077

[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ &&
   "${EXPECTED_SHA:-}" == "$GITHUB_SHA" &&
   "${GITHUB_REF:-}" == refs/heads/main &&
   "${GITHUB_REPOSITORY:-}" == Stuhlmuller/homelab &&
   "${GH_REPO:-}" == Stuhlmuller/homelab && -n "${GH_TOKEN:-}" &&
   -n "${OCTELIUM_AUTH_TOKEN:-}" ]] || exit 2
[[ "$(git rev-parse HEAD)" == "$EXPECTED_SHA" ]] || exit 2
[[ "$(gh api "repos/${GH_REPO}/git/ref/heads/main" --jq .object.sha)" == "$EXPECTED_SHA" ]] || exit 2

bash scripts/ci/install-kubeconfig.sh
python3 -I scripts/ci/openclaw-enterprise-recover-bound-bind.py \
  "$FAILED_BIND_SOURCE_SHA" "$FAILED_BIND_RUN_ID" "$FAILED_BIND_ATTEMPT" \
  "$FAILED_BIND_JOB_UID" "$FAILED_BIND_POD_UID" \
  "$BOUND_SECRET_UID" "$BOUND_SECRET_RV" "$BOUND_INSTALLATION_ID"
