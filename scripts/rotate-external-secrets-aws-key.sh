#!/usr/bin/env bash
# shellcheck disable=SC2030,SC2031 # Credential exports are intentionally scoped to probe subshells.
set -euo pipefail
set +x
umask 077

profile="${1:-}"
expected_revision="${2:-}"

if [[ -z "$profile" || ! "$expected_revision" =~ ^[1-9][0-9]*$ ]]; then
  echo "usage: $0 AWS_PROFILE EXPECTED_DATA_REVISION" >&2
  exit 2
fi

ambient_aws_variables=(
  AWS_ACCESS_KEY_ID
  AWS_DEFAULT_PROFILE
  AWS_IGNORE_CONFIGURED_ENDPOINT_URLS
  AWS_PROFILE
  AWS_ROLE_ARN
  AWS_ROLE_SESSION_NAME
  AWS_SECRET_ACCESS_KEY
  AWS_SECURITY_TOKEN
  AWS_SESSION_TOKEN
  AWS_WEB_IDENTITY_TOKEN_FILE
  AWS_CONTAINER_CREDENTIALS_FULL_URI
  AWS_CONTAINER_CREDENTIALS_RELATIVE_URI
)
for variable in "${ambient_aws_variables[@]}"; do
  if [[ -n "${!variable:-}" ]]; then
    echo "error: unset $variable; the named profile must be the only AWS credential source" >&2
    exit 1
  fi
done
while IFS= read -r variable; do
  if [[ -n "${!variable:-}" ]]; then
    echo "error: unset $variable; custom AWS endpoints are forbidden during rotation" >&2
    exit 1
  fi
done < <(compgen -A variable AWS_ENDPOINT_URL || true)
export AWS_IGNORE_CONFIGURED_ENDPOINT_URLS=true

for command in aws base64 conftest git jq kubectl rg shasum terragrunt; do
  command -v "$command" >/dev/null || {
    echo "error: required command is unavailable: $command" >&2
    exit 1
  }
done

repo_root="$(git rev-parse --show-toplevel)"
unit="$repo_root/IaC/live/kubernetes-secrets/external-secrets-aws-ssm-auth"
catalog_unit="$repo_root/IaC/.catalog/units/live/kubernetes-secrets/external-secrets-aws-ssm-auth/terragrunt.hcl"

if [[ "$(git -C "$repo_root" branch --show-current)" != "main" ]] ||
  [[ -n "$(git -C "$repo_root" status --porcelain)" ]]; then
  echo "error: rotate only from a clean main checkout" >&2
  exit 1
fi
git -C "$repo_root" fetch --quiet origin main
if ! git -C "$repo_root" rev-parse --verify --quiet refs/remotes/origin/main >/dev/null ||
  [[ "$(git -C "$repo_root" rev-parse HEAD)" != "$(git -C "$repo_root" rev-parse refs/remotes/origin/main)" ]]; then
  echo "error: local main must exactly match the reviewed origin/main" >&2
  exit 1
fi

if [[ -n "${KUBECONFIG:-}" ]]; then
  echo "error: KUBECONFIG must be unset so kubectl and the OpenTofu provider use ~/.kube/config" >&2
  exit 1
fi
expected_kubernetes_server="https://10.1.0.199:6443"
expected_kubernetes_ca_sha256="f83fb4e86c60ea695e6d7d951d5bfef2ea52a33c87707e5f6e540050d9aa8bce"
actual_kubernetes_server="$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
actual_kubernetes_ca_sha256="$({
  kubectl config view --raw --minify --flatten -o json |
    jq -r '.clusters[0].cluster["certificate-authority-data"]' |
    base64 --decode |
    shasum -a 256 |
    cut -d' ' -f1
})"
actual_kubernetes_insecure_skip_tls_verify="$(
  kubectl config view --minify -o json |
    jq -r '.clusters[0].cluster["insecure-skip-tls-verify"] // false'
)"
if [[ "$actual_kubernetes_server" != "$expected_kubernetes_server" ||
  "$actual_kubernetes_ca_sha256" != "$expected_kubernetes_ca_sha256" ||
  "$actual_kubernetes_insecure_skip_tls_verify" != false ]]; then
  echo "error: current kube context is not the reviewed TLS-verified homelab API endpoint and CA" >&2
  exit 1
