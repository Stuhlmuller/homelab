#!/usr/bin/env bash
# Protected, source-pinned entry point. Activation remains false until the
# private recovery, publication, and isolated-canary gates are fulfilled.
set -euo pipefail
umask 077

stage="${RUN_STAGE:-}"
case "$stage" in
  inspect|firewall-baseline|firewall-baseline-recover|placement|canary-admit|canary-admit-recover|canary-abort|canary-release|canary-release-recover|qualify|ownership-capture|ownership-approve|owned-cleanup|talos-1.11.6|talos-1.12.12|talos-1.13.11|talos-1.14.4|kubernetes-1.35.9) ;;
  *) exit 2 ;;
esac
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_REF:-}" == refs/heads/main &&
   "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ && "${EXPECTED_SHA:-}" == "$GITHUB_SHA" &&
   "${GITHUB_RUN_ID:-}" =~ ^[0-9]+$ ]] || exit 2
[[ "$GITHUB_SHA" == "$(gh api repos/Stuhlmuller/homelab/branches/main --jq .commit.sha)" ]] || exit 1

config=scripts/config/platform-maintenance.json
jq -e '.schemaVersion == 1 and .sourceRevisionPolicy == "exact-current-main-sha-from-protected-workflow"' "$config" >/dev/null
if [[ "$stage" == placement || "$stage" == firewall-baseline || "$stage" == canary-abort ]]; then
  jq -e '.activationEnabled == false and .canary.node == "zimaboard-2"' "$config" >/dev/null
elif [[ "$stage" == canary-admit || "$stage" == canary-admit-recover ||
        "$stage" == canary-release || "$stage" == canary-release-recover ]]; then
  jq -e '(.canary.node | type) == "string"' "$config" >/dev/null
elif [[ "$stage" != inspect && "$stage" != firewall-baseline && "$stage" != firewall-baseline-recover ]]; then
  jq -e '.activationEnabled == true and (.canary.node | type == "string")' "$config" >/dev/null
fi
if [[ "$stage" == canary-admit-recover || "$stage" == canary-abort ]]; then
  [[ -n "${OCTELIUM_AUTH_TOKEN:-}" && "${ADMISSION_RUN_ID:-}" =~ ^[1-9][0-9]*$ &&
     "${EVIDENCE_SOURCE_SHA:-}" =~ ^[0-9a-f]{40}$ ]] || exit 2
  git merge-base --is-ancestor "$EVIDENCE_SOURCE_SHA" "$GITHUB_SHA" || exit 1
fi
if [[ "$stage" == canary-release-recover ]]; then
  [[ "${RELEASE_SOURCE_SHA:-}" =~ ^[0-9a-f]{40}$ &&
     "${RELEASE_RUN_ID:-}" =~ ^[1-9][0-9]*$ &&
     "${CLEANUP_RUN_ID:-}" =~ ^[1-9][0-9]*$ ]] || exit 2
  git rev-list --first-parent "$GITHUB_SHA" | grep -Fx "$RELEASE_SOURCE_SHA" >/dev/null || exit 1
fi

work="$(mktemp -d)"
chmod 700 "$work"
private_log="$work/tunnel.log"
tunnel_pid=
cleanup() {
  if [[ -n "$tunnel_pid" ]]; then
    kill "$tunnel_pid" 2>/dev/null || true
    wait "$tunnel_pid" 2>/dev/null || true
  fi
  if [[ -d "$work" ]]; then rm -rf -- "$work"; fi
}
trap cleanup EXIT

bucket="$(terragrunt render --config IaC/application-backup-storage.hcl --json --write=false --log-disable | jq -er .inputs.bucket)"
[[ "$(aws s3api get-bucket-versioning --bucket "$bucket" --query Status --output text)" == Enabled ]]
[[ "$(aws s3api get-bucket-encryption --bucket "$bucket" \
  --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' \
  --output text)" == 'aws:kms' ]]

retain_result() {
  local result="$1" name="$2" key response checksum version readback
  [[ -f "$result" && ! -L "$result" && "$(stat -c %a "$result")" == 600 &&
     "$(stat -c %s "$result")" -le 1048576 ]] || exit 1
  key="openclaw-enterprise/platform/${GITHUB_SHA}/${GITHUB_RUN_ID}/${name}.json"
  checksum="$(openssl dgst -sha256 -binary "$result" | base64 -w0)"
  response="$(aws s3api put-object --bucket "$bucket" --key "$key" --body "$result" \
    --server-side-encryption aws:kms --if-none-match '*' \
    --checksum-algorithm SHA256 --checksum-sha256 "$checksum")"
  version="$(jq -er .VersionId <<<"$response")"
  [[ "$version" != null && "$version" != "" ]] || exit 1
  readback="$(aws s3api head-object --bucket "$bucket" --key "$key" \
    --version-id "$version" --checksum-mode ENABLED)"
  jq -e --arg version "$version" --arg checksum "$checksum" \
    '.VersionId == $version and .ChecksumSHA256 == $checksum and .ServerSideEncryption == "aws:kms"' \
    <<<"$readback" >/dev/null
}

