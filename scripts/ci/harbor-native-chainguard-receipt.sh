#!/usr/bin/env bash
set -euo pipefail

test "$#" -eq 0 || { echo 'Usage: harbor-native-chainguard-receipt.sh (no arguments)' >&2; exit 2; }
[[ "${GITHUB_ACTIONS:-}" == true && "$(uname -s)" == Linux ]]
[[ "${GITHUB_REPOSITORY:-}" == Stuhlmuller/homelab ]]
[[ "${GITHUB_REF:-}" == refs/heads/main ]]
[[ "${GITHUB_EVENT_NAME:-}" == workflow_dispatch ]]
[[ "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ && "${EXPECTED_SHA:-}" == "$GITHUB_SHA" ]]
[[ "${GITHUB_WORKFLOW_REF:-}" == Stuhlmuller/homelab/.github/workflows/harbor-native-chainguard-receipt.yml@refs/heads/main ]]
: "${RUNNER_TEMP:?RUNNER_TEMP must be set by GitHub Actions}"
: "${OCTELIUM_AUTH_TOKEN:?The production Octelium CI credential is required}"
[[ "${KUBE_API_SERVER_URL:-}" == https://kubernetes-api-ci.stinkyboi.com ]]

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repository_root"
[[ "$(git rev-parse HEAD)" == "$GITHUB_SHA" ]]
[[ "$(git ls-remote https://github.com/Stuhlmuller/homelab.git refs/heads/main | cut -f1)" == "$GITHUB_SHA" ]]
[[ ! -e "$HOME/.kube/config" ]] || { echo 'Refusing to replace an existing runner kubeconfig.' >&2; exit 1; }
if grep -Eq '(^|[[:space:]])harbor[.]stinkyboi[.]com([[:space:]]|$)|# homelab-harbor-ci$' /etc/hosts; then
  echo 'Refusing to replace existing Harbor host routing.' >&2
  exit 1
fi

umask 077
scratch="$(mktemp -d "${RUNNER_TEMP}/harbor-native-receipt.XXXXXX")"
plan="$scratch/plan.json"
authfile="$scratch/harbor-pull-auth.json"
transport_log="$scratch/transport.log"
forward_pid=""
hosts_added=false
kubeconfig_added=false
receipt_files=()
cleanup() {
  local result=$?
  trap - EXIT INT TERM
  if [[ -n "$forward_pid" ]]; then
    kill -TERM "$forward_pid" 2>/dev/null || true
    wait "$forward_pid" 2>/dev/null || true
  fi
  if "$hosts_added"; then
    sudo -n sed -i '/# homelab-harbor-ci$/d' /etc/hosts || result=1
  fi
  if "$kubeconfig_added"; then
    rm -f -- "$HOME/.kube/config" || result=1
  fi
  rm -rf -- "$scratch" || result=1
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Validate every fixed source, destination, platform, catalog digest, and native
# replication rule before the runner reads either private Harbor credential.
python3 -I scripts/ci/harbor-native-chainguard-receipt.py plan >"$plan"

kubeconfig_added=true
bash scripts/ci/install-kubeconfig.sh >>"$transport_log" 2>&1
kubectl --request-timeout=15s version >>"$transport_log" 2>&1
cp "$(command -v kubectl)" "$scratch/kubectl"
chmod 700 "$scratch/kubectl"
sudo -n setcap cap_net_bind_service=+ep "$scratch/kubectl"
timeout --signal=TERM --kill-after=5s 900 \
  "$scratch/kubectl" --kubeconfig "$HOME/.kube/config" --namespace traefik \
  port-forward --address 127.0.0.1 service/traefik-private 443:443 >>"$transport_log" 2>&1 &
forward_pid=$!
hosts_added=true
printf '%s\n' '127.0.0.1 harbor.stinkyboi.com # homelab-harbor-ci' | sudo -n tee -a /etc/hosts >/dev/null

ready=false
for _ in {1..30}; do
  kill -0 "$forward_pid"
  if status="$(curl --silent --show-error --noproxy '*' --max-time 5 --output /dev/null \
    --write-out '%{http_code}' https://harbor.stinkyboi.com/v2/ 2>>"$transport_log")" && [[ "$status" == 401 ]]; then
    ready=true
    break
  fi
  sleep 2
done
"$ready" || { echo 'Harbor TLS and private registry challenge are not ready.' >&2; exit 1; }

# The pull robot is used only for OCI reads. The separate artifact-read robot
# reads exact child scan summaries over the existing private Harbor transport.
aws ssm get-parameter --region us-west-2 --name /homelab/harbor/robot-pull-password \
  --with-decryption --query Parameter.Value --output text >"$scratch/harbor-pull-password" 2>>"$transport_log"
aws ssm get-parameter --region us-west-2 --name /homelab/harbor/robot-scan-password \
  --with-decryption --query Parameter.Value --output text >"$scratch/harbor-scan-password" 2>>"$transport_log"
[[ -s "$scratch/harbor-pull-password" ]]
[[ -s "$scratch/harbor-scan-password" ]]
skopeo login --authfile "$authfile" --username "robot\$homelab+pull" --password-stdin harbor.stinkyboi.com \
  <"$scratch/harbor-pull-password" >>"$transport_log" 2>&1
rm -f -- "$scratch/harbor-pull-password"
while IFS= read -r image_id; do
  metadata="$scratch/${image_id}.json"
  jq --arg image_id "$image_id" -e '.images[] | select(.image_id == $image_id)' "$plan" >"$metadata"
  source_ref="$(jq -er '.source_ref' "$metadata")"
  source_repository="$(jq -er '.source_repository' "$metadata")"
  source_digest="$(jq -er '.source_digest' "$metadata")"
  destination_ref="$(jq -er '.destination_ref' "$metadata")"
  destination_repository="$(jq -er '.destination_repository' "$metadata")"
  source_tag_index="$scratch/${image_id}-source-tag-index.json"
  source_index="$scratch/${image_id}-source-index.json"
  destination_index="$scratch/${image_id}-destination-index.json"
  pulled_index="$scratch/${image_id}-pulled-index.json"
  scan_receipt="$scratch/${image_id}-scan-receipt.json"
  final_receipt="$scratch/${image_id}-receipt.json"

  skopeo inspect --raw --no-creds "docker://${source_ref}" >"$source_tag_index" 2>>"$transport_log"
  [[ "sha256:$(sha256sum "$source_tag_index" | cut -d ' ' -f 1)" == "$source_digest" ]]
  source_directory="$(mktemp -d "$scratch/${image_id}-source.XXXXXX")"
  skopeo copy --all --preserve-digests --src-no-creds \
    "docker://${source_repository}@${source_digest}" "dir:${source_directory}" >>"$transport_log" 2>&1
  skopeo inspect --raw "dir:${source_directory}" >"$source_index" 2>>"$transport_log"
  cmp -s "$source_tag_index" "$source_index"
  rm -rf -- "$source_directory"

  skopeo inspect --raw --authfile "$authfile" "docker://${destination_ref}" >"$destination_index" 2>>"$transport_log"
  cmp -s "$source_index" "$destination_index"
  pull_directory="$(mktemp -d "$scratch/${image_id}-pull.XXXXXX")"
  skopeo copy --all --preserve-digests --src-authfile "$authfile" \
    "docker://${destination_repository}@${source_digest}" "dir:${pull_directory}" >>"$transport_log" 2>&1
  skopeo inspect --raw "dir:${pull_directory}" >"$pulled_index" 2>>"$transport_log"
  cmp -s "$source_index" "$pulled_index"
  rm -rf -- "$pull_directory"

  config_digest="$(jq -er '.config_digest' "$metadata")"
  python3 -I scripts/ci/harbor-native-chainguard-receipt.py scan \
    --image-id "$image_id" --config-digest "$config_digest" --destination-digest "$source_digest" \
    --index "$source_index" --scan-password-file "$scratch/harbor-scan-password" --output "$scan_receipt" \
    >>"$transport_log" 2>&1
  python3 -I scripts/ci/harbor-native-chainguard-receipt.py verify \
    --image-id "$image_id" --repository-sha "$GITHUB_SHA" --source-index "$source_index" \
    --destination-index "$destination_index" --pulled-index "$pulled_index" \
    --scan-receipt "$scan_receipt" --output "$final_receipt"
  receipt_files+=("$final_receipt")
done < <(jq -er '.images[].image_id' "$plan")
rm -f -- "$scratch/harbor-scan-password"

[[ "${#receipt_files[@]}" -gt 0 ]]
output="$RUNNER_TEMP/harbor-native-chainguard-receipt.json"
jq -s --arg sha "$GITHUB_SHA" \
  '{schema_version: 1, kind: "native-chainguard-receipts-v1", repository_sha: $sha, receipts: .}' \
  "${receipt_files[@]}" >"$output"
chmod 600 "$output"
jq -e --arg sha "$GITHUB_SHA" '
  .schema_version == 1 and .kind == "native-chainguard-receipts-v1" and .repository_sha == $sha and
  (.receipts | type == "array" and length > 0 and all(.[]; .consumer_access == true))
' "$output" >/dev/null
echo 'Native Chainguard imports were digest-matched, completely pulled, and scan-verified.'