fi
kubectl --request-timeout=15s get --raw=/version >/dev/null

(
  cd "$repo_root/IaC"
  terragrunt stack generate >/dev/null
)

if ! rg -q "^[[:space:]]*data_revision[[:space:]]*=[[:space:]]*${expected_revision}[[:space:]]*$" "$catalog_unit"; then
  echo "error: committed data_revision does not equal $expected_revision" >&2
  exit 1
fi

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/homelab-external-secrets-key.XXXXXX")"
chmod 700 "$tmp_dir"
new_key_created=false
new_key_id=""
ssm_updated=false
apply_started=false
old_key_inactive=false
old_key_deleted=false
rotation_complete=false
rotation_lock_acquired=false

aws_cli=(aws --profile "$profile")
iam_user="external-secrets_aws-ssm-auth"
region="us-west-2"
access_parameter="/homelab/external-secrets/aws-ssm/access-key-id"
secret_parameter="/homelab/external-secrets/aws-ssm/secret-access-key"
probe_parameter="/homelab/argocd/oidc/issuer"
rotation_lock_parameter="/homelab/locks/external-secrets-aws-ssm-auth-key-rotation"
rotation_lock_token="$(basename "$tmp_dir")"

put_parameter() {
  "${aws_cli[@]}" ssm put-parameter \
    --region "$region" \
    --cli-input-json "file://$1" >/dev/null
}

read_parameters() {
  "${aws_cli[@]}" ssm get-parameters \
    --region "$region" \
    --names "$access_parameter" "$secret_parameter" \
    --with-decryption \
    --output json >"$1"
}

clear_aws_credential_environment() {
  unset \
    AWS_ACCESS_KEY_ID \
    AWS_CONTAINER_CREDENTIALS_FULL_URI \
    AWS_CONTAINER_CREDENTIALS_RELATIVE_URI \
    AWS_DEFAULT_PROFILE \
    AWS_PROFILE \
    AWS_ROLE_ARN \
    AWS_ROLE_SESSION_NAME \
    AWS_SECRET_ACCESS_KEY \
    AWS_SECURITY_TOKEN \
    AWS_SESSION_TOKEN \
    AWS_WEB_IDENTITY_TOKEN_FILE
}

probe_controller_key() {
  local key_id="$1"
  local secret_access_key="$2"
  local label="$3"
  local auth_index
  local auth_parameter

  (
    clear_aws_credential_environment
    export AWS_ACCESS_KEY_ID="$key_id"
    export AWS_SECRET_ACCESS_KEY="$secret_access_key"
    aws sts get-caller-identity --region "$region" --output json \
      >"$tmp_dir/${label}-caller.json"
    aws ssm get-parameter \
      --region "$region" \
      --name "$probe_parameter" \
      --with-decryption \
      --output json >"$tmp_dir/${label}-probe.json"
    auth_index=0
    for auth_parameter in "$access_parameter" "$secret_parameter"; do
      auth_index=$((auth_index + 1))
      if aws ssm get-parameter \
        --region "$region" \
        --name "$auth_parameter" \
        --with-decryption \
        --output json >"$tmp_dir/${label}-auth-${auth_index}.json" 2>"$tmp_dir/${label}-auth-${auth_index}.err"; then
        echo "error: $label can read one of its own replacement credential parameters" >&2
        exit 1
      fi
      if ! rg -q 'AccessDenied|AccessDeniedException' "$tmp_dir/${label}-auth-${auth_index}.err"; then
        echo "error: could not prove $label is denied one of its own replacement credential parameters" >&2
        exit 1
      fi
    done
    if aws ssm get-parameters \
      --region "$region" \
      --names "$access_parameter" "$secret_parameter" \
      --with-decryption \
      --output json >"$tmp_dir/${label}-auth.json" 2>"$tmp_dir/${label}-auth.err"; then
      echo "error: $label can read its own replacement credential parameters" >&2
      exit 1
    fi
    if ! rg -q 'AccessDenied|AccessDeniedException' "$tmp_dir/${label}-auth.err"; then
      echo "error: could not prove $label is denied its own replacement credential parameters" >&2
      exit 1
    fi
  )

  jq -e --slurpfile user "$tmp_dir/iam-user.json" '
    .Account == ($user[0].User.Arn | split(":")[4]) and
    .Arn == $user[0].User.Arn
  ' "$tmp_dir/${label}-caller.json" >/dev/null
  jq -e --arg name "$probe_parameter" '
    .Parameter.Name == $name and
    (.Parameter.Value | type) == "string" and
    (.Parameter.Value | length) > 0
  ' "$tmp_dir/${label}-probe.json" >/dev/null
}

