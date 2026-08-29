#!/usr/bin/env bash
set -euo pipefail

mode="${1:-}"
owner_token="${2:-}"
profile="${3:-}"
lock_parameter="/homelab/locks/aws-ssm-secret-maintenance"
region="us-west-2"

if [[ "$mode" != "--self-test" &&
  ( ! "$owner_token" =~ ^[A-Za-z0-9._:@/-]{1,128}$ || "$profile" =~ [[:space:]] ) ]]; then
  echo "usage: $0 --acquire|--release OWNER_TOKEN [AWS_PROFILE]" >&2
  exit 2
fi

aws_cli=(aws)
if [[ -n "$profile" ]]; then
  aws_cli+=(--profile "$profile")
fi

acquire_lock() {
  local current_owner=""
  local put_succeeded=false

  if "${aws_cli[@]}" ssm put-parameter \
    --region "$region" \
    --name "$lock_parameter" \
    --type String \
    --value "$owner_token" \
    --no-overwrite \
    --output json >/dev/null 2>&1; then
    put_succeeded=true
  fi
  current_owner="$(
    "${aws_cli[@]}" ssm get-parameter \
      --region "$region" \
      --name "$lock_parameter" \
      --query Parameter.Value \
      --output text 2>/dev/null || true
  )"
  if [[ "$current_owner" == "$owner_token" ]]; then
    return 0
  fi
  if [[ "$put_succeeded" == true ]]; then
    echo "SSM maintenance lock was created but ownership could not be verified; retain it and investigate." >&2
  else
    echo "Another operation owns the SSM secret-maintenance lock." >&2
  fi
  return 1
}

release_lock() {
  local current_owner=""

  current_owner="$(
    "${aws_cli[@]}" ssm get-parameter \
      --region "$region" \
      --name "$lock_parameter" \
      --query Parameter.Value \
      --output text 2>/dev/null || true
  )"
  if [[ "$current_owner" != "$owner_token" ]]; then
    echo "Refusing to release an absent or foreign SSM secret-maintenance lock." >&2
    return 1
  fi
  "${aws_cli[@]}" ssm delete-parameter \
    --region "$region" \
    --name "$lock_parameter" >/dev/null
}

self_test() {
  mock_lock_owner=""
  mock_delete_fails=false
  # shellcheck disable=SC2329 # Invoked indirectly through the aws_cli array.
  aws() {
    case "$*" in
      *"ssm put-parameter"*)
        [[ -z "$mock_lock_owner" ]] || return 254
        mock_lock_owner="$owner_token"
        printf '{}\n'
        ;;
      *"ssm get-parameter"*)
        [[ -n "$mock_lock_owner" ]] || return 254
        printf '%s\n' "$mock_lock_owner"
        ;;
      *"ssm delete-parameter"*)
        [[ "$mock_delete_fails" == false ]] || return 254
        mock_lock_owner=""
        ;;
      *) return 2 ;;
    esac
  }

  owner_token=test-owner
  acquire_lock
  [[ "$mock_lock_owner" == "$owner_token" ]]
  release_lock
  [[ -z "$mock_lock_owner" ]]

  mock_lock_owner=other-owner
  if acquire_lock >/dev/null 2>&1 || release_lock >/dev/null 2>&1; then
    echo "foreign lock fixture unexpectedly passed" >&2
    exit 1
  fi
  mock_lock_owner="$owner_token"
  mock_delete_fails=true
  if release_lock >/dev/null 2>&1; then
    echo "failed lock deletion fixture unexpectedly passed" >&2
    exit 1
  fi
  [[ "$mock_lock_owner" == "$owner_token" ]]
  echo "SSM secret-maintenance lock checks passed"
}

case "$mode" in
  --acquire) acquire_lock ;;
  --release) release_lock ;;
  --self-test) self_test ;;
  *)
    echo "usage: $0 --acquire|--release OWNER_TOKEN [AWS_PROFILE]" >&2
    exit 2
    ;;
esac
