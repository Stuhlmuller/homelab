#!/usr/bin/env bash
set -euo pipefail
umask 077

uuid='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_REPOSITORY:-}" == Stuhlmuller/homelab &&
   "${GITHUB_REF:-}" == refs/heads/main && "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ &&
   "${EXPECTED_SHA:-}" == "$GITHUB_SHA" && "${EXPECTED_N8N_PVC_UID:-}" =~ $uuid &&
   "${EXPECTED_N8N_PV_UID:-}" =~ $uuid && "${EXPECTED_PG_PVC_UID:-}" =~ $uuid &&
   "${EXPECTED_PG_PV_UID:-}" =~ $uuid && "${GITHUB_RUN_ID:-}" =~ ^[1-9][0-9]*$ &&
   "${GITHUB_RUN_ATTEMPT:-}" =~ ^[1-9][0-9]*$ ]] || exit 2
checked_equal() {
  local expected="$1" actual
  shift
  actual="$("$@")" || return 1
  [[ "$actual" == "$expected" ]]
}
checked_equal "$GITHUB_SHA" git rev-parse HEAD || exit 1
checked_equal "$GITHUB_SHA" gh api repos/Stuhlmuller/homelab/git/ref/heads/main --jq .object.sha || exit 1

kubectl_bin="$(command -v kubectl)"
[[ -x "$kubectl_bin" ]] || exit 1
kubectl() {
  timeout --signal=TERM --kill-after=10s 45s \
    "$kubectl_bin" --request-timeout=30s "$@"
}

stack=IaC/homelab/us-west-2/apps/n8n/stack.hcl
job_manifest=clusters/homelab/apps/n8n/checkpoint-reader.job.yaml
policy_manifest=clusters/homelab/apps/n8n/checkpoint-reader.networkpolicy.yaml
active_revisions="$(rg -N '^[[:space:]]*targetRevision[[:space:]]*=' "$stack" |
  sed -E 's/^[[:space:]]*//; s/[[:space:]]*=[[:space:]]*/ = /')"
expected_revisions=$'targetRevision = "4.4.0"\ntargetRevision = local.shared.target_revision\ntargetRevision = local.shared.target_revision'
[[ "$active_revisions" == "$expected_revisions" ]]
active_value_files="$(rg -N '^[[:space:]]*valueFiles[[:space:]]*=' "$stack" |
  sed -E 's/^[[:space:]]*//; s/[[:space:]]*=[[:space:]]*/ = /')"
# shellcheck disable=SC2016 # Helm's literal $values reference is expected here.
[[ "$active_value_files" == 'valueFiles = ["$values/clusters/homelab/apps/n8n/values.yaml", "$values/clusters/homelab/apps/n8n/maintenance-fence.values.yaml"]' ]]
literal_absent() {
  local status=0
  rg -Fq "$1" "$2" || status=$?
  [[ "$status" -eq 1 ]]
}
literal_absent 'migration-v1.values.yaml' "$stack" || exit 1
literal_absent 'migration-github-trigger-v1.values.yaml' "$stack" || exit 1
literal_absent 'checkpoint-reader.job.yaml' clusters/homelab/apps/n8n/kustomization.yaml || exit 1
literal_absent 'checkpoint-reader.networkpolicy.yaml' clusters/homelab/apps/n8n/kustomization.yaml || exit 1

bucket="$(sed -nE 's/^[[:space:]]*bucket[[:space:]]*=[[:space:]]*"([a-z0-9-]+)"[[:space:]]*$/\1/p' IaC/application-backup-storage.hcl)"
[[ "$bucket" =~ ^homelab-application-backups-([0-9]{12})-us-east-1$ ]] || exit 1
account="${BASH_REMATCH[1]}"
checked_equal "$account" aws --region us-east-1 sts get-caller-identity --query Account --output text || exit 1
checked_equal Enabled aws --region us-east-1 s3api get-bucket-versioning --bucket "$bucket" --expected-bucket-owner "$account" --query Status --output text || exit 1
checked_equal aws:kms aws --region us-east-1 s3api get-bucket-encryption --bucket "$bucket" --expected-bucket-owner "$account" --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' --output text || exit 1

