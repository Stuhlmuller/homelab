#!/usr/bin/env bash
set -euo pipefail
umask 077

stage="${1:-}"
case "$stage" in
  full-sync|reconcile|stop|verification|restore|acceptance) ;;
  *) echo 'Invalid Enterprise operation stage' >&2; exit 2 ;;
esac
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ &&
   "${EXPECTED_SHA:-}" == "$GITHUB_SHA" &&
   "${GITHUB_REF:-}" == refs/heads/main &&
   "${GITHUB_REPOSITORY:-}" == Stuhlmuller/homelab ]] || exit 2
[[ "$(git rev-parse HEAD)" == "$GITHUB_SHA" ]] || exit 2
jq -e '
  .schemaVersion == 1 and
  .privateJournal == {
    required: true, sourceBound: true, durable: true,
    mountPath: "/private/openclaw-enterprise/journal.json",
    mode: "0600", lockRequired: true
  } and
  .privateArchives.legacy.mountPath == "/private/openclaw-enterprise/legacy-archive" and
  .privateArchives.enterprise.mountPath == "/private/openclaw-enterprise/new-archive"
' scripts/config/openclaw-enterprise.json >/dev/null
[[ "${GH_REPO:-}" == Stuhlmuller/homelab && -n "${GH_TOKEN:-}" ]] || exit 2
[[ "$(gh api "repos/${GH_REPO}/git/ref/heads/main" --jq .object.sha)" == "$EXPECTED_SHA" ]] || exit 2

if [[ "$stage" == full-sync ]]; then
  [[ -n "${OCTELIUM_AUTH_TOKEN:-}" && "${GH_REPO:-}" == Stuhlmuller/homelab &&
     -n "${GH_TOKEN:-}" ]] || exit 2
  bash scripts/ci/install-kubeconfig.sh
  bash scripts/ci/openclaw-enterprise-full-sync.sh
  exit
fi

if [[ "$stage" == reconcile || "$stage" == stop || "$stage" == verification ]]; then
  jq -e '.journalOperator.enabled == true' scripts/config/openclaw-enterprise.json >/dev/null || {
    echo 'Enterprise operator remains disabled pending placement and credential proofs' >&2
    exit 1
  }
  [[ -n "${OCTELIUM_AUTH_TOKEN:-}" && "${GH_REPO:-}" == Stuhlmuller/homelab &&
     -n "${GH_TOKEN:-}" ]] || exit 2
  bash scripts/ci/install-kubeconfig.sh
  python3 -I scripts/ci/openclaw-enterprise-journal-operator.py "$stage"
  exit
fi

# Restore and acceptance need separate recovery and human-session contracts.
echo "Enterprise ${stage} blocked: durable private journal runner is not declared" >&2
exit 1
