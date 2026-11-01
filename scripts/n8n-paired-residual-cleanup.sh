#!/usr/bin/env bash
set -euo pipefail
umask 077

usage='Usage: scripts/n8n-paired-residual-cleanup.sh CURRENT_MAIN_SHA RUN_ID ATTEMPT JOB_UID|absent POLICY_UID|absent OWNER_LABEL'
[[ $# -eq 6 ]] || { echo "$usage" >&2; exit 2; }
main_sha=$1
run_id=$2
attempt=$3
expected_job_uid=$4
expected_policy_uid=$5
owner=$6
uuid='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
valid_uid() { [[ "$1" == absent || "$1" =~ $uuid ]]; }
[[ "$main_sha" =~ ^[0-9a-f]{40}$ && "$run_id" =~ ^[1-9][0-9]*$ &&
   "$attempt" =~ ^[1-9][0-9]*$ && "$owner" =~ ^[0-9a-f]{32}$ ]] || exit 2
valid_uid "$expected_job_uid" && valid_uid "$expected_policy_uid" || exit 2
name="n8n-checkpoint-reader-${run_id}-${attempt}"
[[ ${#name} -le 63 ]] || exit 2
local_head="$(git rev-parse HEAD)" || exit 1
remote_main="$(gh api repos/Stuhlmuller/homelab/git/ref/heads/main --jq .object.sha)" || exit 1
worktree_status="$(git status --porcelain)" || exit 1
[[ "$local_head" == "$main_sha" && "$remote_main" == "$main_sha" &&
   -z "$worktree_status" ]] || exit 1

kubectl_bin="$(command -v kubectl)"
timeout_bin="$(command -v timeout)"
[[ -x "$kubectl_bin" && -x "$timeout_bin" ]] || exit 1
kubectl() { "$timeout_bin" -k 5s 45s "$kubectl_bin" --request-timeout=30s "$@"; }
wait_for_delete() {
  "$timeout_bin" -k 5s 155s "$kubectl_bin" --request-timeout=30s \
    -n automation wait --for=delete "$1/$name" --timeout=120s
}
delete_job() {
  "$timeout_bin" -k 5s 155s "$kubectl_bin" --request-timeout=30s \
    -n automation delete job "$name" --cascade=foreground --wait=true --timeout=120s
}
delete_policy() {
  "$timeout_bin" -k 5s 95s "$kubectl_bin" --request-timeout=30s \
    -n automation delete networkpolicy "$name" --wait=true --timeout=60s
}
work="$(mktemp -d)"
cleanup() {
  rm -rf -- "$work"
}
trap cleanup EXIT
job_manifest=clusters/homelab/apps/n8n/checkpoint-reader.job.yaml
yq -o=json '.' "$job_manifest" >"$work/expected-job.json"
reader_image="$(jq -er '.spec.template.spec.containers[] | select(.name == "reader") | .image' "$work/expected-job.json")"

for access in 'get applications -n argocd' 'get deployments -n automation' \
  'get jobs -n automation' 'delete jobs -n automation' \
  'get networkpolicies -n automation' 'delete networkpolicies -n automation' \
  'list pods -n automation'; do
  read -r -a args <<<"$access"
  [[ "$(kubectl auth can-i "${args[@]}")" == yes ]] || exit 1
done

fenced() {
  local allowed_job_uid=$1
  kubectl -n argocd get application n8n -o json |
    jq -e --arg sha "$main_sha" '
      .status.sync.status == "Synced" and .status.health.status == "Healthy" and
      ([.status.sync.revisions[]? | select(. == $sha)] | length) == 2' >/dev/null
  kubectl -n automation get deployment n8n -o json |
    jq -e '.spec.replicas == 0 and (.status.replicas // 0) == 0 and
      (.status.readyReplicas // 0) == 0 and
      .status.observedGeneration == .metadata.generation' >/dev/null
  kubectl get --raw '/api/v1/namespaces/automation/pods?limit=500' |
    jq -e --arg job "$name" --arg uid "$allowed_job_uid" --arg owner "$owner" --arg image "$reader_image" '
      .kind == "PodList" and (.metadata.resourceVersion | type == "string" and . != "" and . != "0") and
      (.metadata.continue // "") == "" and (.items | type == "array") and
      all(.items[];
        (any(.metadata.ownerReferences[]?; .kind == "Job" and .name == $job) or
          .metadata.labels["batch.kubernetes.io/job-name"] == $job or
          .metadata.labels["app.kubernetes.io/name"] == "n8n-checkpoint-reader") as $reader |
        if $reader then
          $uid != "absent" and
          .metadata.labels["homelab.stuhlmuller.dev/checkpoint-owner"] == $owner and
          .metadata.labels["app.kubernetes.io/name"] == "n8n-checkpoint-reader" and
          any(.metadata.ownerReferences[]?; .controller == true and .kind == "Job" and
            .name == $job and .uid == $uid) and
          .spec.automountServiceAccountToken == false and
          ([.spec.volumes[]? | select(.name == "source" and
            .persistentVolumeClaim.claimName == "n8n" and .persistentVolumeClaim.readOnly == true)] | length) == 1 and
          ([.spec.containers[]? | select(.name == "reader" and .image == $image and
            ([.volumeMounts[]? | select(.name == "source" and .mountPath == "/source" and .readOnly == true)] | length) == 1)] | length) == 1
        else
          .spec.serviceAccountName != "n8n" and
          .metadata.labels["app.kubernetes.io/name"] != "n8n" and
          all(.spec.volumes[]?; .persistentVolumeClaim.claimName != "n8n" and
            .secret.secretName != "n8n-postgres-client")
        end)' >/dev/null
  kubectl -n automation get jobs,cronjobs -o json |
    jq -e '[.items[] | select(
      (.kind == "Job" and (.status.active // 0) > 0 and
        .spec.template.spec.serviceAccountName == "n8n") or
      (.kind == "CronJob" and .spec.suspend != true and
        .spec.jobTemplate.spec.template.spec.serviceAccountName == "n8n"))] | length == 0' >/dev/null
}

kubectl -n automation get job "$name" -o json --ignore-not-found >"$work/job.json"
kubectl -n automation get networkpolicy "$name" -o json --ignore-not-found >"$work/policy.json"
if [[ -s "$work/job.json" ]]; then
  [[ "$expected_job_uid" != absent ]] || exit 1
  jq -e --arg name "$name" --arg uid "$expected_job_uid" --arg owner "$owner" \
    --slurpfile template "$work/expected-job.json" '
      .kind == "Job" and .apiVersion == "batch/v1" and
      .metadata.namespace == "automation" and .metadata.name == $name and
      .metadata.uid == $uid and
      (.metadata.resourceVersion | type == "string" and . != "" and . != "0") and
      .metadata.labels["app.kubernetes.io/name"] == "n8n-checkpoint-reader" and
      .metadata.labels["homelab.stuhlmuller.dev/checkpoint-owner"] == $owner and
      .spec.backoffLimit == 0 and .spec.activeDeadlineSeconds == 3600 and
      .spec.template.metadata.labels["homelab.stuhlmuller.dev/checkpoint-owner"] == $owner and
      .spec.template.metadata.labels["app.kubernetes.io/name"] == "n8n-checkpoint-reader" and
      .spec.template.metadata.annotations["sidecar.istio.io/inject"] == "false" and
      .spec.template.spec.automountServiceAccountToken == false and
      .spec.template.spec.restartPolicy == "Never" and
      (.spec.template.spec.containers | length) == 1 and
      .spec.template.spec.containers[0].name == "reader" and
      .spec.template.spec.containers[0].image == $template[0].spec.template.spec.containers[0].image and
      .spec.template.spec.containers[0].command == $template[0].spec.template.spec.containers[0].command and
      .spec.template.spec.containers[0].args == $template[0].spec.template.spec.containers[0].args and
      .spec.template.spec.containers[0].securityContext == $template[0].spec.template.spec.containers[0].securityContext and
      .spec.template.spec.securityContext == $template[0].spec.template.spec.securityContext and
      (.spec.template.spec.containers[0].volumeMounts | length) == 1 and
      ([.spec.template.spec.containers[0].volumeMounts[]? | select(.name == "source" and
        .mountPath == "/source" and .readOnly == true)] | length) == 1 and
      (.spec.template.spec.volumes | length) == 1 and
      ([.spec.template.spec.volumes[]? | select(.name == "source" and
        .persistentVolumeClaim.claimName == "n8n" and .persistentVolumeClaim.readOnly == true)] | length) == 1' \
    "$work/job.json" >/dev/null
else
  [[ "$expected_job_uid" == absent ]] || exit 1
fi
if [[ -s "$work/policy.json" ]]; then
  [[ "$expected_policy_uid" != absent ]] || exit 1
  jq -e --arg name "$name" --arg uid "$expected_policy_uid" --arg owner "$owner" '
      .kind == "NetworkPolicy" and .apiVersion == "networking.k8s.io/v1" and
      .metadata.namespace == "automation" and .metadata.name == $name and
      .metadata.uid == $uid and
      (.metadata.resourceVersion | type == "string" and . != "" and . != "0") and
      .metadata.labels["homelab.stuhlmuller.dev/checkpoint-owner"] == $owner and
      .spec.podSelector.matchLabels == {
        "app.kubernetes.io/name": "n8n-checkpoint-reader",
        "homelab.stuhlmuller.dev/checkpoint-owner": $owner
      } and (.spec.policyTypes | sort) == ["Egress", "Ingress"] and
      (.spec.ingress // []) == [] and (.spec.egress // []) == []' \
    "$work/policy.json" >/dev/null
else
  [[ "$expected_policy_uid" == absent ]] || exit 1
fi

fenced "$expected_job_uid"
if [[ -s "$work/policy.json" ]] &&
   jq -e '.metadata.deletionTimestamp != null' "$work/policy.json" >/dev/null; then
  # An already deleting policy cannot protect a live reader Pod or a Job that could create one.
  [[ ! -s "$work/job.json" ]] ||
    jq -e '.metadata.deletionTimestamp != null' "$work/job.json" >/dev/null || exit 1
  fenced absent
fi

same_resource() {
  local kind=$1 snapshot=$2 current="$work/current.json" observed expected
  kubectl -n automation get "$kind" "$name" -o json --ignore-not-found >"$current" || exit 1
  [[ -s "$current" ]] || return 1
  observed="$(jq -Sc '[.metadata.name, .metadata.namespace, .metadata.uid, .metadata.labels, .spec]' "$current")" || exit 1
  expected="$(jq -Sc '[.metadata.name, .metadata.namespace, .metadata.uid, .metadata.labels, .spec]' "$snapshot")" || exit 1
  [[ "$observed" == "$expected" ]] || exit 1
}

absent() {
  local kind=$1 output="$work/absent-${1}.json"
  kubectl -n automation get "$kind" "$name" -o json --ignore-not-found >"$output" || return 1
  [[ ! -s "$output" ]]
}

if [[ -s "$work/job.json" ]]; then
  if same_resource job "$work/job.json"; then
    # shortcut: run-scoped names have one writer; use API UID preconditions if concurrent recovery writers are added.
    if jq -e '.metadata.deletionTimestamp != null' "$work/current.json" >/dev/null; then
      wait_for_delete job >/dev/null
    else
      delete_job >/dev/null
    fi
  fi
  absent job || exit 1
fi
fenced absent
if [[ -s "$work/policy.json" ]]; then
  absent job || exit 1
  fenced absent
  if same_resource networkpolicy "$work/policy.json"; then
    if jq -e '.metadata.deletionTimestamp != null' "$work/current.json" >/dev/null; then
      "$timeout_bin" -k 5s 95s "$kubectl_bin" --request-timeout=30s \
        -n automation wait --for=delete "networkpolicy/$name" --timeout=60s >/dev/null
    else
      delete_policy >/dev/null
    fi
  fi
  absent networkpolicy || exit 1
fi
absent job && absent networkpolicy || exit 1
fenced absent
echo "Confirmed residual reader Job and deny-all policy absent for run ${run_id}/${attempt}; n8n remains fenced."
