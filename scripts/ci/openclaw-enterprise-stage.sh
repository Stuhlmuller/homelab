#!/usr/bin/env bash
set -euo pipefail
umask 077

stage="${1:-}"
case "$stage" in
  full-sync|reconcile|stop|verification|restore|acceptance) ;;
  *) echo 'Invalid Enterprise operation stage' >&2; exit 2 ;;
esac
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ &&
   "${EXPECTED_SHA:-}" == "$GITHUB_SHA" ]] || exit 2
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

# A GitHub runner has no shared journal mount. Starting a mutating CLI here
# could lose pending API intents on interruption before its next run.
echo "Enterprise ${stage} blocked: durable private journal runner is not declared" >&2
exit 1