probe_temporary_session_denied() {
  local old_key_id="$1"
  local old_secret_access_key="$2"
  local session_access_key_id
  local session_secret_access_key
  local session_token

  (
    clear_aws_credential_environment
    export AWS_ACCESS_KEY_ID="$old_key_id"
    export AWS_SECRET_ACCESS_KEY="$old_secret_access_key"
    aws sts get-session-token \
      --region "$region" \
      --duration-seconds 900 \
      --output json >"$tmp_dir/temporary-session.json"
  )
  jq -e '
    (.Credentials.AccessKeyId | type) == "string" and
    (.Credentials.SecretAccessKey | type) == "string" and
    (.Credentials.SessionToken | type) == "string"
  ' "$tmp_dir/temporary-session.json" >/dev/null

  session_access_key_id="$(jq -r '.Credentials.AccessKeyId' "$tmp_dir/temporary-session.json")"
  session_secret_access_key="$(jq -r '.Credentials.SecretAccessKey' "$tmp_dir/temporary-session.json")"
  session_token="$(jq -r '.Credentials.SessionToken' "$tmp_dir/temporary-session.json")"
  (
    clear_aws_credential_environment
    export AWS_ACCESS_KEY_ID="$session_access_key_id"
    export AWS_SECRET_ACCESS_KEY="$session_secret_access_key"
    export AWS_SESSION_TOKEN="$session_token"
    if aws ssm get-parameter \
      --region "$region" \
      --name "$probe_parameter" \
      --with-decryption \
      --output json >"$tmp_dir/temporary-session-probe.json" 2>"$tmp_dir/temporary-session-probe.err"; then
      echo "error: temporary credentials derived from the controller key remain usable" >&2
      exit 1
    fi
    if ! rg -q 'AccessDenied|AccessDeniedException' "$tmp_dir/temporary-session-probe.err"; then
      echo "error: could not prove temporary controller credentials are denied" >&2
      exit 1
    fi
  )
  unset session_access_key_id session_secret_access_key session_token
}

parameters_match_old() {
  jq -e --arg access "$access_parameter" --arg secret "$secret_parameter" \
    --slurpfile old "$tmp_dir/old-parameters.json" '
      (.InvalidParameters | length) == 0 and
      (.Parameters | length) == 2 and
      (.Parameters[] | select(.Name == $access) | .Value) ==
        ($old[0].Parameters[] | select(.Name == $access) | .Value) and
      (.Parameters[] | select(.Name == $secret) | .Value) ==
        ($old[0].Parameters[] | select(.Name == $secret) | .Value)
    ' "$1" >/dev/null
}

parameters_match_new() {
  jq -e --arg access "$access_parameter" --arg secret "$secret_parameter" \
    --slurpfile new "$tmp_dir/new-key.json" '
      (.InvalidParameters | length) == 0 and
      (.Parameters | length) == 2 and
      (.Parameters[] | select(.Name == $access) | .Value) == $new[0].AccessKey.AccessKeyId and
      (.Parameters[] | select(.Name == $secret) | .Value) == $new[0].AccessKey.SecretAccessKey
    ' "$1" >/dev/null
}

