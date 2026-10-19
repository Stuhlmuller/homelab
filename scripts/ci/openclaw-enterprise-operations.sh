#!/usr/bin/env bash
# shellcheck disable=SC2016
set -euo pipefail
umask 077
phase=preflight
work=
on_exit() {
  result=$?
  if [[ -n "$work" ]]; then rm -rf -- "$work"; fi
  if (( result != 0 )) && [[ "${stage:-}" == publish-inventory && -n "${OPENCLAW_PHASE_FILE:-}" ]]; then
    printf '%s\n' "$phase" >"$OPENCLAW_PHASE_FILE"
  fi
}
trap on_exit EXIT

stage="${1:-}"
case "$stage" in inventory | publish-inventory | archive | publish-archive | verify) ;; *) echo 'Invalid legacy operation stage' >&2; exit 2 ;; esac
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ && "${GITHUB_RUN_ID:-}" =~ ^[0-9]+$ ]] || exit 2
case "$stage" in
  publish-inventory)
    [[ "${BASELINE_REF:-}" =~ ^[0-9a-f]{40}/[0-9]+$ ]] || exit 2
    ;;
  archive) [[ "${BASELINE_REF:-}" =~ ^[0-9a-f]{40}/[0-9]+$ ]] || exit 2 ;;
  publish-archive)
    [[ "${BASELINE_REF:-}" =~ ^[0-9a-f]{40}/[0-9]+$ && "${ARCHIVE_REF:-}" =~ ^[0-9a-f]{40}/[0-9]+$ ]] || exit 2
    ;;
  verify) [[ "${ARCHIVE_REF:-}" =~ ^[0-9a-f]{40}/[0-9]+$ ]] || exit 2 ;;
esac

bucket="$(jq -er .bucket IaC/config/application-backup-storage.json)"
[[ "$(aws s3api get-bucket-versioning --bucket "$bucket" --query Status --output text)" == Enabled ]] || exit 1
[[ "$(aws s3api get-bucket-encryption --bucket "$bucket" --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' --output text)" == 'aws:kms' ]] || exit 1

work="$(mktemp -d)"
status_refresh_count=0
python3 scripts/openclaw-retirement-status.py --config scripts/config/openclaw-enterprise.json --output "$work/status.json"
pod="$(jq -er .readerPod "$work/status.json")"
pod_uid="$(jq -er .readerPodUid "$work/status.json")"
[[ "$pod" =~ ^openclaw-retirement-reader-[a-z0-9-]+$ && "$pod_uid" =~ ^[0-9a-f-]{36}$ ]] || exit 1
[[ "$(kubectl -n ai get pod "$pod" -o jsonpath='{.metadata.uid}')" == "$pod_uid" ]] || exit 1

reader=(kubectl -n ai exec "$pod" -c reader --)
reader_input=(kubectl -n ai exec -i "$pod" -c reader --)
retirement_sha="$(sha256sum clusters/homelab/apps/openclaw/retirement/retirement.py | cut -d' ' -f1)"
[[ "$("${reader[@]}" sha256sum /etc/openclaw-retirement/retirement.py | cut -d' ' -f1)" == "$retirement_sha" ]] || exit 1
"${reader[@]}" sh -c 'umask 077; mkdir -p /private/legacy; chmod 700 /private/legacy; chmod g-s /private/legacy'
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
  aws s3api get-object --bucket "$bucket" --key "$1" --version-id "$2" \
    "$pipe_dir/body" >/dev/null &
  source_pid=$!
  "${reader_input[@]}" sh -c 'umask 077; cat > "$1"' sh "$3" \
    <"$pipe_dir/body" &
  reader_pid=$!
  if ! wait -n -p completed_pid "$source_pid" "$reader_pid"; then
    kill "$source_pid" "$reader_pid" 2>/dev/null || true
    wait "$source_pid" "$reader_pid" 2>/dev/null || true
    exit 1
  fi
  if [[ "$completed_pid" == "$source_pid" ]]; then wait "$reader_pid"; else wait "$source_pid"; fi
)

