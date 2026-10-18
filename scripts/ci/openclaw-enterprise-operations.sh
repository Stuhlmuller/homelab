#!/usr/bin/env bash
# shellcheck disable=SC2016
set -euo pipefail
umask 077

stage="${1:-}"
case "$stage" in inventory | archive | verify) ;; *) echo 'Invalid legacy operation stage' >&2; exit 2 ;; esac
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ && "${GITHUB_RUN_ID:-}" =~ ^[0-9]+$ ]] || exit 2
case "$stage" in
  archive) [[ "${BASELINE_REF:-}" =~ ^[0-9a-f]{40}/[0-9]+$ ]] || exit 2 ;;
  verify) [[ "${ARCHIVE_REF:-}" =~ ^[0-9a-f]{40}/[0-9]+$ ]] || exit 2 ;;
esac

bucket="$(jq -er .bucket IaC/config/application-backup-storage.json)"
[[ "$(aws s3api get-bucket-versioning --bucket "$bucket" --query Status --output text)" == Enabled ]] || exit 1
[[ "$(aws s3api get-bucket-encryption --bucket "$bucket" --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' --output text)" == 'aws:kms' ]] || exit 1

work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
python3 scripts/openclaw-retirement-status.py --config scripts/config/openclaw-enterprise.json --output "$work/status.json"
pod="$(jq -er .readerPod "$work/status.json")"
pod_uid="$(jq -er .readerPodUid "$work/status.json")"
[[ "$pod" =~ ^openclaw-retirement-reader-[a-z0-9-]+$ && "$pod_uid" =~ ^[0-9a-f-]{36}$ ]] || exit 1
[[ "$(kubectl -n ai get pod "$pod" -o jsonpath='{.metadata.uid}')" == "$pod_uid" ]] || exit 1

reader=(kubectl -n ai exec "$pod" -c reader --)
reader_input=(kubectl -n ai exec -i "$pod" -c reader --)
"${reader[@]}" sh -c 'umask 077; mkdir -p /private/legacy; chmod 700 /private/legacy'
"${reader_input[@]}" sh -c 'umask 077; cat > /private/legacy/config.json' <scripts/config/openclaw-enterprise.json
"${reader_input[@]}" sh -c 'umask 077; cat > /private/legacy/status.json' <"$work/status.json"
[[ "$(kubectl -n ai get pod "$pod" -o jsonpath='{.metadata.uid}')" == "$pod_uid" ]] || exit 1

require_absent_object() {
  aws s3api list-object-versions --bucket "$bucket" --prefix "$1" --output json |
    jq -e --arg key "$1" '[.Versions[]?, .DeleteMarkers[]?] | all(.Key != $key)' >/dev/null
}

restore_version() (
  pipe_dir="$(mktemp -d)"
  trap 'rm -rf -- "$pipe_dir"' EXIT
  mkfifo -m 600 "$pipe_dir/body"
  exec 3<>"$pipe_dir/body"
  aws s3api get-object --bucket "$bucket" --key "$1" --version-id "$2" \
    "$pipe_dir/body" >/dev/null 3>&- &
  source_pid=$!
  "${reader_input[@]}" sh -c 'umask 077; cat > "$1"' sh "$3" \
    <"$pipe_dir/body" 3>&- &
  reader_pid=$!
  source_result=0
  wait "$source_pid" || source_result=$?
  exec 3>&-
  wait "$reader_pid"
  exit "$source_result"
)