for access in \
  'get applications -n argocd' \
  'get deployments -n automation' \
  'get statefulsets -n automation' \
  'get pods -n automation' \
  'list pods -n automation' \
  'get jobs -n automation' \
  'create jobs -n automation' \
  'delete jobs -n automation' \
  'create networkpolicies -n automation' \
  'delete networkpolicies -n automation' \
  'get networkpolicies -n automation' \
  'list jobs -n automation' \
  'list cronjobs -n automation' \
  'get persistentvolumeclaims -n automation' \
  'get persistentvolumes' \
  'create pods/exec -n automation'; do
  read -r -a args <<<"$access"
  checked_equal yes kubectl auth can-i "${args[@]}" || exit 1
done

pg_image="$(yq -r 'select(.kind == "StatefulSet" and .metadata.name == "n8n-postgres") | .spec.template.spec.containers[] | select(.name == "postgres") | .image' clusters/homelab/apps/n8n-postgres/statefulset.yaml)"
[[ "$pg_image" =~ ^harbor\.stinkyboi\.com/mirror/docker\.io/library/postgres:[^@]+@sha256:[0-9a-f]{64}$ ]] || exit 1
reader_image="$(yq -r '.spec.template.spec.containers[] | select(.name == "reader") | .image' "$job_manifest")"
[[ "$reader_image" == harbor.stinkyboi.com/mirror/docker.io/library/busybox:1.38.0@sha256:fd7dc98638c8e305f4dc34e979f1c0fdfdcaeb0fbf8fcff77ae834b6da3d7e6e ]] || exit 1