refresh_status() {
  status_refresh_count=$((status_refresh_count + 1))
  recheck="$work/recheck-${status_refresh_count}.json"
  python3 scripts/openclaw-retirement-status.py --config scripts/config/openclaw-enterprise.json --output "$recheck"
  jq -e --arg stage "$1" --slurpfile before "$work/status.json" '
    .readerPodUid == $before[0].readerPodUid and .readerPod == $before[0].readerPod and
    .claims == $before[0].claims and .volumes == $before[0].volumes and
    .roots == $before[0].roots and .image == $before[0].image and
    .assistantSha256 == $before[0].assistantSha256 and
    ($stage != "stopped" or (.replicas == 0 and .readyReplicas == 0 and
      .pods == 0 and .activeJobs == 0 and
      (.cronJobSuspended == true or .cronJobAbsent == true)))
  ' "$recheck" >/dev/null
  "${reader_input[@]}" sh -c 'umask 077; cat > /private/legacy/status.json' <"$recheck"
}

validate_baseline() {
  jq -e --slurpfile status "$2" --slurpfile config scripts/config/openclaw-enterprise.json '
    . as $baseline | $status[0] as $live | $config[0].legacyRetention as $contract |
    ($baseline.format == 1 and $baseline.node == $contract.node and
     $baseline.claims == $live.claims and
     $baseline.kubernetes == {image: $live.image, assistantSha256: $live.assistantSha256, volumes: $live.volumes} and
     $baseline.rootIdentity == $live.roots and
     $baseline.requiredNas == $contract.requiredNas and
     ($baseline.databases | keys) == ($contract.requiredLocal | sort) and
     ([$baseline.databases[] | (.bytes | type) == "number" and .bytes >= 0 and
       (.sha256 | type) == "string" and (.sha256 | test("^[0-9a-f]{64}$"))] | all) and
     $baseline.roots.local.uid == $contract.localUid and
     $baseline.roots.nas.uid == $contract.nasUid and
     ([$baseline.roots.local.tree, $baseline.roots.nas.tree] |
       all((.entries | type) == "number" and .entries > 0 and
           (.bytes | type) == "number" and .bytes >= 0 and
           (.sha256 | type) == "string" and (.sha256 | test("^[0-9a-f]{64}$")))))
  ' "$1" >/dev/null
}

lookup_baseline_versions() {
  if ! versions="$(aws s3api list-object-versions --no-paginate --bucket "$bucket" --prefix "$baseline_key" --output json 2>"$work/s3-error")"; then
    phase=publication-lookup-failed
    if grep -Fq '(AccessDenied)' "$work/s3-error"; then phase=publication-lookup-denied; fi
    return 1
  fi
  phase=publication-lookup-response
  jq -e '.IsTruncated == false and ((.Versions // []) | type == "array") and ((.DeleteMarkers // []) | type == "array")' <<<"$versions" >/dev/null
}