json_excludes_new_credentials() {
  jq -e --slurpfile new "$tmp_dir/new-key.json" '
    (tostring | contains($new[0].AccessKey.AccessKeyId) or
      contains($new[0].AccessKey.SecretAccessKey)) | not
  ' "$1" >/dev/null
}

delete_access_key_safely() {
  local key_id="$1"
  local key_label="$2"
  local key_absent=false
  local key_inactive=false

  "${aws_cli[@]}" iam delete-access-key \
    --user-name "$iam_user" \
    --access-key-id "$key_id" >/dev/null 2>&1 || true

  for _ in {1..5}; do
    "${aws_cli[@]}" iam list-access-keys \
      --user-name "$iam_user" --output json >"$tmp_dir/cleanup-keys.json" || break
    if jq -e --arg key "$key_id" '
      all(.AccessKeyMetadata[]; .AccessKeyId != $key)
    ' "$tmp_dir/cleanup-keys.json" >/dev/null; then
      key_absent=true
      break
    fi
    sleep 2
  done
  [[ "$key_absent" == true ]] && return 0

  "${aws_cli[@]}" iam update-access-key \
    --user-name "$iam_user" --access-key-id "$key_id" --status Inactive \
    >/dev/null 2>&1 || true
  if "${aws_cli[@]}" iam list-access-keys \
    --user-name "$iam_user" --output json >"$tmp_dir/cleanup-keys.json" &&
    jq -e --arg key "$key_id" '
      any(.AccessKeyMetadata[];
        .AccessKeyId == $key and .Status == "Inactive")
    ' "$tmp_dir/cleanup-keys.json" >/dev/null; then
    key_inactive=true
  fi

  if [[ "$key_inactive" == true ]]; then
    echo "error: $key_label IAM key could not be deleted but was verified inactive; remove it before retrying" >&2
  else
    echo "error: $key_label IAM key could not be deleted or proven inactive; inspect the two-key IAM inventory immediately" >&2
  fi
  return 1
}

cleanup_uncertain_created_key() {
  local inventory_observed=false
  local extra_count=0
  local extra_key_id

  for _ in {1..15}; do
    if "${aws_cli[@]}" iam list-access-keys \
      --user-name "$iam_user" --output json >"$tmp_dir/create-failure-keys.json"; then
      inventory_observed=true
      extra_count="$(
        jq --arg old "$old_key_id" \
          '[.AccessKeyMetadata[] | select(.AccessKeyId != $old)] | length' \
          "$tmp_dir/create-failure-keys.json"
      )"
      if [[ "$extra_count" == 1 ]]; then
        extra_key_id="$(
          jq -r --arg old "$old_key_id" \
            '.AccessKeyMetadata[] | select(.AccessKeyId != $old) | .AccessKeyId' \
            "$tmp_dir/create-failure-keys.json"
        )"
        delete_access_key_safely "$extra_key_id" "unconfirmed replacement"
        return
      fi
      if [[ "$extra_count" != 0 ]]; then
        echo "error: unexpected IAM key inventory after uncertain creation; inspect it immediately" >&2
        return 1
      fi
    fi
    sleep 2
  done

  if [[ "$inventory_observed" == true ]]; then
    echo "error: key creation failed and no additional key was observed after repeated inventory checks" >&2
    return 0
  fi

  echo "error: key creation failed and the IAM inventory could not be checked" >&2
  return 1
}

