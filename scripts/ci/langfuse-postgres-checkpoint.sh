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
   "${GITHUB_RUN_ID:-}" =~ ^[1-9][0-9]*$ &&
   "${GITHUB_RUN_ATTEMPT:-}" =~ ^[1-9][0-9]*$ ]] || exit 2
[[ "$GITHUB_SHA" == "$(gh api repos/Stuhlmuller/homelab/git/ref/heads/main --jq .object.sha)" ]] || exit 1

bucket="$(sed -nE 's/^[[:space:]]*bucket[[:space:]]*=[[:space:]]*"([a-z0-9-]+)"[[:space:]]*$/\1/p' IaC/application-backup-storage.hcl)"
[[ "$bucket" =~ ^homelab-application-backups-([0-9]{12})-us-east-1$ ]] || exit 1
account="${BASH_REMATCH[1]}"
[[ "$(aws --region us-east-1 sts get-caller-identity --query Account --output text)" == "$account" ]] || exit 1
[[ "$(aws --region us-east-1 s3api get-bucket-versioning --bucket "$bucket" --expected-bucket-owner "$account" --query Status --output text)" == Enabled ]] || exit 1
[[ "$(aws --region us-east-1 s3api get-bucket-encryption --bucket "$bucket" --expected-bucket-owner "$account" --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' --output text)" == aws:kms ]] || exit 1

image="$(yq -r 'select(.kind == "Deployment" and .metadata.name == "langfuse-postgres") | .spec.template.spec.containers[] | select(.name == "postgres") | .image' clusters/homelab/apps/langfuse/datastores.yaml)"
[[ "$image" =~ ^pgvector/pgvector:pg17@sha256:[0-9a-f]{64}$ ]] || exit 1
[[ "$(kubectl auth can-i get deployments -n langfuse)" == yes ]] || exit 1
[[ "$(kubectl auth can-i get pods -n langfuse)" == yes ]] || exit 1
[[ "$(kubectl auth can-i get replicasets -n langfuse)" == yes ]] || exit 1
[[ "$(kubectl auth can-i get persistentvolumeclaims -n langfuse)" == yes ]] || exit 1
[[ "$(kubectl auth can-i get persistentvolumes)" == yes ]] || exit 1
[[ "$(kubectl auth can-i create pods/exec -n langfuse)" == yes ]] || exit 1
select_deployment() {
  kubectl -n langfuse get deployment langfuse-postgres -o json |
    jq -er --arg image "$image" '
      select(.spec.replicas == 1 and .status.readyReplicas == 1 and
        .status.updatedReplicas == 1 and .status.observedGeneration == .metadata.generation and
        ([.spec.template.spec.containers[] | select(.name == "postgres" and .image == $image and
          ([.volumeMounts[] | select(.name == "data" and .mountPath == "/var/lib/postgresql/data")] | length == 1))] | length == 1) and
        ([.spec.template.spec.volumes[] | select(.name == "data" and
          .persistentVolumeClaim.claimName == "langfuse-postgres-data")] | length == 1)) |
      .metadata.uid'
}
deployment_uid="$(select_deployment)"
[[ "$deployment_uid" =~ ^[0-9a-f-]{36}$ ]] || exit 1

select_binding() {
  local claim_record claim_uid pv_name pv_uid
  claim_record="$(kubectl -n langfuse get pvc langfuse-postgres-data -o json |
    jq -er '
      select(.kind == "PersistentVolumeClaim" and .metadata.namespace == "langfuse" and
        .metadata.name == "langfuse-postgres-data" and .metadata.deletionTimestamp == null and
        .status.phase == "Bound" and
        .spec.storageClassName == "nfs-default" and .spec.accessModes == ["ReadWriteOnce"]) |
      [.metadata.uid, .spec.volumeName] | @tsv')"
  IFS=$'\t' read -r claim_uid pv_name <<<"$claim_record"
  [[ "$claim_uid" == "$EXPECTED_PVC_UID" && "$pv_name" == "pvc-$claim_uid" ]] || return 1
  pv_uid="$(kubectl get pv "$pv_name" -o json |
    jq -er --arg name "$pv_name" --arg claim_uid "$claim_uid" '
      select(.kind == "PersistentVolume" and .metadata.name == $name and
        .metadata.deletionTimestamp == null and
        .status.phase == "Bound" and .spec.storageClassName == "nfs-default" and
        .spec.persistentVolumeReclaimPolicy == "Retain" and
        .spec.nfs.server == "10.1.0.2" and
        .spec.nfs.path == ("/homelab/langfuse-langfuse-postgres-data-pvc-" + $claim_uid) and
        .spec.claimRef.namespace == "langfuse" and
        .spec.claimRef.name == "langfuse-postgres-data" and
        .spec.claimRef.uid == $claim_uid) | .metadata.uid')"
  [[ "$pv_uid" == "$EXPECTED_PV_UID" ]] || return 1
  printf '%s\t%s\t%s\n' "$claim_uid" "$pv_name" "$pv_uid"
}
binding_record="$(select_binding)"
IFS=$'\t' read -r claim_uid pv_name pv_uid <<<"$binding_record"