load_receipt() {
  local key="$1" target="$2" expected_version="${3:-}" versions version metadata checksum actual
  versions="$(aws s3api list-object-versions --bucket "$bucket" --prefix "$key" --no-paginate)"
  version="$(jq -er --arg key "$key" '
    if .IsTruncated == false and (.DeleteMarkers // []) == [] and
       (.Versions | length) == 1 and .Versions[0].Key == $key and
       (.Versions[0].IsLatest == true) and
       (.Versions[0].VersionId | type == "string" and . != "" and . != "null")
    then .Versions[0].VersionId else empty end' <<<"$versions")"
  [[ -z "$expected_version" || "$version" == "$expected_version" ]] || exit 1
  metadata="$(aws s3api head-object --bucket "$bucket" --key "$key" \
    --version-id "$version" --checksum-mode ENABLED)"
  checksum="$(jq -er --arg version "$version" '
    select(.VersionId == $version and .ServerSideEncryption == "aws:kms" and
      (.ContentLength | type == "number" and . >= 1 and . <= 1048576)) |
    .ChecksumSHA256 | select(type == "string" and . != "")' <<<"$metadata")"
  aws s3api get-object --bucket "$bucket" --key "$key" --version-id "$version" "$target" >/dev/null
  chmod 600 "$target"
  actual="$(openssl dgst -sha256 -binary "$target" | base64 -w0)"
  [[ "$actual" == "$checksum" ]]
  loaded_receipt_version="$version"
}

require_absent_receipt() {
  local key="$1" versions
  versions="$(aws s3api list-object-versions --bucket "$bucket" --prefix "$key" --no-paginate)"
  jq -e --arg key "$key" '
    .IsTruncated == false and
    ([.Versions[]? | select(.Key == $key)] | length) == 0 and
    ([.DeleteMarkers[]? | select(.Key == $key)] | length) == 0
  ' <<<"$versions" >/dev/null
}

connect_talos() {
    # Octelium clientless credentials cannot reach TCP Services. This separate
    # CLIENT credential is limited by homelab-platform-talos-ci-access.
    [[ -n "${OCTELIUM_AUTH_TOKEN:-}" && -n "${OCE_OCTELIUM_CLIENT_AUTH_TOKEN:-}" &&
       -n "${OCE_TALOSCONFIG_B64:-}" ]] || exit 1
    bash scripts/ci/install-kubeconfig.sh
    printf %s "$OCE_TALOSCONFIG_B64" | base64 --decode >"$work/talosconfig"
    chmod 600 "$work/talosconfig"
    bash scripts/ci/install-octelium-client.sh >/dev/null
    install -m 0700 -d "$work/octelium"
    OCTELIUM_AUTH_TOKEN="$OCE_OCTELIUM_CLIENT_AUTH_TOKEN" \
      "${HOME}/.local/bin/octelium" --homedir "$work/octelium" connect \
      --domain stinkyboi.com --implementation gvisor --ip-mode v4 --no-dns \
      --publish talos-api-ci.homelab:127.0.0.1:15000 >"$private_log" 2>&1 &
    tunnel_pid=$!
    # Preserve the reviewed certificate hostname while connecting to the
    # runner-local Octelium TCP listener; Talos mTLS remains mandatory.
    printf '127.0.0.1 talos-api.homelab.local.stinkyboi.com\n' | sudo tee -a /etc/hosts >/dev/null
    python3 - <<'PY'
import socket
import time
for attempt in range(60):
    try:
        with socket.create_connection(("127.0.0.1", 15000), timeout=2):
            break
    except OSError:
        time.sleep(2)
else:
    raise SystemExit("Talos TCP tunnel did not become ready")
PY
}

case "$stage" in
  inspect)
    connect_talos
    python3 -I scripts/platform-maintenance.py inspect --config "$config" \
      --talosconfig "$work/talosconfig" --output "$work/inspect.json"
    retain_result "$work/inspect.json" inspect
    ;;
  firewall-baseline)
    [[ -n "${OCTELIUM_AUTH_TOKEN:-}" ]] || exit 1
    bash scripts/ci/install-kubeconfig.sh
    kubectl auth can-i create pods -n kube-system --quiet
    kubectl auth can-i create pods/exec -n kube-system --quiet
    kubectl auth can-i delete pods -n kube-system --quiet
    kubectl auth can-i get pods -n kube-system --quiet
    kubectl auth can-i list pods --all-namespaces --quiet
    kubectl auth can-i get nodes --quiet
    kubectl auth can-i list nodes --quiet
    pod_token="$(openssl rand -hex 24)"
    jq -n --arg sourceSha "$GITHUB_SHA" --arg runId "$GITHUB_RUN_ID" \
      --arg podToken "$pod_token" \
      '{format: 1, stage: "firewall-baseline", status: "attempted", verified: false,
        sourceSha: $sourceSha, runId: $runId, node: "zimaboard-2",
        podToken: $podToken}' >"$work/baseline-attempt.json"
    chmod 600 "$work/baseline-attempt.json"
    retain_result "$work/baseline-attempt.json" baseline-attempt
    if ! python3 -I scripts/network-policy-firewall-baseline.py --config "$config" \
      --expected-sha "$GITHUB_SHA" --bucket "$bucket" \
      --attempt "$work/baseline-attempt.json" --output "$work/baseline.json"; then
      if [[ -f "$work/baseline.json" && ! -L "$work/baseline.json" ]]; then
        retain_result "$work/baseline.json" baseline-interrupted
      fi
      exit 1
    fi
    retain_result "$work/baseline.json" baseline
    ;;
  firewall-baseline-recover)
    [[ -n "${OCTELIUM_AUTH_TOKEN:-}" ]] || exit 1
    [[ "${BASELINE_SOURCE_SHA:-}" =~ ^[0-9a-f]{40}$ &&
       "${BASELINE_RUN_ID:-}" =~ ^[1-9][0-9]*$ ]] || exit 2
    bash scripts/ci/install-kubeconfig.sh
    kubectl auth can-i delete pods -n kube-system --quiet
    kubectl auth can-i get pods -n kube-system --quiet
    attempt_name=baseline-attempt
    if [[ -n "${RELEASE_RUN_ID:-}" ]]; then
      [[ "$RELEASE_RUN_ID" =~ ^[1-9][0-9]*$ && -z "${ADMISSION_RUN_ID:-}" ]] || exit 2
      attempt_name=canary-release-recover-attempt
    elif [[ -n "${ADMISSION_RUN_ID:-}" ]]; then
      [[ "$ADMISSION_RUN_ID" =~ ^[1-9][0-9]*$ ]] || exit 2
      attempt_name=canary-admit-recover-attempt
    fi
    load_receipt "openclaw-enterprise/platform/${BASELINE_SOURCE_SHA}/${BASELINE_RUN_ID}/${attempt_name}.json" \
      "$work/baseline-attempt.json"
    jq -n --arg sourceSha "$GITHUB_SHA" --arg runId "$GITHUB_RUN_ID" \
      --arg baselineSourceSha "$BASELINE_SOURCE_SHA" --arg baselineRunId "$BASELINE_RUN_ID" \
      '{format: 1, stage: "firewall-baseline-recover", status: "attempted",
        verified: false, sourceSha: $sourceSha, runId: $runId,
        baselineSourceSha: $baselineSourceSha, baselineRunId: $baselineRunId}' \
      >"$work/baseline-recover-attempt.json"
    chmod 600 "$work/baseline-recover-attempt.json"
    retain_result "$work/baseline-recover-attempt.json" baseline-recover-attempt
    if ! python3 -I scripts/network-policy-firewall-baseline.py recover --config "$config" \
      --expected-sha "$GITHUB_SHA" --bucket "$bucket" \
      --attempt "$work/baseline-attempt.json" \
      --baseline-source-sha "$BASELINE_SOURCE_SHA" --baseline-run-id "$BASELINE_RUN_ID" \
      --output "$work/baseline-recover.json"; then
      if [[ -f "$work/baseline-recover.json" && ! -L "$work/baseline-recover.json" ]]; then
        retain_result "$work/baseline-recover.json" baseline-recover-interrupted
      fi
      exit 1
    fi
    retain_result "$work/baseline-recover.json" baseline-recover
    ;;
  placement)
    [[ -n "${OCTELIUM_AUTH_TOKEN:-}" ]] || exit 1
    [[ "${BASELINE_SOURCE_SHA:-}" == "$GITHUB_SHA" &&
       "${BASELINE_RUN_ID:-}" =~ ^[1-9][0-9]*$ ]] || exit 2
    bash scripts/ci/install-kubeconfig.sh
    kubectl auth can-i get nodes --quiet
    kubectl auth can-i list nodes --quiet
    kubectl auth can-i list pods --all-namespaces --quiet
    kubectl auth can-i get nodes.metrics.k8s.io --quiet
    kubectl auth can-i get nodes/proxy --quiet
    python3 -I scripts/network-policy-placement.py --config "$config" \
      --expected-sha "$GITHUB_SHA" --baseline-source-sha "$BASELINE_SOURCE_SHA" \
      --baseline-run-id "$BASELINE_RUN_ID" --bucket "$bucket" \
      --output "$work/placement.json"
    retain_result "$work/placement.json" placement
    ;;
  canary-admit|canary-release)
    [[ -n "${OCTELIUM_AUTH_TOKEN:-}" ]] || exit 1
    bash scripts/ci/install-kubeconfig.sh
    if [[ "$stage" == canary-admit ]]; then
      kubectl auth can-i get nodes --quiet
      kubectl auth can-i list nodes --quiet
      kubectl auth can-i list pods --all-namespaces --quiet
      kubectl auth can-i get nodes.metrics.k8s.io --quiet
      kubectl auth can-i get nodes/proxy --quiet
    fi
    install -m 0700 -d "$work/receipts"
    placement_version=
    placement_node=
    placement_node_uid=
    placement_boot_id=
    selection_args=()
    if [[ "$stage" == canary-release ]]; then
      [[ "${CLEANUP_RUN_ID:-}" =~ ^[1-9][0-9]*$ ]] || exit 2
      load_receipt "openclaw-enterprise/platform/${GITHUB_SHA}/${CLEANUP_RUN_ID}/cleanup.json" \
        "$work/receipts/cleanup.json"
      capture_run_id="$(jq -er '.captureRunId | select(type == "string" and test("^[1-9][0-9]*$"))' \
        "$work/receipts/cleanup.json")"
      load_receipt "openclaw-enterprise/platform/receipts/${GITHUB_SHA}/firewall-ownership/${capture_run_id}.json" \
        "$work/receipts/firewall-ownership.json"
      evidence_source_sha="$(jq -er '.evidenceSourceSha | select(type == "string" and test("^[0-9a-f]{40}$"))' \
        "$work/receipts/firewall-ownership.json")"
      placement_run_id="$(jq -er '.placementRunId | select(type == "string" and test("^[1-9][0-9]*$"))' \
        "$work/receipts/firewall-ownership.json")"
      placement_version="$(jq -er '.placementVersionId | select(type == "string" and . != "" and . != "null")' \
        "$work/receipts/firewall-ownership.json")"
      load_receipt "openclaw-enterprise/platform/receipts/${evidence_source_sha}/placement/${placement_run_id}.json" \
        "$work/receipts/placement.json" "$placement_version"
      admission_run_id="$(jq -er '.admissionRunId | select(type == "string" and test("^[1-9][0-9]*$"))' \
        "$work/receipts/firewall-ownership.json")"
      cleanup_pod_uid="$(jq -er '.cleanupPodUid | select(type == "string" and . != "")' \
        "$work/receipts/cleanup.json")"
      placement_node="$(jq -er '.node | select(type == "string" and . != "")' "$work/receipts/placement.json")"
      placement_node_uid="$(jq -er '.nodeUid | select(type == "string" and . != "")' "$work/receipts/placement.json")"
      placement_boot_id="$(jq -er '.bootID | select(type == "string" and . != "")' "$work/receipts/placement.json")"
    else
      [[ "${PLACEMENT_RUN_ID:-}" =~ ^[1-9][0-9]*$ ]] || exit 2
      placement_run_id="$PLACEMENT_RUN_ID"
      load_receipt "openclaw-enterprise/platform/receipts/${GITHUB_SHA}/placement/${PLACEMENT_RUN_ID}.json" \
        "$work/receipts/placement.json"
      placement_version="$loaded_receipt_version"
      placement_node="$(jq -er '.node | select(type == "string" and . != "")' "$work/receipts/placement.json")"
      placement_node_uid="$(jq -er '.nodeUid | select(type == "string" and . != "")' "$work/receipts/placement.json")"
      placement_boot_id="$(jq -er '.bootID | select(type == "string" and . != "")' "$work/receipts/placement.json")"
      selection_args=(--placement-run-id "$PLACEMENT_RUN_ID" --placement-version-id "$placement_version")
    fi
    jq -n --arg stage "$stage" --arg sourceSha "$GITHUB_SHA" --arg runId "$GITHUB_RUN_ID" \
      --arg placementRunId "$placement_run_id" --arg placementVersionId "$placement_version" \
      --arg node "$placement_node" --arg nodeUid "$placement_node_uid" \
      --arg bootID "$placement_boot_id" --arg cleanupRunId "${CLEANUP_RUN_ID:-}" \
      --arg cleanupPodUid "${cleanup_pod_uid:-}" --arg captureRunId "${capture_run_id:-}" \
      --arg admissionRunId "${admission_run_id:-}" \
      --arg evidenceSourceSha "${evidence_source_sha:-}" \
      '{format: 1, stage: $stage, status: "attempted", verified: false,
        sourceSha: $sourceSha, runId: $runId} +
        (if $stage == "canary-admit" then
          {node: $node, nodeUid: $nodeUid, bootID: $bootID,
           placementRunId: $placementRunId, placementVersionId: $placementVersionId}
         elif $stage == "canary-release" then
          {node: $node, nodeUid: $nodeUid, bootID: $bootID,
           placementRunId: $placementRunId, placementVersionId: $placementVersionId,
           cleanupRunId: $cleanupRunId, cleanupPodUid: $cleanupPodUid,
           captureRunId: $captureRunId, admissionRunId: $admissionRunId,
           evidenceSourceSha: $evidenceSourceSha}
         else {} end)' >"$work/canary-attempt.json"
    chmod 600 "$work/canary-attempt.json"
    retain_result "$work/canary-attempt.json" "${stage}-attempt"
    if ! python3 -I scripts/network-policy-canary-node.py "${stage#canary-}" \
      --config "$config" --expected-sha "$GITHUB_SHA" \
      --receipt-dir "$work/receipts" --bucket "$bucket" \
      "${selection_args[@]}" \
      --output "$work/canary.json"; then
      if [[ -f "$work/canary.json" && ! -L "$work/canary.json" ]]; then
        retain_result "$work/canary.json" "${stage}-interrupted"
      fi
      exit 1
    fi
    retain_result "$work/canary.json" "$stage"
    ;;
  canary-release-recover)
    [[ -n "${OCTELIUM_AUTH_TOKEN:-}" ]] || exit 1
    bash scripts/ci/install-kubeconfig.sh
    kubectl auth can-i create pods -n kube-system --quiet
    kubectl auth can-i create pods/exec -n kube-system --quiet
    kubectl auth can-i delete pods -n kube-system --quiet
    kubectl auth can-i get pods -n kube-system --quiet
    kubectl auth can-i list pods --all-namespaces --quiet
    kubectl auth can-i get nodes --quiet
    kubectl auth can-i list nodes --quiet
    install -m 0700 -d "$work/receipts"
    release_key="openclaw-enterprise/platform/${RELEASE_SOURCE_SHA}/${RELEASE_RUN_ID}/canary-release-attempt.json"
    cleanup_key="openclaw-enterprise/platform/${RELEASE_SOURCE_SHA}/${CLEANUP_RUN_ID}/cleanup.json"
    load_receipt "$release_key" "$work/receipts/release-attempt.json"
    release_version="$loaded_receipt_version"
    load_receipt "$cleanup_key" "$work/receipts/cleanup.json"
    cleanup_version="$loaded_receipt_version"
    capture_run_id="$(jq -er '.captureRunId | select(type == "string" and test("^[1-9][0-9]*$"))' \
      "$work/receipts/cleanup.json")"
    ownership_key="openclaw-enterprise/platform/receipts/${RELEASE_SOURCE_SHA}/firewall-ownership/${capture_run_id}.json"
    load_receipt "$ownership_key" "$work/receipts/firewall-ownership.json"
    ownership_version="$loaded_receipt_version"
    evidence_source_sha="$(jq -er '.evidenceSourceSha | select(type == "string" and test("^[0-9a-f]{40}$"))' \
      "$work/receipts/firewall-ownership.json")"
    admission_run_id="$(jq -er '.admissionRunId | select(type == "string" and test("^[1-9][0-9]*$"))' \
      "$work/receipts/firewall-ownership.json")"
    placement_run_id="$(jq -er '.placementRunId | select(type == "string" and test("^[1-9][0-9]*$"))' \
      "$work/receipts/firewall-ownership.json")"
    placement_version="$(jq -er '.placementVersionId | select(type == "string" and . != "" and . != "null")' \
      "$work/receipts/firewall-ownership.json")"
    placement_key="openclaw-enterprise/platform/receipts/${evidence_source_sha}/placement/${placement_run_id}.json"
    load_receipt "$placement_key" "$work/receipts/placement.json" "$placement_version"
    jq -e -s --arg releaseSha "$RELEASE_SOURCE_SHA" --arg releaseRun "$RELEASE_RUN_ID" \
      --arg cleanupRun "$CLEANUP_RUN_ID" --arg captureRun "$capture_run_id" \
      --arg evidenceSha "$evidence_source_sha" --arg admissionRun "$admission_run_id" \
      --arg placementRun "$placement_run_id" --arg placementVersion "$placement_version" '
      .[0] as $attempt | .[1] as $cleanup | .[2] as $ownership | .[3] as $placement |
      ($cleanup.format == 1 and $cleanup.stage == "owned-firewall-cleanup" and
       $cleanup.status == "verified" and $cleanup.verified == true and
       $cleanup.sourceSha == $releaseSha and $cleanup.captureRunId == $captureRun and
       ($cleanup.cleanupPodUid | type == "string" and . != "") and
       $ownership.format == 1 and $ownership.verified == true and
       $ownership.sourceSha == $releaseSha and $ownership.evidenceSourceSha == $evidenceSha and
       $ownership.captureRunId == $captureRun and $ownership.admissionRunId == $admissionRun and
       $ownership.placementRunId == $placementRun and
       $ownership.placementVersionId == $placementVersion and
       $placement.format == 1 and $placement.verified == true and
       $placement.sourceSha == $evidenceSha and $placement.placementRunId == $placementRun and
       $attempt.format == 1 and $attempt.stage == "canary-release" and
       $attempt.status == "attempted" and $attempt.verified == false and
       $attempt.sourceSha == $releaseSha and $attempt.runId == $releaseRun and
       $attempt.cleanupRunId == $cleanupRun and $attempt.captureRunId == $captureRun and
       $attempt.evidenceSourceSha == $evidenceSha and $attempt.admissionRunId == $admissionRun and
       $attempt.placementRunId == $placementRun and
       $attempt.placementVersionId == $placementVersion and
       $attempt.cleanupPodUid == $cleanup.cleanupPodUid and
       $attempt.node == $placement.node and $attempt.nodeUid == $placement.nodeUid and
       $attempt.bootID == $placement.bootID and
       $cleanup.node == $placement.node and $cleanup.nodeUid == $placement.nodeUid and
       $cleanup.bootID == $placement.bootID and
       $ownership.node == $placement.node and $ownership.nodeUid == $placement.nodeUid and
       $ownership.bootID == $placement.bootID)' \
      "$work/receipts/release-attempt.json" "$work/receipts/cleanup.json" \
      "$work/receipts/firewall-ownership.json" "$work/receipts/placement.json" >/dev/null
    node="$(jq -er '.node | select(type == "string" and . != "")' "$work/receipts/placement.json")"
    node_uid="$(jq -er '.nodeUid | select(type == "string" and . != "")' "$work/receipts/placement.json")"
    boot_id="$(jq -er '.bootID | select(type == "string" and . != "")' "$work/receipts/placement.json")"
    cleanup_pod_uid="$(jq -er '.cleanupPodUid | select(type == "string" and . != "")' "$work/receipts/cleanup.json")"
    pod_token="$(openssl rand -hex 24)"
    jq -n --arg sourceSha "$GITHUB_SHA" --arg runId "$GITHUB_RUN_ID" \
      --arg releaseSourceSha "$RELEASE_SOURCE_SHA" --arg releaseRunId "$RELEASE_RUN_ID" \
      --arg cleanupRunId "$CLEANUP_RUN_ID" --arg captureRunId "$capture_run_id" \
      --arg evidenceSourceSha "$evidence_source_sha" --arg admissionRunId "$admission_run_id" \
      --arg placementRunId "$placement_run_id" --arg placementVersionId "$placement_version" \
      --arg cleanupPodUid "$cleanup_pod_uid" --arg node "$node" --arg nodeUid "$node_uid" \
      --arg bootID "$boot_id" --arg podToken "$pod_token" \
      '{format: 1, stage: "canary-release-recover", status: "attempted", verified: false,
        sourceSha: $sourceSha, runId: $runId, releaseSourceSha: $releaseSourceSha,
        releaseRunId: $releaseRunId, cleanupRunId: $cleanupRunId,
        captureRunId: $captureRunId, evidenceSourceSha: $evidenceSourceSha,
        admissionRunId: $admissionRunId, placementRunId: $placementRunId,
        placementVersionId: $placementVersionId, cleanupPodUid: $cleanupPodUid,
        node: $node, nodeUid: $nodeUid, bootID: $bootID, podToken: $podToken}' \
      >"$work/receipts/recovery-attempt.json"
    chmod 600 "$work/receipts/recovery-attempt.json"
    retain_result "$work/receipts/recovery-attempt.json" canary-release-recover-attempt
    if ! python3 -I scripts/network-policy-firewall-baseline.py --config "$config" \
      --expected-sha "$GITHUB_SHA" --bucket "$bucket" --release-recovery \
      --evidence-source-sha "$evidence_source_sha" \
      --recovery-placement "$work/receipts/placement.json" \
      --attempt "$work/receipts/recovery-attempt.json" \
      --output "$work/receipts/firewall-recovery-proof.json"; then
      if [[ -f "$work/receipts/firewall-recovery-proof.json" &&
            ! -L "$work/receipts/firewall-recovery-proof.json" ]]; then
        retain_result "$work/receipts/firewall-recovery-proof.json" firewall-recovery-interrupted
      fi
      exit 1
    fi
    retain_result "$work/receipts/firewall-recovery-proof.json" firewall-recovery-proof
    load_receipt "$release_key" "$work/receipts/release-readback.json" "$release_version"
    cmp "$work/receipts/release-attempt.json" "$work/receipts/release-readback.json"
    load_receipt "$cleanup_key" "$work/receipts/cleanup-readback.json" "$cleanup_version"
    cmp "$work/receipts/cleanup.json" "$work/receipts/cleanup-readback.json"
    load_receipt "$ownership_key" "$work/receipts/ownership-readback.json" "$ownership_version"
    cmp "$work/receipts/firewall-ownership.json" "$work/receipts/ownership-readback.json"
    load_receipt "$placement_key" "$work/receipts/placement-readback.json" "$placement_version"
    cmp "$work/receipts/placement.json" "$work/receipts/placement-readback.json"
    if ! python3 -I scripts/network-policy-canary-node.py release-recover \
      --config "$config" --expected-sha "$GITHUB_SHA" --bucket "$bucket" \
      --release-source-sha "$RELEASE_SOURCE_SHA" --release-run-id "$RELEASE_RUN_ID" \
      --cleanup-run-id "$CLEANUP_RUN_ID" --evidence-source-sha "$evidence_source_sha" \
      --admission-run-id "$admission_run_id" --receipt-dir "$work/receipts" \
      --output "$work/canary.json"; then
      if [[ -f "$work/canary.json" && ! -L "$work/canary.json" ]]; then
        retain_result "$work/canary.json" canary-release-recover-interrupted
      fi
      exit 1
    fi
    retain_result "$work/canary.json" canary-release-recover
    ;;
  canary-admit-recover|canary-abort)
    bash scripts/ci/install-kubeconfig.sh
    kubectl auth can-i create pods -n kube-system --quiet
    kubectl auth can-i create pods/exec -n kube-system --quiet
    kubectl auth can-i delete pods -n kube-system --quiet
    kubectl auth can-i get pods -n kube-system --quiet
    kubectl auth can-i list pods --all-namespaces --quiet
    kubectl auth can-i get nodes --quiet
    kubectl auth can-i list nodes --quiet
    install -m 0700 -d "$work/receipts"
    load_receipt "openclaw-enterprise/platform/${EVIDENCE_SOURCE_SHA}/${ADMISSION_RUN_ID}/canary-admit-attempt.json" \
      "$work/receipts/admission-attempt.json"
    jq -e --arg sourceSha "$EVIDENCE_SOURCE_SHA" --arg runId "$ADMISSION_RUN_ID" \
      '.format == 1 and .stage == "canary-admit" and .status == "attempted" and
       .verified == false and .sourceSha == $sourceSha and .runId == $runId' \
      "$work/receipts/admission-attempt.json" >/dev/null
    admission_key="openclaw-enterprise/platform/${EVIDENCE_SOURCE_SHA}/${ADMISSION_RUN_ID}/canary-admit.json"
    admission_version=
    if [[ "$stage" == canary-abort ]]; then
      load_receipt "$admission_key" "$work/receipts/admission.json"
      admission_version="$loaded_receipt_version"
      git rev-list --first-parent "$GITHUB_SHA" | grep -Fx "$EVIDENCE_SOURCE_SHA" >/dev/null || exit 1
      git diff --quiet "$EVIDENCE_SOURCE_SHA" "$GITHUB_SHA" -- \
        clusters/homelab/platform/network-policy/preflight/pod.json \
        clusters/homelab/platform/network-policy/daemonset.yaml \
        clusters/homelab/platform/network-policy/canary/fixtures.yaml \
        clusters/homelab/platform/network-policy/kustomization.yaml \
        clusters/homelab/platform/network-policy/canary/kustomization.yaml \
        IaC/homelab/us-west-2/apps/platform-network-policy/stack.hcl \
        IaC/homelab/us-west-2/apps/platform-network-policy-canary/stack.hcl || exit 1
    else
      require_absent_receipt "$admission_key"
    fi
    placement_run_id="$(jq -er '.placementRunId | select(type == "string" and test("^[1-9][0-9]*$"))' \
      "$work/receipts/admission-attempt.json")"
    placement_version="$(jq -er '.placementVersionId | select(type == "string" and . != "" and . != "null")' \
      "$work/receipts/admission-attempt.json")"
    load_receipt "openclaw-enterprise/platform/receipts/${EVIDENCE_SOURCE_SHA}/placement/${placement_run_id}.json" \
      "$work/receipts/placement.json" "$placement_version"
    node="$(jq -er '.node | select(type == "string" and . != "")' "$work/receipts/placement.json")"
    node_uid="$(jq -er '.nodeUid | select(type == "string" and . != "")' "$work/receipts/placement.json")"
    boot_id="$(jq -er '.bootID | select(type == "string" and . != "")' "$work/receipts/placement.json")"
    pod_token="$(openssl rand -hex 24)"
    jq -n --arg sourceSha "$GITHUB_SHA" --arg evidenceSourceSha "$EVIDENCE_SOURCE_SHA" \
      --arg runId "$GITHUB_RUN_ID" \
      --arg admissionRunId "$ADMISSION_RUN_ID" --arg placementRunId "$placement_run_id" \
      --arg placementVersionId "$placement_version" --arg node "$node" \
      --arg nodeUid "$node_uid" --arg bootID "$boot_id" --arg podToken "$pod_token" \
      --arg stage "$stage" \
      '{format: 1, stage: $stage, status: "attempted", verified: false,
        sourceSha: $sourceSha, evidenceSourceSha: $evidenceSourceSha,
        runId: $runId, admissionRunId: $admissionRunId,
        placementRunId: $placementRunId, placementVersionId: $placementVersionId,
        node: $node, nodeUid: $nodeUid, bootID: $bootID, podToken: $podToken}' \
      >"$work/recovery-attempt.json"
    chmod 600 "$work/recovery-attempt.json"
    retain_result "$work/recovery-attempt.json" canary-admit-recover-attempt
    if ! python3 -I scripts/network-policy-firewall-baseline.py --config "$config" \
      --expected-sha "$GITHUB_SHA" --bucket "$bucket" \
      --evidence-source-sha "$EVIDENCE_SOURCE_SHA" \
      --recovery-placement "$work/receipts/placement.json" \
      --attempt "$work/recovery-attempt.json" \
      --output "$work/receipts/firewall-recovery-proof.json"; then
      if [[ -f "$work/receipts/firewall-recovery-proof.json" &&
            ! -L "$work/receipts/firewall-recovery-proof.json" ]]; then
        retain_result "$work/receipts/firewall-recovery-proof.json" firewall-recovery-interrupted
      fi
      exit 1
    fi
    retain_result "$work/receipts/firewall-recovery-proof.json" firewall-recovery-proof
    if [[ "$stage" == canary-abort ]]; then
      load_receipt "$admission_key" "$work/receipts/admission-readback.json" "$admission_version"
      cmp "$work/receipts/admission.json" "$work/receipts/admission-readback.json"
      action=abort
      admission_args=(--admission-version-id "$admission_version")
    else
      require_absent_receipt "$admission_key"
      action=recover
      admission_args=()
    fi
    if ! python3 -I scripts/network-policy-canary-node.py "$action" \
      --config "$config" --expected-sha "$GITHUB_SHA" --bucket "$bucket" \
      --evidence-source-sha "$EVIDENCE_SOURCE_SHA" \
      --admission-run-id "$ADMISSION_RUN_ID" \
      --placement-run-id "$placement_run_id" --placement-version-id "$placement_version" \
      "${admission_args[@]}" \
      --receipt-dir "$work/receipts" --output "$work/canary-recovery.json"; then
      if [[ -f "$work/canary-recovery.json" && ! -L "$work/canary-recovery.json" ]]; then
        retain_result "$work/canary-recovery.json" "${stage}-interrupted"
      fi
      exit 1
    fi
    retain_result "$work/canary-recovery.json" "$stage"
    ;;
  qualify)
    [[ -n "${OCTELIUM_AUTH_TOKEN:-}" ]] || exit 1
    bash scripts/ci/install-kubeconfig.sh
    python3 scripts/network-policy-qualification.py --config "$config" --output "$work/qualification.json"
    retain_result "$work/qualification.json" qualification
    ;;
  ownership-capture|ownership-approve)
    [[ -n "${OCTELIUM_AUTH_TOKEN:-}" ]] || exit 1
    bash scripts/ci/install-kubeconfig.sh
    if [[ "$stage" == ownership-capture ]]; then
      [[ "${ADMISSION_RUN_ID:-}" =~ ^[1-9][0-9]*$ ]] || exit 2
      python3 -I scripts/network-policy-ownership.py capture --config "$config" \
        --expected-sha "$GITHUB_SHA" --bucket "$bucket" \
        --evidence-source-sha "${EVIDENCE_SOURCE_SHA:-}" \
        --qualification-run-id "${QUALIFICATION_RUN_ID:-}" \
        --admission-run-id "${ADMISSION_RUN_ID:-}"
    else
      python3 -I scripts/network-policy-ownership.py approve --config "$config" \
        --expected-sha "$GITHUB_SHA" --bucket "$bucket" \
        --capture-run-id "${CAPTURE_RUN_ID:-}" \
        --reviewed-snapshot-sha256 "${REVIEWED_SNAPSHOT_SHA256:-}"
    fi
    ;;
  owned-cleanup)
    [[ -n "${OCTELIUM_AUTH_TOKEN:-}" ]] || exit 1
    bash scripts/ci/install-kubeconfig.sh
    install -m 0700 -d "$work/receipts"
    [[ "${CAPTURE_RUN_ID:-}" =~ ^[1-9][0-9]*$ ]] || exit 1
    load_receipt "openclaw-enterprise/platform/receipts/${GITHUB_SHA}/firewall-ownership/${CAPTURE_RUN_ID}.json" \
      "$work/receipts/firewall-ownership.json"
    evidence_source_sha="$(jq -er '.evidenceSourceSha | select(type == "string" and test("^[0-9a-f]{40}$"))' \
      "$work/receipts/firewall-ownership.json")"
    placement_run_id="$(jq -er '.placementRunId | select(type == "string" and test("^[1-9][0-9]*$"))' \
      "$work/receipts/firewall-ownership.json")"
    placement_version="$(jq -er '.placementVersionId | select(type == "string" and . != "" and . != "null")' \
      "$work/receipts/firewall-ownership.json")"
    load_receipt "openclaw-enterprise/platform/receipts/${evidence_source_sha}/placement/${placement_run_id}.json" \
      "$work/receipts/placement.json" "$placement_version"
    # A versioned private attempt must exist before any firewall operation.
    # If the final upload fails, this marker still requires direct review.
    jq -n --arg sourceSha "$GITHUB_SHA" --arg runId "$GITHUB_RUN_ID" \
      --arg captureRunId "$CAPTURE_RUN_ID" \
      '{format: 1, stage: "owned-firewall-cleanup", status: "attempted", verified: false,
        sourceSha: $sourceSha, runId: $runId, captureRunId: $captureRunId}' >"$work/cleanup-attempt.json"
    chmod 600 "$work/cleanup-attempt.json"
    retain_result "$work/cleanup-attempt.json" cleanup-attempt
    if ! python3 scripts/network-policy-cleanup.py --config "$config" \
      --expected-sha "$GITHUB_SHA" --capture-run-id "$CAPTURE_RUN_ID" \
      --receipt-dir "$work/receipts" \
      --output "$work/cleanup.json"; then
      if [[ -f "$work/cleanup.json" && ! -L "$work/cleanup.json" ]]; then
        retain_result "$work/cleanup.json" cleanup-interrupted
      fi
      exit 1
    fi
    retain_result "$work/cleanup.json" cleanup
    ;;
  talos-*|kubernetes-*)
    [[ -n "${OCE_CONTROLPLANE_CONFIG_B64:-}" && -n "${OCE_WORKER_CONFIG_B64:-}" ]] || exit 1
    connect_talos
    printf %s "$OCE_CONTROLPLANE_CONFIG_B64" | base64 --decode >"$work/controlplane.yaml"
    printf %s "$OCE_WORKER_CONFIG_B64" | base64 --decode >"$work/worker.yaml"
    chmod 600 "$work/controlplane.yaml" "$work/worker.yaml"
    install -m 0700 -d "$work/receipts"
    if ! python3 -I scripts/platform-maintenance.py execute --config "$config" \
      --stage "$stage" --expected-sha "$GITHUB_SHA" \
      --talosconfig "$work/talosconfig" \
      --control-plane-config "$work/controlplane.yaml" \
      --worker-config "$work/worker.yaml" \
      --receipt-dir "$work/receipts" --output "$work/upgrade-error.json"; then
      if [[ -f "$work/upgrade-error.json" && ! -L "$work/upgrade-error.json" ]]; then
        retain_result "$work/upgrade-error.json" upgrade-error
      fi
      exit 1
    fi
    retain_result "$work/receipts/$stage.json" "$stage"
    ;;
esac