acquire_rotation_lock() {
  local put_succeeded=false

  if "${aws_cli[@]}" ssm put-parameter \
    --region "$region" \
    --name "$rotation_lock_parameter" \
    --type String \
    --value "$rotation_lock_token" \
    --no-overwrite \
    --output json >"$tmp_dir/rotation-lock-put.json" 2>"$tmp_dir/rotation-lock-put.err"; then
    put_succeeded=true
  fi

  if "${aws_cli[@]}" ssm get-parameter \
    --region "$region" \
    --name "$rotation_lock_parameter" \
    --output json >"$tmp_dir/rotation-lock.json" 2>/dev/null &&
    jq -e --arg token "$rotation_lock_token" '.Parameter.Value == $token' \
      "$tmp_dir/rotation-lock.json" >/dev/null; then
    rotation_lock_acquired=true
    return 0
  fi

  if [[ "$put_succeeded" == true ]]; then
    echo "error: rotation lock was created but could not be verified; inspect $rotation_lock_parameter" >&2
  else
    echo "error: another rotation may hold $rotation_lock_parameter; inspect it before retrying" >&2
  fi
  return 1
}

release_rotation_lock() {
  if ! "${aws_cli[@]}" ssm get-parameter \
    --region "$region" \
    --name "$rotation_lock_parameter" \
    --output json >"$tmp_dir/rotation-lock-release.json" 2>/dev/null ||
    ! jq -e --arg token "$rotation_lock_token" '.Parameter.Value == $token' \
      "$tmp_dir/rotation-lock-release.json" >/dev/null; then
    echo "error: refusing to remove a rotation lock that is absent or not owned by this run" >&2
    return 1
  fi

  "${aws_cli[@]}" ssm delete-parameter \
    --region "$region" \
    --name "$rotation_lock_parameter" >/dev/null
}

cleanup() {
  local rc=$?
  local safe_to_delete_new=true
  set +e

  if ((rc != 0)) && [[ "$rotation_complete" != true ]]; then
    if [[ "$old_key_inactive" == true && "$old_key_deleted" != true ]]; then
      if "${aws_cli[@]}" iam update-access-key \
        --user-name "$iam_user" --access-key-id "$old_key_id" --status Active; then
        old_key_inactive=false
      else
        echo "error: failed to reactivate the old IAM key; retain the new key and investigate immediately" >&2
      fi
    fi

    if [[ "$apply_started" == true ]]; then
      echo "error: apply started; SSM keeps the new key and no remaining IAM key is deleted" >&2
    else
      if [[ "$ssm_updated" == true ]]; then
        safe_to_delete_new=false
        if put_parameter "$tmp_dir/old-access-parameter.json" &&
          put_parameter "$tmp_dir/old-secret-parameter.json" &&
          read_parameters "$tmp_dir/rollback-parameters.json" &&
          parameters_match_old "$tmp_dir/rollback-parameters.json"; then
          safe_to_delete_new=true
        else
          echo "error: old SSM pair was not restored exactly; retaining the new IAM key" >&2
          if put_parameter "$tmp_dir/new-access-parameter.json" &&
            put_parameter "$tmp_dir/new-secret-parameter.json" &&
            read_parameters "$tmp_dir/recovery-parameters.json" &&
            parameters_match_new "$tmp_dir/recovery-parameters.json"; then
            echo "error: SSM was recovered to the complete new pair; retry the reviewed rotation" >&2
          else
            echo "error: SSM pair could not be verified as old or new; immediate operator recovery is required" >&2
          fi
        fi
      fi

      if [[ "$new_key_created" == true && "$safe_to_delete_new" == true ]]; then
        delete_access_key_safely "$new_key_id" "replacement" || true
      elif [[ "$new_key_created" == true ]]; then
        echo "error: new IAM key retained because SSM rollback was not proven" >&2
      fi
    fi
  fi

  if [[ "$rotation_lock_acquired" == true ]]; then
    if release_rotation_lock; then
      rotation_lock_acquired=false
    else
      ((rc == 0)) && rc=1
    fi
  fi

  if ! rm -rf -- "$tmp_dir" "$unit/.terragrunt-cache"; then
    echo "error: failed to remove private rotation files" >&2
    ((rc == 0)) && rc=1
  fi
  exit "$rc"
}
trap cleanup EXIT