case "$stage" in
  inventory)
    baseline="/archive/private/baseline-${GITHUB_RUN_ID}.json"
    baseline_result="/private/legacy/baseline-${GITHUB_RUN_ID}.json"
    "${reader[@]}" python3 /etc/openclaw-retirement/retirement.py inventory \
      --config /private/legacy/config.json --status /private/legacy/status.json \
      --output "$baseline_result"
    "${reader[@]}" sh -c 'test ! -e "$1" && cp "$2" "$1" && chmod 600 "$1"' sh "$baseline" "$baseline_result"
    baseline_key="openclaw-enterprise/legacy/${GITHUB_SHA}/${GITHUB_RUN_ID}/baseline.json"
    require_absent_object "$baseline_key"
    "${reader[@]}" cat "$baseline" | aws s3 cp - "s3://${bucket}/${baseline_key}"
    ;;
  archive)
    baseline_id="${BASELINE_REF##*/}"
    baseline="/archive/private/baseline-${baseline_id}.json"
    archive_result="/private/legacy/archive-result-${GITHUB_RUN_ID}.json"
    aws s3 cp "s3://${bucket}/openclaw-enterprise/legacy/${BASELINE_REF}/baseline.json" - >"$work/baseline.json"
    "${reader[@]}" cat "$baseline" >"$work/mounted-baseline.json"
    cmp "$work/baseline.json" "$work/mounted-baseline.json"
    "${reader[@]}" env GITHUB_ACTIONS=true python3 /etc/openclaw-retirement/retirement.py archive \
      --config /private/legacy/config.json --status /private/legacy/status.json \
      --baseline "$baseline" --destination /archive/private \
      --output "$archive_result"
    receipt="$("${reader[@]}" cat "$archive_result" | jq -er .receipt)"
    [[ "$receipt" =~ ^/archive/private/legacy-[0-9a-f]{64}/receipt\.json$ ]] || exit 1
    prefix="openclaw-enterprise/legacy/${GITHUB_SHA}/${GITHUB_RUN_ID}"
    for name in legacy.tar.gz receipt.json final.json; do require_absent_object "$prefix/$name"; done
    "${reader[@]}" cat "${receipt%/*}/legacy.tar.gz" | aws s3 cp - "s3://${bucket}/${prefix}/legacy.tar.gz" --expected-size 80000000000
    "${reader[@]}" cat "$receipt" | aws s3 cp - "s3://${bucket}/${prefix}/receipt.json"
    archive_version="$(aws s3api head-object --bucket "$bucket" --key "$prefix/legacy.tar.gz" --query VersionId --output text)"
    receipt_version="$(aws s3api head-object --bucket "$bucket" --key "$prefix/receipt.json" --query VersionId --output text)"
    [[ -n "$archive_version" && "$archive_version" != None && -n "$receipt_version" && "$receipt_version" != None ]] || exit 1
    restore="/archive/private/offsite-${GITHUB_RUN_ID}"
    "${reader[@]}" sh -c 'umask 077; test ! -e "$1" && mkdir -m 700 "$1"' sh "$restore"
    restore_version "$prefix/legacy.tar.gz" "$archive_version" "$restore/legacy.tar.gz"
    restore_version "$prefix/receipt.json" "$receipt_version" "$restore/receipt.json"
    "${reader[@]}" python3 /etc/openclaw-retirement/retirement.py verify-archive \
      --config /private/legacy/config.json --receipt "$restore/receipt.json"
    "${reader[@]}" cat "$restore/receipt.json" >"$work/receipt.json"
    jq -n --arg sha "$GITHUB_SHA" --arg run "$GITHUB_RUN_ID" \
      --arg baseline "$BASELINE_REF" --arg archiveVersion "$archive_version" \
      --arg receiptVersion "$receipt_version" --arg digest "$(jq -er .sha256 "$work/receipt.json")" \
      '{sourceSha:$sha,runId:$run,baselineRef:$baseline,archiveVersion:$archiveVersion,receiptVersion:$receiptVersion,archiveSha256:$digest,offsiteRestoreVerified:true}' >"$work/final.json"
    aws s3 cp "$work/final.json" "s3://${bucket}/${prefix}/final.json"
    "${reader[@]}" sh -c 'case "$1" in /archive/private/offsite-[0-9]*) rm -rf -- "$1";; *) exit 1;; esac' sh "$restore"
    ;;
  verify)
    jq -e '.replicas == 0 and .readyReplicas == 0 and .pods == 0 and .activeJobs == 0 and (.cronJobSuspended == true or .cronJobAbsent == true)' "$work/status.json" >/dev/null
    prefix="openclaw-enterprise/legacy/${ARCHIVE_REF}"
    final_key="$prefix/final.json"
    # Archive refuses prior versions, so the oldest exact-key version is its original receipt.
    final_version="$(aws s3api list-object-versions --bucket "$bucket" --prefix "$final_key" --output json |
      jq -er --arg key "$final_key" 'if .IsTruncated == false then [.Versions[]? | select(.Key == $key) | .VersionId] | last else empty end')"
    aws s3api get-object --bucket "$bucket" --key "$final_key" --version-id "$final_version" "$work/final.json" >/dev/null
    jq -e --arg ref "$ARCHIVE_REF" '.offsiteRestoreVerified == true and (.sourceSha + "/" + .runId) == $ref and .archiveVersion != null and .receiptVersion != null' "$work/final.json" >/dev/null
    archive_version="$(jq -er .archiveVersion "$work/final.json")"
    receipt_version="$(jq -er .receiptVersion "$work/final.json")"
    restore="/archive/private/offsite-${GITHUB_RUN_ID}"
    "${reader[@]}" sh -c 'umask 077; test ! -e "$1" && mkdir -m 700 "$1"' sh "$restore"
    restore_version "$prefix/legacy.tar.gz" "$archive_version" "$restore/legacy.tar.gz"
    restore_version "$prefix/receipt.json" "$receipt_version" "$restore/receipt.json"
    "${reader[@]}" python3 /etc/openclaw-retirement/retirement.py verify-archive \
      --config /private/legacy/config.json --receipt "$restore/receipt.json"
    "${reader[@]}" cat "$restore/receipt.json" | jq -e --arg sha "$(jq -er .archiveSha256 "$work/final.json")" '.sha256 == $sha' >/dev/null
    "${reader[@]}" sh -c 'case "$1" in /archive/private/offsite-[0-9]*) rm -rf -- "$1";; *) exit 1;; esac' sh "$restore"
    ;;
esac

echo 'Legacy operation completed; private receipt retained offsite'