select_pod() {
  kubectl -n langfuse get pods --chunk-size=0 \
    -l 'app.kubernetes.io/name=langfuse,app.kubernetes.io/instance=langfuse,app.kubernetes.io/component=postgresql' -o json |
    jq -er --arg image "$image" '
      select(.kind == "PodList" and
        (.metadata.resourceVersion | type == "string" and . != "" and . != "0") and
        (.metadata.continue // "") == "" and (.items | type == "array")) |
      .items | if length == 1 then .[0] else error("expected exactly one PostgreSQL Pod") end |
      select(.metadata.deletionTimestamp == null and .status.phase == "Running" and
        ([.spec.containers[] | select(.name == "postgres" and .image == $image and
          ([.volumeMounts[] | select(.name == "data" and .mountPath == "/var/lib/postgresql/data")] | length == 1))] | length == 1) and
        ([.spec.volumes[] | select(.name == "data" and
          .persistentVolumeClaim.claimName == "langfuse-postgres-data")] | length == 1) and
        ([.status.containerStatuses[] | select(.name == "postgres" and .ready == true)] | length == 1)) |
      ([.metadata.ownerReferences[]? | select(.controller == true and .kind == "ReplicaSet")] ) as $owners |
      select($owners | length == 1) |
      [.metadata.name, .metadata.uid, $owners[0].name, $owners[0].uid] | @tsv'
}
pod_record="$(select_pod)"
read -r pod pod_uid replica_set replica_set_uid <<<"$pod_record"
[[ "$pod" =~ ^langfuse-postgres-[a-z0-9-]+$ && "$pod_uid" =~ ^[0-9a-f-]{36}$ &&
   "$replica_set" =~ ^langfuse-postgres-[a-z0-9]+$ && "$replica_set_uid" =~ ^[0-9a-f-]{36}$ ]] || exit 1
verify_replica_set() {
  kubectl -n langfuse get replicaset "$replica_set" -o json |
    jq -e --arg uid "$replica_set_uid" --arg deployment "$deployment_uid" '
      .metadata.uid == $uid and
      ([.metadata.ownerReferences[]? | select(.controller == true and .kind == "Deployment" and
        .name == "langfuse-postgres" and .uid == $deployment)] | length == 1)' >/dev/null
}
verify_replica_set

# shortcut: one GiB bound fits single PUT and hosted-runner scratch; use multipart and larger runner if this database grows.
database_bytes="$(kubectl -n langfuse exec "$pod" -c postgres -- \
  psql -XAt -w -U langfuse -d langfuse -c 'SELECT pg_database_size(current_database())')"
[[ "$database_bytes" =~ ^[1-9][0-9]*$ && "$database_bytes" -lt 1073741824 ]] || exit 1

work="$(mktemp -d)"
container=
volume=
cleanup() {
  if [[ -n "$container" ]]; then docker rm -f "$container" >/dev/null 2>&1 || true; fi
  if [[ -n "$volume" ]]; then docker volume rm -f "$volume" >/dev/null 2>&1 || true; fi
  rm -rf -- "$work"
}
trap cleanup EXIT

kubectl -n langfuse exec "$pod" -c postgres -- \
  pg_dump --format=custom --no-owner --no-privileges --no-password \
  -U langfuse -d langfuse >"$work/langfuse.dump"
[[ "$(select_deployment)" == "$deployment_uid" && "$(select_pod)" == "$pod_record" ]] || exit 1
verify_replica_set
[[ "$(select_binding)" == "$binding_record" ]] || exit 1
bytes="$(wc -c <"$work/langfuse.dump" | tr -d '[:space:]')"
[[ "$bytes" =~ ^[1-9][0-9]*$ && "$bytes" -lt 1073741824 ]] || exit 1
checksum="$(openssl dgst -sha256 -binary "$work/langfuse.dump" | openssl base64 -A)"
digest="$(sha256sum "$work/langfuse.dump" | cut -d' ' -f1)"

key="langfuse/postgresql/${GITHUB_SHA}/${GITHUB_RUN_ID}/${GITHUB_RUN_ATTEMPT}/langfuse.dump"
aws --region us-east-1 s3api list-object-versions --bucket "$bucket" \
  --expected-bucket-owner "$account" --prefix "$key" --output json |
  jq -e --arg key "$key" '[.Versions[]?, .DeleteMarkers[]?] | all(.Key != $key)' >/dev/null
put="$(aws --region us-east-1 s3api put-object --bucket "$bucket" --key "$key" \
  --expected-bucket-owner "$account" --body "$work/langfuse.dump" \
  --server-side-encryption aws:kms --if-none-match '*' \
  --checksum-algorithm SHA256 --checksum-sha256 "$checksum")"
version="$(jq -er '.VersionId | select(type == "string" and . != "" and . != "null")' <<<"$put")"
head="$(aws --region us-east-1 s3api head-object --bucket "$bucket" --key "$key" \
  --expected-bucket-owner "$account" --version-id "$version" --checksum-mode ENABLED)"
jq -e --arg version "$version" --arg checksum "$checksum" --argjson bytes "$bytes" \
  '.VersionId == $version and .ChecksumSHA256 == $checksum and
    .ContentLength == $bytes and .ServerSideEncryption == "aws:kms"' <<<"$head" >/dev/null
aws --region us-east-1 s3api get-object --bucket "$bucket" --key "$key" \
  --expected-bucket-owner "$account" --version-id "$version" --checksum-mode ENABLED \
  "$work/retrieved.dump" >"$work/readback.json"
jq -e --arg version "$version" --arg checksum "$checksum" --argjson bytes "$bytes" \
  '.VersionId == $version and .ChecksumSHA256 == $checksum and
    .ContentLength == $bytes and .ServerSideEncryption == "aws:kms"' "$work/readback.json" >/dev/null
[[ "$(sha256sum "$work/retrieved.dump" | cut -d' ' -f1)" == "$digest" ]] || exit 1

volume="langfuse-checkpoint-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
docker volume create "$volume" >/dev/null
container="$(docker run --detach --rm --network none \
  --mount "type=volume,src=$volume,dst=/var/lib/postgresql/data" \
  --mount "type=bind,src=$work/retrieved.dump,dst=/checkpoint.dump,readonly" \
  --env POSTGRES_DB=langfuse --env POSTGRES_USER=langfuse \
  --env POSTGRES_HOST_AUTH_METHOD=trust "$image")"
ready=false
# The temporary init server accepts sockets before the final server starts.
for _ in {1..60}; do
  if docker exec "$container" pg_isready -h 127.0.0.1 -U langfuse -d langfuse >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 2
done
[[ "$ready" == true ]] || exit 1
docker exec "$container" pg_restore --clean --if-exists --exit-on-error \
  --no-owner --no-privileges \
  -U langfuse -d langfuse /checkpoint.dump >/dev/null
tables="$(docker exec "$container" psql -XAt -w -U langfuse -d langfuse \
  -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")"
[[ "$tables" =~ ^[1-9][0-9]*$ ]] || exit 1
[[ "$(select_binding)" == "$binding_record" ]] || exit 1

printf 'Verified Langfuse PostgreSQL checkpoint: key=%s version=%s sha256=%s bytes=%s tables=%s pvc_uid=%s pv=%s pv_uid=%s\n' \
  "$key" "$version" "$digest" "$bytes" "$tables" "$claim_uid" "$pv_name" "$pv_uid" >"${RUNNER_TEMP:?}/langfuse-checkpoint-receipt"