"${aws_cli[@]}" sts get-caller-identity --output json >"$tmp_dir/profile-caller.json"
"${aws_cli[@]}" iam get-user --user-name "$iam_user" --output json >"$tmp_dir/iam-user.json"
jq -e --slurpfile user "$tmp_dir/iam-user.json" '
  .Account == ($user[0].User.Arn | split(":")[4]) and
  $user[0].User.UserName == "external-secrets_aws-ssm-auth"
' "$tmp_dir/profile-caller.json" >/dev/null

acquire_rotation_lock

boundary_arn="$(jq -r '.User.PermissionsBoundary.PermissionsBoundaryArn // empty' "$tmp_dir/iam-user.json")"
if [[ -z "$boundary_arn" ]]; then
  echo "error: External Secrets IAM user has no permissions boundary" >&2
  exit 1
fi
"${aws_cli[@]}" iam get-policy \
  --policy-arn "$boundary_arn" \
  --output json >"$tmp_dir/boundary-policy.json"
boundary_version="$(jq -r '.Policy.DefaultVersionId' "$tmp_dir/boundary-policy.json")"
"${aws_cli[@]}" iam get-policy-version \
  --policy-arn "$boundary_arn" \
  --version-id "$boundary_version" \
  --output json >"$tmp_dir/boundary-policy-version.json"
jq -e '
  def wildcard: . == "*" or . == ["*"];
  any(.PolicyVersion.Document.Statement[];
    .Sid == "DenyTemporarySessionCredentials" and
    .Effect == "Deny" and
    (.Action | wildcard) and
    (.Resource | wildcard) and
    .Condition == {"Null": {"aws:TokenIssueTime": "false"}})
' "$tmp_dir/boundary-policy-version.json" >/dev/null

"${aws_cli[@]}" iam list-access-keys \
  --user-name "$iam_user" \
  --output json >"$tmp_dir/keys.json"

if [[ "$(jq '[.AccessKeyMetadata[] | select(.Status == "Active")] | length' "$tmp_dir/keys.json")" != 1 ]] ||
  [[ "$(jq '.AccessKeyMetadata | length' "$tmp_dir/keys.json")" != 1 ]]; then
  echo "error: expected exactly one IAM access key before rotation" >&2
  exit 1
fi
old_key_id="$(jq -r '.AccessKeyMetadata[0].AccessKeyId' "$tmp_dir/keys.json")"

read_parameters "$tmp_dir/old-parameters.json"

jq -e --arg access "$access_parameter" --arg secret "$secret_parameter" --arg old "$old_key_id" '
  (.InvalidParameters | length) == 0 and
  (.Parameters | length) == 2 and
  ([.Parameters[].Name] | sort) == ([$access, $secret] | sort) and
  (.Parameters[] | select(.Name == $access) | .Value) == $old
' "$tmp_dir/old-parameters.json" >/dev/null

kubectl -n external-secrets get secret aws-ssm-auth -o json >"$tmp_dir/live-secret-before.json"
jq -e --arg access "$access_parameter" --arg secret "$secret_parameter" \
  --slurpfile old "$tmp_dir/old-parameters.json" '
    (.data["access-key-id"] | @base64d) ==
      ($old[0].Parameters[] | select(.Name == $access) | .Value) and
    (.data["secret-access-key"] | @base64d) ==
      ($old[0].Parameters[] | select(.Name == $secret) | .Value)
  ' "$tmp_dir/live-secret-before.json" >/dev/null

old_secret_access_key="$(jq -r --arg secret "$secret_parameter" \
  '.Parameters[] | select(.Name == $secret) | .Value' "$tmp_dir/old-parameters.json")"
probe_controller_key "$old_key_id" "$old_secret_access_key" old-key
probe_temporary_session_denied "$old_key_id" "$old_secret_access_key"
unset old_secret_access_key

if ! "${aws_cli[@]}" iam create-access-key \
  --user-name "$iam_user" \
  --output json >"$tmp_dir/new-key.json"; then
  cleanup_uncertain_created_key || true
  exit 1
