#!/usr/bin/env bash
set -euo pipefail
umask 077

[[ "${GITHUB_ACTIONS:-}" == true &&
   "${GITHUB_REPOSITORY:-}" == Stuhlmuller/homelab &&
   "${GITHUB_REF:-}" == refs/heads/main &&
   "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ &&
   "${EXPECTED_SHA:-}" == "$GITHUB_SHA" &&
   "${EXPECTED_PVC_UID:-}" =~ ^[0-9a-f-]{36}$ &&
   "${EXPECTED_PV_UID:-}" =~ ^[0-9a-f-]{36}$ &&
   "${OBJECT_SHA256:-}" =~ ^[0-9a-f]{64}$ &&
   "${OBJECT_BYTES:-}" =~ ^[1-9][0-9]*$ &&
   "$OBJECT_BYTES" -lt 1073741824 &&
   "${OBJECT_VERSION:-}" =~ ^[A-Za-z0-9._~+/=-]+$ &&
   "${OBJECT_VERSION:-}" != null &&
   "${GITHUB_RUN_ID:-}" =~ ^[1-9][0-9]*$ &&
   "${GITHUB_RUN_ATTEMPT:-}" =~ ^[1-9][0-9]*$ ]] || exit 2
key_pattern="^langfuse/postgresql/${EXPECTED_SHA}/[1-9][0-9]*/1/langfuse[.]dump$"
[[ "${OBJECT_KEY:-}" =~ $key_pattern ]] || exit 2
[[ "$GITHUB_SHA" == "$(gh api repos/Stuhlmuller/homelab/git/ref/heads/main --jq .object.sha)" ]] || exit 1

bucket="$(sed -nE 's/^[[:space:]]*bucket[[:space:]]*=[[:space:]]*"([a-z0-9-]+)"[[:space:]]*$/\1/p' IaC/application-backup-storage.hcl)"
[[ "$bucket" =~ ^homelab-application-backups-([0-9]{12})-us-east-1$ ]] || exit 1
account="${BASH_REMATCH[1]}"
[[ "$(aws --region us-east-1 sts get-caller-identity --query Account --output text)" == "$account" ]] || exit 1
[[ "$(aws --region us-east-1 s3api get-bucket-versioning --bucket "$bucket" --expected-bucket-owner "$account" --query Status --output text)" == Enabled ]] || exit 1
[[ "$(aws --region us-east-1 s3api get-bucket-encryption --bucket "$bucket" --expected-bucket-owner "$account" --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' --output text)" == aws:kms ]] || exit 1

image="$(yq -r 'select(.kind == "Deployment" and .metadata.name == "langfuse-postgres") | .spec.template.spec.containers[] | select(.name == "postgres") | .image' clusters/homelab/apps/langfuse/datastores.yaml)"
[[ "$image" =~ ^harbor\.stinkyboi\.com/mirror/docker\.io/pgvector/pgvector:[^@]+@sha256:[0-9a-f]{64}$ ]] || exit 1
checksum="$(python3 - "$OBJECT_SHA256" <<'PY'
import base64
import sys

print(base64.b64encode(bytes.fromhex(sys.argv[1])).decode())
PY
)"

work="$(mktemp -d)"
container=
volume=
cleanup() {
  if [[ -n "$container" ]]; then docker rm -f "$container" >/dev/null 2>&1 || true; fi
  if [[ -n "$volume" ]]; then docker volume rm -f "$volume" >/dev/null 2>&1 || true; fi
  rm -rf -- "$work"
}
trap cleanup EXIT

head="$(aws --region us-east-1 s3api head-object --bucket "$bucket" --key "$OBJECT_KEY" \
  --expected-bucket-owner "$account" --version-id "$OBJECT_VERSION" --checksum-mode ENABLED)"
jq -e --arg version "$OBJECT_VERSION" --arg checksum "$checksum" \
  --argjson bytes "$OBJECT_BYTES" --arg revision "$EXPECTED_SHA" \
  --arg pvc "$EXPECTED_PVC_UID" --arg pv "$EXPECTED_PV_UID" '
    .VersionId == $version and .ChecksumSHA256 == $checksum and
    .ContentLength == $bytes and .ServerSideEncryption == "aws:kms" and
    .Metadata["source-revision"] == $revision and
    .Metadata["source-pvc-uid"] == $pvc and .Metadata["source-pv-uid"] == $pv
  ' <<<"$head" >/dev/null
aws --region us-east-1 s3api get-object --bucket "$bucket" --key "$OBJECT_KEY" \
  --expected-bucket-owner "$account" --version-id "$OBJECT_VERSION" --checksum-mode ENABLED \
  "$work/retrieved.dump" >"$work/readback.json"
jq -e --arg version "$OBJECT_VERSION" --arg checksum "$checksum" \
  --argjson bytes "$OBJECT_BYTES" --arg revision "$EXPECTED_SHA" \
  --arg pvc "$EXPECTED_PVC_UID" --arg pv "$EXPECTED_PV_UID" '
    .VersionId == $version and .ChecksumSHA256 == $checksum and
    .ContentLength == $bytes and .ServerSideEncryption == "aws:kms" and
    .Metadata["source-revision"] == $revision and
    .Metadata["source-pvc-uid"] == $pvc and .Metadata["source-pv-uid"] == $pv
  ' "$work/readback.json" >/dev/null
[[ "$(sha256sum "$work/retrieved.dump" | cut -d' ' -f1)" == "$OBJECT_SHA256" ]] || exit 1

volume="langfuse-checkpoint-restore-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
docker volume create "$volume" >/dev/null
container="$(docker run --detach --rm --network none \
  --mount "type=volume,src=$volume,dst=/var/lib/postgresql/data" \
  --mount "type=bind,src=$work/retrieved.dump,dst=/checkpoint.dump,readonly" \
  --env POSTGRES_DB=langfuse --env POSTGRES_USER=langfuse \
  --env POSTGRES_HOST_AUTH_METHOD=trust "$image")"
ready=false
for _ in {1..60}; do
  if docker exec "$container" pg_isready -h 127.0.0.1 -U langfuse -d langfuse >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 2
done
[[ "$ready" == true ]] || exit 1
docker exec "$container" pg_restore --clean --if-exists --exit-on-error \
  --no-owner --no-privileges -U langfuse -d langfuse /checkpoint.dump >/dev/null
tables="$(docker exec "$container" psql -XAt -w -U langfuse -d langfuse \
  -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")"
[[ "$tables" =~ ^[1-9][0-9]*$ ]] || exit 1
[[ "$GITHUB_SHA" == "$(gh api repos/Stuhlmuller/homelab/git/ref/heads/main --jq .object.sha)" ]] || exit 1

printf 'Verified Langfuse PostgreSQL checkpoint: key=%s version=%s sha256=%s bytes=%s tables=%s pvc_uid=%s pv=%s pv_uid=%s\n' \
  "$OBJECT_KEY" "$OBJECT_VERSION" "$OBJECT_SHA256" "$OBJECT_BYTES" "$tables" \
  "$EXPECTED_PVC_UID" "pvc-$EXPECTED_PVC_UID" "$EXPECTED_PV_UID" >"${RUNNER_TEMP:?}/langfuse-checkpoint-receipt"