run_inventory_worker() {
  local worker marker worker_sha state attempt
  worker=/etc/openclaw-retirement/inventory-worker.sh
  marker="/private/legacy/inventory-${GITHUB_RUN_ID}.state"
  worker_sha=d9ffb78cf80bc8c2fc4e90587e66e721d999679ec123a1d583be40f4f75d0f0d
  [[ "$(sha256sum clusters/homelab/apps/openclaw/retirement/inventory-worker.sh | cut -d' ' -f1)" == "$worker_sha" ]] || exit 1
  [[ "$("${reader[@]}" sha256sum "$worker" | cut -d' ' -f1)" == "$worker_sha" ]] || exit 1
  "${reader[@]}" sh -c '
    set -eu
    run_id="$1"
    directory=/private/legacy
    command -v nohup >/dev/null
    test ! -e "$directory/baseline-${run_id}.json"
    test ! -L "$directory/baseline-${run_id}.json"
    test ! -e "$directory/inventory-${run_id}.state"
    test ! -L "$directory/inventory-${run_id}.state"
    test ! -e "$directory/inventory-${run_id}.log"
    test ! -L "$directory/inventory-${run_id}.log"
    mkdir "$directory/inventory.lock"
    nohup sh /etc/openclaw-retirement/inventory-worker.sh "$run_id" \
      </dev/null >/dev/null 2>&1 &
  ' sh "$GITHUB_RUN_ID"
  state=pending
  for ((attempt = 0; attempt < 420; attempt++)); do
    state="$("${reader[@]}" sh -c \
      'if test -f "$1"; then cat "$1"; else printf pending; fi' sh "$marker")"
    case "$state" in
      success) break ;;
      failure)
        "${reader[@]}" cat "/private/legacy/inventory-${GITHUB_RUN_ID}.log" |
          aws s3 cp - "s3://${bucket}/openclaw-enterprise/legacy/${GITHUB_SHA}/${GITHUB_RUN_ID}/diagnostic.log" >/dev/null
        exit 1
        ;;
      pending) sleep 30 ;;
      *) exit 1 ;;
    esac
  done
  [[ "$state" == success ]] || exit 1
}

verify_restored_archive() {
  local receipt="$1" marker="/private/legacy/verify-${GITHUB_RUN_ID}.state" state attempt
  "${reader[@]}" sh -c '
    set -eu
    umask 077
    receipt="$1"; marker="$2"
    test ! -e "$marker" && test ! -L "$marker"
    nohup sh -c '\''
      if python3 /etc/openclaw-retirement/retirement.py verify-archive \
        --config /private/legacy/config.json --receipt "$1"; then
        printf "success\\n" >"$2"
      else
        printf "failure\\n" >"$2"
      fi
    '\'' sh "$receipt" "$marker" </dev/null >"${marker%.state}.log" 2>&1 &
  ' sh "$receipt" "$marker"
  state=pending
  for ((attempt = 0; attempt < 420; attempt++)); do
    state="$("${reader[@]}" sh -c \
      'if test -f "$1"; then cat "$1"; else printf pending; fi' sh "$marker")"
    case "$state" in
      success) break ;;
      failure) exit 1 ;;
      pending|'') sleep 30 ;;
      *) exit 1 ;;
    esac
  done
  [[ "$state" == success ]] || exit 1
}