fi
if ! jq -e '
  (.AccessKey.AccessKeyId | type == "string") and
  (.AccessKey.AccessKeyId | length > 0) and
  (.AccessKey.SecretAccessKey | type == "string") and
  (.AccessKey.SecretAccessKey | length > 0)
' "$tmp_dir/new-key.json" >/dev/null; then
  cleanup_uncertain_created_key || true
  exit 1
fi
new_key_id="$(jq -r .AccessKey.AccessKeyId "$tmp_dir/new-key.json")"
new_key_created=true
chmod 600 "$tmp_dir"/*.json

jq --arg name "$access_parameter" \
  '{Name:$name,Value:.AccessKey.AccessKeyId,Type:"SecureString",KeyId:"alias/homelab-opentofu",Overwrite:true}' \
  "$tmp_dir/new-key.json" \
  >"$tmp_dir/new-access-parameter.json"
jq --arg name "$secret_parameter" \
  '{Name:$name,Value:.AccessKey.SecretAccessKey,Type:"SecureString",KeyId:"alias/homelab-opentofu",Overwrite:true}' \
  "$tmp_dir/new-key.json" \
  >"$tmp_dir/new-secret-parameter.json"
jq --arg name "$access_parameter" \
  '{Name:$name,Value:(.Parameters[] | select(.Name == $name) | .Value),Type:"SecureString",KeyId:"alias/homelab-opentofu",Overwrite:true}' \
  "$tmp_dir/old-parameters.json" \
  >"$tmp_dir/old-access-parameter.json"
jq --arg name "$secret_parameter" \
  '{Name:$name,Value:(.Parameters[] | select(.Name == $name) | .Value),Type:"SecureString",KeyId:"alias/homelab-opentofu",Overwrite:true}' \
  "$tmp_dir/old-parameters.json" \
  >"$tmp_dir/old-secret-parameter.json"
chmod 600 "$tmp_dir"/*.json

ssm_updated=true
put_parameter "$tmp_dir/new-access-parameter.json"
put_parameter "$tmp_dir/new-secret-parameter.json"
read_parameters "$tmp_dir/new-parameters.json"
parameters_match_new "$tmp_dir/new-parameters.json"

new_access_key_id="$new_key_id"
new_secret_access_key="$(jq -r .AccessKey.SecretAccessKey "$tmp_dir/new-key.json")"
probe_controller_key "$new_access_key_id" "$new_secret_access_key" new-key
unset new_secret_access_key

(
  cd "$unit"
  AWS_PROFILE="$profile" terragrunt --log-disable plan -no-color -out="$tmp_dir/plan.out"
  AWS_PROFILE="$profile" terragrunt --log-disable show -json "$tmp_dir/plan.out" >"$tmp_dir/plan.json"
  conftest test --policy "$repo_root/policy" --output github "$tmp_dir/plan.json"
  jq -e --argjson revision "$expected_revision" '
    ([.resource_changes[] | select(.mode == "managed" and .change.actions != ["no-op"]) | .address] == ["kubernetes_secret_v1.this"]) and
    ([.resource_changes[].change.actions[] | select(. == "delete")] | length == 0) and
    (.resource_changes[] | select(.address == "kubernetes_secret_v1.this") | .change.actions) == ["update"] and
    (.resource_changes[] | select(.address == "kubernetes_secret_v1.this") | .change.after.data_wo_revision) == $revision and
    ((.resource_changes[] | select(.address == "kubernetes_secret_v1.this") | .change.after.data) // {}) == {}
  ' "$tmp_dir/plan.json" >/dev/null
  json_excludes_new_credentials "$tmp_dir/plan.json"
)

apply_started=true
(
  cd "$unit"
  AWS_PROFILE="$profile" terragrunt --log-disable apply -no-color "$tmp_dir/plan.out"
  AWS_PROFILE="$profile" terragrunt --log-disable state pull >"$tmp_dir/state.json"
)
jq -e '
  [.resources[] | select(.type == "kubernetes_secret_v1") | .instances[].attributes.data] |
  all(. == null or . == {})
' "$tmp_dir/state.json" >/dev/null
json_excludes_new_credentials "$tmp_dir/state.json"

kubectl -n external-secrets get secret aws-ssm-auth -o json >"$tmp_dir/live-secret.json"
jq -e --slurpfile new "$tmp_dir/new-key.json" '
  (.data["access-key-id"] | @base64d) == $new[0].AccessKey.AccessKeyId and
  (.data["secret-access-key"] | @base64d) == $new[0].AccessKey.SecretAccessKey
' "$tmp_dir/live-secret.json" >/dev/null

kubectl wait --for=condition=Ready clustersecretstore/aws-ssm --timeout=120s
kubectl get externalsecrets.external-secrets.io --all-namespaces -o json >"$tmp_dir/external-secrets-before.json"
jq -e '
  (.items | length) > 0 and
  ([.items[] | any(.status.conditions[]?; .type == "Ready" and .status == "True")] | all) and
  ([.items[] | select(.spec.refreshPolicy == "Periodic")] | length) > 0
' "$tmp_dir/external-secrets-before.json" >/dev/null

"${aws_cli[@]}" iam update-access-key \
  --user-name "$iam_user" \
  --access-key-id "$old_key_id" \
  --status Inactive
old_key_inactive=true

old_secret_access_key="$(jq -r --arg secret "$secret_parameter" \
  '.Parameters[] | select(.Name == $secret) | .Value' "$tmp_dir/old-parameters.json")"
old_key_rejected=false
for _ in {1..30}; do
  if ! (
    clear_aws_credential_environment
    export AWS_ACCESS_KEY_ID="$old_key_id"
    export AWS_SECRET_ACCESS_KEY="$old_secret_access_key"
    aws sts get-caller-identity --region "$region" \
      >"$tmp_dir/old-key-probe.json" 2>"$tmp_dir/old-key-probe.err"
  ) && rg -q 'InvalidClientTokenId|UnrecognizedClientException' "$tmp_dir/old-key-probe.err"; then
    old_key_rejected=true
    break
  fi
  sleep 5
done
unset old_secret_access_key
[[ "$old_key_rejected" == true ]]
cutover_epoch="$(date -u +%s)"

fresh_reconcile=false
for _ in {1..90}; do
  kubectl get externalsecrets.external-secrets.io --all-namespaces -o json >"$tmp_dir/external-secrets-after.json"
  if jq -e --argjson cutoff "$cutover_epoch" '
    any(.items[];
      .spec.refreshPolicy == "Periodic" and
      ((try ((.status.refreshTime // "") | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601) catch 0) > $cutoff) and
      any(.status.conditions[]?; .type == "Ready" and .status == "True")
    )
  ' "$tmp_dir/external-secrets-after.json" >/dev/null; then
    fresh_reconcile=true
    break
  fi
  sleep 10
done
[[ "$fresh_reconcile" == true ]]
jq -e '([.items[] | any(.status.conditions[]?; .type == "Ready" and .status == "True")] | all)' \
  "$tmp_dir/external-secrets-after.json" >/dev/null

"${aws_cli[@]}" iam delete-access-key \
  --user-name "$iam_user" \
  --access-key-id "$old_key_id"
old_key_deleted=true
old_key_inactive=false

"${aws_cli[@]}" iam list-access-keys \
  --user-name "$iam_user" \
  --output json >"$tmp_dir/final-keys.json"
jq -e --slurpfile new "$tmp_dir/new-key.json" '
  [.AccessKeyMetadata[] | select(.Status == "Active") | .AccessKeyId] == [$new[0].AccessKey.AccessKeyId] and
  (.AccessKeyMetadata | length) == 1
' "$tmp_dir/final-keys.json" >/dev/null

rotation_complete=true
echo "External Secrets AWS access key rotated; state and consumers verified."