check_fence() {
  local allowed_reader_uid="${1:-}"
  kubectl -n argocd get application n8n -o json |
    jq -e --arg sha "$GITHUB_SHA" '
      .status.sync.status == "Synced" and .status.health.status == "Healthy" and
      ([.status.sync.revisions[]? | select(. == $sha)] | length) == 2' >/dev/null
  kubectl -n automation get deployment n8n -o json |
    jq -e '.spec.replicas == 0 and (.status.replicas // 0) == 0 and
      (.status.readyReplicas // 0) == 0 and
      .status.observedGeneration == .metadata.generation' >/dev/null
  kubectl get --raw '/api/v1/namespaces/automation/pods?limit=500' |
    jq -e --arg allowed "$allowed_reader_uid" '
      .kind == "PodList" and (.metadata.resourceVersion | type == "string" and . != "" and . != "0") and
      (.metadata.continue // "") == "" and
      ([.items[] | select(.metadata.uid != $allowed) |
        select(.spec.serviceAccountName == "n8n" or
          .metadata.labels["app.kubernetes.io/name"] == "n8n" or
          any(.spec.volumes[]?; .persistentVolumeClaim.claimName == "n8n" or
            .secret.secretName == "n8n-postgres-client"))] | length) == 0' >/dev/null
  kubectl -n automation get jobs,cronjobs -o json |
    jq -e '[.items[] | select(
      (.kind == "Job" and (.status.active // 0) > 0 and
        .spec.template.spec.serviceAccountName == "n8n") or
      (.kind == "CronJob" and .spec.suspend != true and
        .spec.jobTemplate.spec.template.spec.serviceAccountName == "n8n"))] | length == 0' >/dev/null
}

binding() {
  local claim="$1" expected_claim_uid="$2" expected_pv_uid="$3" record claim_uid pv_name pv_uid
  record="$(kubectl -n automation get pvc "$claim" -o json |
    jq -er --arg name "$claim" '
      select(.kind == "PersistentVolumeClaim" and .metadata.namespace == "automation" and
        .metadata.name == $name and .metadata.deletionTimestamp == null and
        .status.phase == "Bound" and .spec.storageClassName == "nfs-default" and
        .spec.accessModes == ["ReadWriteOnce"]) | [.metadata.uid, .spec.volumeName] | @tsv')" || return 1
  IFS=$'\t' read -r claim_uid pv_name <<<"$record"
  [[ "$claim_uid" == "$expected_claim_uid" && "$pv_name" == "pvc-$claim_uid" ]] || return 1
  pv_uid="$(kubectl get pv "$pv_name" -o json |
    jq -er --arg name "$pv_name" --arg claim "$claim" --arg claim_uid "$claim_uid" '
      select(.kind == "PersistentVolume" and .metadata.name == $name and
        .metadata.deletionTimestamp == null and .status.phase == "Bound" and
        .spec.storageClassName == "nfs-default" and
        .spec.persistentVolumeReclaimPolicy == "Retain" and
        .spec.nfs.server == "10.1.0.2" and
        .spec.nfs.path == ("/homelab/automation-" + $claim + "-pvc-" + $claim_uid) and
        .spec.claimRef.namespace == "automation" and .spec.claimRef.name == $claim and
        .spec.claimRef.uid == $claim_uid) | .metadata.uid')" || return 1
  [[ "$pv_uid" == "$expected_pv_uid" ]] || return 1
  printf '%s\t%s\t%s\n' "$claim_uid" "$pv_name" "$pv_uid"
}

pg_state() {
  local stateful_uid
  stateful_uid="$(kubectl -n automation get statefulset n8n-postgres -o json |
    jq -er --arg image "$pg_image" '
      select(.spec.replicas == 1 and .status.readyReplicas == 1 and
        .status.updatedReplicas == 1 and
        .status.observedGeneration == .metadata.generation and
        ([.spec.template.spec.containers[] | select(.name == "postgres" and .image == $image)] | length) == 1 and
        ([.spec.volumeClaimTemplates[] | select(.metadata.name == "data")] | length) == 1) |
      .metadata.uid')" || return 1
  [[ "$stateful_uid" =~ $uuid ]] || return 1
  kubectl -n automation get pod n8n-postgres-0 -o json |
    jq -er --arg owner "$stateful_uid" --arg image "$pg_image" '
      select(.metadata.deletionTimestamp == null and .status.phase == "Running" and
        ([.metadata.ownerReferences[]? | select(.controller == true and
          .kind == "StatefulSet" and .name == "n8n-postgres" and .uid == $owner)] | length) == 1 and
        ([.spec.containers[] | select(.name == "postgres" and .image == $image and
          ([.volumeMounts[] | select(.name == "data" and .mountPath == "/var/lib/postgresql/data")] | length) == 1)] | length) == 1 and
        ([.spec.volumes[] | select(.name == "data" and
          .persistentVolumeClaim.claimName == "data-n8n-postgres-0")] | length) == 1 and
        ([.status.containerStatuses[] | select(.name == "postgres" and .ready == true)] | length) == 1) |
      [.metadata.uid, (.spec.containers[] | select(.name == "postgres") | .image)] | @tsv'
}

owned_policy_uid() {
  kubectl -n automation get networkpolicy "$resource_name" -o json |
    jq -er --arg name "$resource_name" --arg owner "$owner_token" '
      select(.metadata.name == $name and .metadata.deletionTimestamp == null and
        .metadata.labels["homelab.stuhlmuller.dev/checkpoint-owner"] == $owner and
        .spec.podSelector.matchLabels["app.kubernetes.io/name"] == "n8n-checkpoint-reader" and
        .spec.podSelector.matchLabels["homelab.stuhlmuller.dev/checkpoint-owner"] == $owner and
        (.spec.policyTypes | sort) == ["Egress", "Ingress"] and
        (.spec.ingress // []) == [] and (.spec.egress // []) == []) | .metadata.uid'
}

owned_job_uid() {
  kubectl -n automation get job "$resource_name" -o json |
    jq -er --arg name "$resource_name" --arg owner "$owner_token" '
      select(.metadata.name == $name and .metadata.deletionTimestamp == null and
        .metadata.labels["homelab.stuhlmuller.dev/checkpoint-owner"] == $owner and
        .spec.backoffLimit == 0 and .spec.activeDeadlineSeconds == 3600 and
        .spec.template.metadata.labels["homelab.stuhlmuller.dev/checkpoint-owner"] == $owner) |
      .metadata.uid'
}

reader_state() {
  local job_uid
  job_uid="$(owned_job_uid)" || return 1
  [[ "$job_uid" =~ $uuid ]] || return 1
  kubectl get --raw "/api/v1/namespaces/automation/pods?labelSelector=batch.kubernetes.io%2Fjob-name%3D${resource_name}" |
    jq -er --arg owner "$job_uid" --arg name "$resource_name" --arg token "$owner_token" --arg image "$reader_image" '
      select(.kind == "PodList" and (.metadata.resourceVersion | type == "string" and . != "" and . != "0") and
        (.metadata.continue // "") == "" and (.items | length) == 1) |
      .items[0] | select(.metadata.deletionTimestamp == null and .status.phase == "Running" and
        .metadata.labels["app.kubernetes.io/name"] == "n8n-checkpoint-reader" and
        .metadata.labels["homelab.stuhlmuller.dev/checkpoint-owner"] == $token and
        ([.metadata.ownerReferences[]? | select(.controller == true and .kind == "Job" and
          .name == $name and .uid == $owner)] | length) == 1 and
        .spec.automountServiceAccountToken == false and
        ([.spec.volumes[] | select(.name == "source" and
          .persistentVolumeClaim.claimName == "n8n" and .persistentVolumeClaim.readOnly == true)] | length) == 1 and
        ([.spec.containers[] | select(.name == "reader" and .image == $image and
          ([.volumeMounts[] | select(.name == "source" and .mountPath == "/source" and .readOnly == true)] | length) == 1)] | length) == 1 and
        ([.status.containerStatuses[] | select(.name == "reader" and .ready == true)] | length) == 1) |
      [.metadata.name, .metadata.uid] | @tsv'
}

work="$(mktemp -d)"
resource_name="n8n-checkpoint-reader-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
[[ "${#resource_name}" -le 63 ]] || exit 1
owner_token="$(openssl rand -hex 16)"
[[ "$owner_token" =~ ^[0-9a-f]{32}$ ]] || exit 1
job_file="$work/job.json"
policy_file="$work/policy.json"
yq -o=json '.' "$job_manifest" |
  jq --arg name "$resource_name" --arg owner "$owner_token" '
    .metadata.name = $name |
    .metadata.labels["homelab.stuhlmuller.dev/checkpoint-owner"] = $owner |
    .spec.template.metadata.labels["homelab.stuhlmuller.dev/checkpoint-owner"] = $owner' >"$job_file"
yq -o=json '.' "$policy_manifest" |
  jq --arg name "$resource_name" --arg owner "$owner_token" '
    .metadata.name = $name |
    .metadata.labels["homelab.stuhlmuller.dev/checkpoint-owner"] = $owner |
    .spec.podSelector.matchLabels["homelab.stuhlmuller.dev/checkpoint-owner"] = $owner' >"$policy_file"
job_attempted=false
policy_attempted=false
job_uid=
policy_uid=
container=
volume=
absent() {
  local result
  result="$(kubectl -n automation get "$1" "$resource_name" -o json --ignore-not-found)" || return 1
  [[ -z "$result" ]]
}
reader_pods_gone() {
  local _
  for _ in {1..6}; do
    if kubectl -n automation get pods \
      -l "homelab.stuhlmuller.dev/checkpoint-owner=$owner_token" --chunk-size=0 -o json |
      jq -e '.kind == "PodList" and
        (.metadata.resourceVersion | type == "string" and . != "" and . != "0") and
        (.metadata.continue // "") == "" and (.items | type == "array" and length == 0)' >/dev/null; then
      return 0
    fi
    sleep 2
  done
  return 1
}
cleanup_resources() {
  local current
  if [[ "$job_attempted" == true ]] && ! absent job; then
    current="$(owned_job_uid)" || return 1
    [[ "$current" =~ $uuid && ( -z "$job_uid" || "$current" == "$job_uid" ) ]] || return 1
    timeout --signal=TERM --kill-after=30s 2m \
      "$kubectl_bin" --request-timeout=60s -n automation delete -f "$job_file" \
      --cascade=foreground --ignore-not-found --wait=true >/dev/null 2>&1 || return 1
    absent job || return 1
  fi
  if [[ "$job_attempted" == true || "$policy_attempted" == true ]]; then
    reader_pods_gone || return 1
  fi
  if [[ "$policy_attempted" == true ]] && ! absent networkpolicy; then
    current="$(owned_policy_uid)" || return 1
    [[ "$current" =~ $uuid && ( -z "$policy_uid" || "$current" == "$policy_uid" ) ]] || return 1
    timeout --signal=TERM --kill-after=30s 2m \
      "$kubectl_bin" --request-timeout=60s -n automation delete -f "$policy_file" \
      --ignore-not-found --wait=true >/dev/null 2>&1 || return 1
    absent networkpolicy || return 1
  fi
}
cleanup() {
  local result=$?
  cleanup_resources || result=1
  if [[ -n "$container" ]]; then docker rm -f "$container" >/dev/null 2>&1 || true; fi
  if [[ -n "$volume" ]]; then docker volume rm -f "$volume" >/dev/null 2>&1 || true; fi
  rm -rf -- "$work"
  exit "$result"
}
trap cleanup EXIT

check_fence
n8n_binding="$(binding n8n "$EXPECTED_N8N_PVC_UID" "$EXPECTED_N8N_PV_UID")"
pg_binding="$(binding data-n8n-postgres-0 "$EXPECTED_PG_PVC_UID" "$EXPECTED_PG_PV_UID")"
pg_record="$(pg_state)"
checked_equal 1 kubectl -n automation exec n8n-postgres-0 -c postgres -- \
  psql -XAt -w -U postgres -d n8n -c 'SELECT 1' || exit 1
database_bytes="$(kubectl -n automation exec n8n-postgres-0 -c postgres -- psql -XAt -w -U postgres -d n8n -c 'SELECT pg_database_size(current_database())')"
[[ "$database_bytes" =~ ^[1-9][0-9]*$ && "$database_bytes" -lt 1073741824 ]] || exit 1

policy_attempted=true
kubectl -n automation create -f "$policy_file" -o name >"$work/policy-create.out" 2>"$work/policy-create.err" || true
for _ in {1..5}; do
  policy_uid="$(owned_policy_uid 2>/dev/null)" && break
  sleep 2
done
[[ "$policy_uid" =~ $uuid ]] || exit 1
job_attempted=true
kubectl -n automation create -f "$job_file" -o name >"$work/job-create.out" 2>"$work/job-create.err" || true
for _ in {1..5}; do
  job_uid="$(owned_job_uid 2>/dev/null)" && break
  sleep 2
done
[[ "$job_uid" =~ $uuid ]] || exit 1
reader_record=
for _ in {1..60}; do
  reader_record="$(reader_state 2>/dev/null)" && break
  sleep 2
done
[[ -n "$reader_record" ]] || exit 1
IFS=$'\t' read -r reader_pod reader_uid <<<"$reader_record"
[[ "$reader_pod" == "$resource_name"-* && "$reader_uid" =~ $uuid ]] || exit 1
check_fence "$reader_uid"

timeout --signal=TERM --kill-after=30s 15m \
  "$kubectl_bin" -n automation exec n8n-postgres-0 -c postgres -- \
    pg_dump --format=custom --no-owner --no-privileges --no-password \
    -U postgres -d n8n >"$work/n8n.dump"
timeout --signal=TERM --kill-after=30s 15m \
  "$kubectl_bin" -n automation exec "$reader_pod" -c reader -- \
    tar -C /source -cf - . >"$work/n8n.tar"
checked_equal "$pg_record" pg_state || exit 1
checked_equal "$reader_record" reader_state || exit 1
checked_equal "$n8n_binding" binding n8n "$EXPECTED_N8N_PVC_UID" "$EXPECTED_N8N_PV_UID" || exit 1
checked_equal "$pg_binding" binding data-n8n-postgres-0 "$EXPECTED_PG_PVC_UID" "$EXPECTED_PG_PV_UID" || exit 1
check_fence "$reader_uid"

cleanup_resources
job_attempted=false
policy_attempted=false
check_fence

pg_bytes="$(wc -c <"$work/n8n.dump" | tr -d '[:space:]')"
pvc_bytes="$(wc -c <"$work/n8n.tar" | tr -d '[:space:]')"
[[ "$pg_bytes" =~ ^[1-9][0-9]*$ && "$pg_bytes" -lt 1073741824 &&
   "$pvc_bytes" =~ ^[1-9][0-9]*$ && "$pvc_bytes" -lt 1073741824 ]] || exit 1
python3 -I scripts/ci/n8n-pvc-restore-check.py "$work/n8n.tar" "$work/pvc-check.json"
files="$(jq -er '.files | select(type == "number" and . > 0)' "$work/pvc-check.json")"
config_sha="$(jq -er '.config_sha256 | select(test("^[0-9a-f]{64}$"))' "$work/pvc-check.json")"

prefix="n8n/paired/${GITHUB_SHA}/${GITHUB_RUN_ID}/${GITHUB_RUN_ATTEMPT}"
publish() {
  local source="$1" key="$2" target="$3" bytes checksum digest put version head readback_sha
  bytes="$(wc -c <"$source" | tr -d '[:space:]')" || return 1
  checksum="$(openssl dgst -sha256 -binary "$source" | openssl base64 -A)" || return 1
  digest="$(sha256sum "$source" | cut -d' ' -f1)" || return 1
  aws --region us-east-1 s3api list-object-versions --bucket "$bucket" \
    --expected-bucket-owner "$account" --prefix "$key" --output json |
    jq -e --arg key "$key" '[.Versions[]?, .DeleteMarkers[]?] | all(.Key != $key)' >/dev/null || return 1
  put="$(aws --region us-east-1 s3api put-object --bucket "$bucket" --key "$key" \
    --expected-bucket-owner "$account" --body "$source" \
    --server-side-encryption aws:kms --if-none-match '*' \
    --checksum-algorithm SHA256 --checksum-sha256 "$checksum")" || return 1
  version="$(jq -er '.VersionId | select(type == "string" and . != "" and . != "null")' <<<"$put")" || return 1
  head="$(aws --region us-east-1 s3api head-object --bucket "$bucket" --key "$key" \
    --expected-bucket-owner "$account" --version-id "$version" --checksum-mode ENABLED)" || return 1
  jq -e --arg version "$version" --arg checksum "$checksum" --argjson bytes "$bytes" \
    '.VersionId == $version and .ChecksumSHA256 == $checksum and
      .ContentLength == $bytes and .ServerSideEncryption == "aws:kms"' <<<"$head" >/dev/null || return 1
  aws --region us-east-1 s3api get-object --bucket "$bucket" --key "$key" \
    --expected-bucket-owner "$account" --version-id "$version" --checksum-mode ENABLED \
    "$target" >"$work/readback.json" || return 1
  jq -e --arg version "$version" --arg checksum "$checksum" --argjson bytes "$bytes" \
    '.VersionId == $version and .ChecksumSHA256 == $checksum and
      .ContentLength == $bytes and .ServerSideEncryption == "aws:kms"' "$work/readback.json" >/dev/null || return 1
  readback_sha="$(sha256sum "$target" | cut -d' ' -f1)" || return 1
  [[ "$readback_sha" == "$digest" ]] || return 1
  printf '%s\t%s\t%s\n' "$version" "$digest" "$bytes"
}

pg_key="$prefix/n8n.dump"
pvc_key="$prefix/n8n.tar"
pg_object="$(publish "$work/n8n.dump" "$pg_key" "$work/retrieved.dump")"
pvc_object="$(publish "$work/n8n.tar" "$pvc_key" "$work/retrieved.tar")"
IFS=$'\t' read -r pg_version pg_sha pg_bytes <<<"$pg_object"
IFS=$'\t' read -r pvc_version pvc_sha pvc_bytes <<<"$pvc_object"

python3 -I scripts/ci/n8n-pvc-restore-check.py "$work/retrieved.tar" "$work/retrieved-pvc-check.json"
cmp -s "$work/pvc-check.json" "$work/retrieved-pvc-check.json"

volume="$(docker volume create)"
[[ "$volume" =~ ^[A-Za-z0-9._-]+$ ]] || exit 1
container="$(docker run --detach --rm --network none \
  --mount "type=volume,src=$volume,dst=/var/lib/postgresql/data" \
  --mount "type=bind,src=$work/retrieved.dump,dst=/checkpoint.dump,readonly" \
  --env POSTGRES_DB=n8n --env POSTGRES_USER=postgres \
  --env POSTGRES_HOST_AUTH_METHOD=trust "$pg_image")"
ready=false
for _ in {1..60}; do
  if docker exec "$container" pg_isready -h 127.0.0.1 -U postgres -d n8n >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 2
done
[[ "$ready" == true ]] || exit 1
docker exec "$container" psql -v ON_ERROR_STOP=1 -XAt -w -U postgres -d postgres -c \
  'CREATE ROLE n8n LOGIN' >/dev/null
docker exec "$container" psql -v ON_ERROR_STOP=1 -XAt -w -U postgres -d postgres -c \
  'ALTER DATABASE n8n OWNER TO n8n' >/dev/null
docker exec "$container" psql -v ON_ERROR_STOP=1 -XAt -w -U postgres -d n8n -c \
  'ALTER SCHEMA public OWNER TO n8n' >/dev/null
docker exec "$container" pg_restore --clean --if-exists --exit-on-error \
  --no-owner --no-privileges -U n8n -d n8n /checkpoint.dump >/dev/null
tables="$(docker exec "$container" psql -XAt -w -U n8n -d n8n -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")"
[[ "$tables" =~ ^[1-9][0-9]*$ ]] || exit 1
docker exec "$container" psql -XAt -w -U n8n -d n8n -c \
  'SELECT 1 FROM public.workflow_entity LIMIT 0' >/dev/null

check_fence
checked_equal "$pg_record" pg_state || exit 1
checked_equal "$n8n_binding" binding n8n "$EXPECTED_N8N_PVC_UID" "$EXPECTED_N8N_PV_UID" || exit 1
checked_equal "$pg_binding" binding data-n8n-postgres-0 "$EXPECTED_PG_PVC_UID" "$EXPECTED_PG_PV_UID" || exit 1

IFS=$'\t' read -r n8n_pvc_uid n8n_pv n8n_pv_uid <<<"$n8n_binding"
IFS=$'\t' read -r pg_pvc_uid pg_pv pg_pv_uid <<<"$pg_binding"
jq -n --arg sha "$GITHUB_SHA" --argjson run "$GITHUB_RUN_ID" \
  --argjson attempt "$GITHUB_RUN_ATTEMPT" \
  --arg n8n_pvc_uid "$n8n_pvc_uid" --arg n8n_pv "$n8n_pv" --arg n8n_pv_uid "$n8n_pv_uid" \
  --arg pg_pvc_uid "$pg_pvc_uid" --arg pg_pv "$pg_pv" --arg pg_pv_uid "$pg_pv_uid" \
  --arg pg_key "$pg_key" --arg pg_version "$pg_version" --arg pg_sha "$pg_sha" --argjson pg_bytes "$pg_bytes" \
  --arg pvc_key "$pvc_key" --arg pvc_version "$pvc_version" --arg pvc_sha "$pvc_sha" --argjson pvc_bytes "$pvc_bytes" \
  --argjson tables "$tables" --argjson files "$files" --arg config_sha "$config_sha" \
  '{schema: 1, source: {main_sha: $sha, run_id: $run, run_attempt: $attempt,
    n8n: {pvc_uid: $n8n_pvc_uid, pv: $n8n_pv, pv_uid: $n8n_pv_uid},
    postgresql: {pvc_uid: $pg_pvc_uid, pv: $pg_pv, pv_uid: $pg_pv_uid}},
    objects: {postgresql: {key: $pg_key, version: $pg_version, sha256: $pg_sha, bytes: $pg_bytes},
      n8n_pvc: {key: $pvc_key, version: $pvc_version, sha256: $pvc_sha, bytes: $pvc_bytes}},
    isolated_restore: {postgresql_tables: $tables, pvc_files: $files, config_sha256: $config_sha}}' \
  >"$work/manifest.json"
manifest_key="$prefix/manifest.json"
manifest_object="$(publish "$work/manifest.json" "$manifest_key" "$work/retrieved-manifest.json")"
cmp -s "$work/manifest.json" "$work/retrieved-manifest.json"
IFS=$'\t' read -r manifest_version manifest_sha _ <<<"$manifest_object"

docker rm -f "$container" >/dev/null
container=
docker volume rm -f "$volume" >/dev/null
volume=
rm -rf -- "$work"
[[ ! -e "$work" ]] || exit 1

printf 'Verified n8n paired checkpoint: manifest=%s version=%s sha256=%s pg_pvc_uid=%s pg_pv_uid=%s n8n_pvc_uid=%s n8n_pv_uid=%s tables=%s files=%s\n' \
  "$manifest_key" "$manifest_version" "$manifest_sha" "$pg_pvc_uid" "$pg_pv_uid" \
  "$n8n_pvc_uid" "$n8n_pv_uid" "$tables" "$files" \
  >"${RUNNER_TEMP:?}/n8n-paired-checkpoint-receipt"