case "$stage" in
  inventory)
    baseline="/archive/private/baseline-${GITHUB_RUN_ID}.json"
    baseline_result="/private/legacy/baseline-${GITHUB_RUN_ID}.json"
    run_inventory_worker
    refresh_status inventory
    "${reader[@]}" sh -c 'test ! -e "$1" && cp "$2" "$1" && chmod 600 "$1"' sh "$baseline" "$baseline_result"
    baseline_key="openclaw-enterprise/legacy/${GITHUB_SHA}/${GITHUB_RUN_ID}/baseline.json"
    require_absent_object "$baseline_key"
    "${reader[@]}" cat "$baseline" | aws s3 cp - "s3://${bucket}/${baseline_key}"
    ;;
  publish-inventory)
    phase=baseline
    baseline_id="${BASELINE_REF##*/}"
    baseline="/archive/private/baseline-${baseline_id}.json"
    baseline_result="/private/legacy/baseline-${baseline_id}.json"
    marker="/private/legacy/inventory-${baseline_id}.state"
    worker=/etc/openclaw-retirement/inventory-worker.sh
    [[ "$("${reader[@]}" cat "$marker")" == success ]] || exit 1
    worker_sha=d9ffb78cf80bc8c2fc4e90587e66e721d999679ec123a1d583be40f4f75d0f0d
    [[ "$(sha256sum clusters/homelab/apps/openclaw/retirement/inventory-worker.sh | cut -d' ' -f1)" == "$worker_sha" ]] || exit 1
    [[ "$("${reader[@]}" sha256sum "$worker" | cut -d' ' -f1)" == "$worker_sha" ]] || exit 1
    "${reader[@]}" cat "$baseline" >"$work/baseline.json"
    "${reader[@]}" cat "$baseline_result" >"$work/worker-baseline.json"
    cmp "$work/baseline.json" "$work/worker-baseline.json"
    validate_baseline "$work/baseline.json" "$work/status.json"
    refresh_status inventory
    phase=publication
    baseline_key="openclaw-enterprise/legacy/${BASELINE_REF}/baseline.json"
    phase=publication-lookup
    lookup_baseline_versions
    count="$(jq --arg key "$baseline_key" '[(.Versions[]?, .DeleteMarkers[]?) | select(.Key == $key)] | length' <<<"$versions")"
    if [[ "$count" == 0 ]]; then
      [[ "$BASELINE_REF" == 'd55e2ab8521e427c059e07e34b270e476092a8a1/39127113354' ]] || exit 1
      phase=publication-upload
      aws s3api put-object --bucket "$bucket" --key "$baseline_key" \
        --body "$work/baseline.json" --if-none-match '*' >"$work/put.json"
      phase=publication-lookup
      lookup_baseline_versions
    fi
    phase=publication-version
    version="$(jq -er --arg key "$baseline_key" '
      if .IsTruncated == false and
         ([(.Versions[]?, .DeleteMarkers[]?) | select(.Key == $key)] | length) == 1
      then [.Versions[]? | select(.Key == $key) | .VersionId] | .[0]
      else empty end' <<<"$versions")"
    [[ "$version" != null && "$version" != None ]] || exit 1
    phase=verification
    aws s3api get-object --bucket "$bucket" --key "$baseline_key" \
      --version-id "$version" "$work/offsite-baseline.json" >"$work/get.json"
    cmp "$work/baseline.json" "$work/offsite-baseline.json"
    [[ "$(aws s3api head-object --bucket "$bucket" --key "$baseline_key" \
      --version-id "$version" --query ServerSideEncryption --output text)" == aws:kms ]] || exit 1
    refresh_status inventory
    ;;
  archive|publish-archive)
    baseline_id="${BASELINE_REF##*/}"
    baseline="/archive/private/baseline-${baseline_id}.json"
    archive_id="$GITHUB_RUN_ID"
    archive_sha="$GITHUB_SHA"
    if [[ "$stage" == publish-archive ]]; then
      archive_id="${ARCHIVE_REF##*/}"
      archive_sha="${ARCHIVE_REF%%/*}"
    fi
    archive_result="/private/legacy/archive-result-${archive_id}.json"
    aws s3 cp "s3://${bucket}/openclaw-enterprise/legacy/${BASELINE_REF}/baseline.json" - >"$work/baseline.json"
    "${reader[@]}" cat "$baseline" >"$work/mounted-baseline.json"
    cmp "$work/baseline.json" "$work/mounted-baseline.json"
    observed="/private/legacy/baseline-${archive_id}.json"
    if [[ "$stage" == archive ]]; then run_inventory_worker; fi
    refresh_status stopped
    if [[ "$stage" == archive ]]; then
      "${reader[@]}" sh -c '
        set -eu
        umask 077
        baseline="$1"; observed="$2"; output="$3"; run_id="$4"
        log="/private/legacy/archive-${run_id}.log"
        test ! -e "$output" && test ! -e "$log"
        test ! -L "$output" && test ! -L "$log"
        nohup flock -n /private/legacy/archive.lock env GITHUB_ACTIONS=true \
          python3 /etc/openclaw-retirement/retirement.py archive \
          --config /private/legacy/config.json --status /private/legacy/status.json \
          --baseline "$baseline" --observed "$observed" --destination /archive/private \
          --output "$output" </dev/null >"$log" 2>&1 &
        worker=$!
        sleep 2
        kill -0 "$worker"
      ' sh "$baseline" "$observed" "$archive_result" "$archive_id"
    else
    receipt="$("${reader[@]}" cat "$archive_result" | jq -er .receipt)"
    [[ "$receipt" =~ ^/archive/private/legacy-[0-9a-f]{64}/receipt\.json$ ]] || exit 1
    "${reader[@]}" cat "$observed" >"$work/observed.json"
    "${reader[@]}" cat "$receipt" >"$work/receipt.json"
    validate_baseline "$work/observed.json" "$work/status.json"
    jq -e --slurpfile observed "$work/observed.json" '.format == 1 and .inventory == $observed[0] and (.sha256 | test("^[0-9a-f]{64}$"))' "$work/receipt.json" >/dev/null
    prefix="openclaw-enterprise/legacy/${archive_sha}/${archive_id}"
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
    verify_restored_archive "$restore/receipt.json"
    "${reader[@]}" cat "$restore/receipt.json" >"$work/restored-receipt.json"
    cmp "$work/receipt.json" "$work/restored-receipt.json"
    jq -n --arg sha "$archive_sha" --arg run "$archive_id" \
      --arg baseline "$BASELINE_REF" --arg archiveVersion "$archive_version" \
      --arg receiptVersion "$receipt_version" --arg digest "$(jq -er .sha256 "$work/receipt.json")" \
      '{sourceSha:$sha,runId:$run,baselineRef:$baseline,archiveVersion:$archiveVersion,receiptVersion:$receiptVersion,archiveSha256:$digest,offsiteRestoreVerified:true}' >"$work/final.json"
    refresh_status stopped
    aws s3 cp "$work/final.json" "s3://${bucket}/${prefix}/final.json"
    "${reader[@]}" sh -c 'case "$1" in /archive/private/offsite-[0-9]*) rm -rf -- "$1";; *) exit 1;; esac' sh "$restore"
    fi
    ;;
  verify)
    jq -e '.replicas == 0 and .readyReplicas == 0 and .pods == 0 and .activeJobs == 0 and (.cronJobSuspended == true or .cronJobAbsent == true)' "$work/status.json" >/dev/null
    prefix="openclaw-enterprise/legacy/${ARCHIVE_REF}"
    final_key="$prefix/final.json"
    # Archive refuses prior versions, so the oldest exact-key version is its original receipt.
    final_version="$(aws s3api list-object-versions --no-paginate --bucket "$bucket" --prefix "$final_key" --output json |
      jq -er --arg key "$final_key" 'if .IsTruncated == false then [.Versions[]? | select(.Key == $key) | .VersionId] | last else empty end')"
    aws s3api get-object --bucket "$bucket" --key "$final_key" --version-id "$final_version" "$work/final.json" >/dev/null
    jq -e --arg ref "$ARCHIVE_REF" '.offsiteRestoreVerified == true and (.sourceSha + "/" + .runId) == $ref and .archiveVersion != null and .receiptVersion != null' "$work/final.json" >/dev/null
    archive_version="$(jq -er .archiveVersion "$work/final.json")"
    receipt_version="$(jq -er .receiptVersion "$work/final.json")"
    restore="/archive/private/offsite-${GITHUB_RUN_ID}"
    "${reader[@]}" sh -c 'umask 077; test ! -e "$1" && mkdir -m 700 "$1"' sh "$restore"
    restore_version "$prefix/legacy.tar.gz" "$archive_version" "$restore/legacy.tar.gz"
    restore_version "$prefix/receipt.json" "$receipt_version" "$restore/receipt.json"
    verify_restored_archive "$restore/receipt.json"
    "${reader[@]}" cat "$restore/receipt.json" | jq -e --arg sha "$(jq -er .archiveSha256 "$work/final.json")" '.sha256 == $sha' >/dev/null
    "${reader[@]}" sh -c 'case "$1" in /archive/private/offsite-[0-9]*) rm -rf -- "$1";; *) exit 1;; esac' sh "$restore"
    ;;
esac

if [[ "$stage" == archive ]]; then
  echo 'Legacy archive worker started; protected publication remains pending'
else
  echo 'Legacy operation completed; private receipt retained offsite'
fi
