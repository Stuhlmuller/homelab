#!/usr/bin/env bash
set -euo pipefail
umask 077

[[ $# -le 1 && ( $# -eq 0 || "$1" == "--execute" ) ]] || {
  echo "usage: scripts/octelium-ci-plan-catalog.sh [--execute]" >&2
  exit 2
}

repo="Stuhlmuller/homelab"
domain="stinkyboi.com"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
catalog="docs/examples/octelium/homelab-services.yaml"

for tool in git gh jq yq octeliumctl; do
  command -v "$tool" >/dev/null || {
    echo "error: $tool is required" >&2
    exit 127
  }
done

work="$(mktemp -d "${TMPDIR:-/tmp}/octelium-ci-plan-catalog.XXXXXX")"
trap 'rm -rf -- "$work"' EXIT
target="$work/plan-catalog.yaml"
target_json="$work/plan-catalog.json"

# Select only the staged plan identity, its Policy, and the existing public
# Service whose authorization list must gain that Policy.
yq ea '
  select(
    (.kind == "User" and .metadata.name == "homelab-ci-plan") or
    (.kind == "Policy" and .metadata.name == "homelab-ci-kubernetes-api-plan-access") or
    (.kind == "Service" and .metadata.name == "kubernetes-api-ci")
  )
' "$catalog" >"$target"
yq ea -o=json -I=0 '[.]' "$target" >"$target_json"
jq -e '
  length == 3 and
  (map([.kind, .metadata.name]) | sort) == ([
    ["Policy", "homelab-ci-kubernetes-api-plan-access"],
    ["Service", "kubernetes-api-ci"],
    ["User", "homelab-ci-plan"]
  ] | sort) and
  ([.[] | select(.kind == "User")][0].spec.type == "WORKLOAD") and
  ([.[] | select(.kind == "Policy")][0].spec.rules | map(.name)) == [
    "deny-non-dry-run-writes", "deny-subresources", "read-or-dry-run"
  ] and
  ([.[] | select(.kind == "Service")][0].spec.authorization.policies) == [
    "homelab-ci-kubernetes-api-access", "homelab-ci-kubernetes-api-plan-access"
  ]
' "$target_json" >/dev/null || {
  echo "error: plan catalog selection differs from the reviewed three-resource contract" >&2
  exit 1
}

if [[ $# -eq 0 ]]; then
  echo "Would apply the plan User, Policy, and public Kubernetes API Service binding from ${catalog}."
  exit 0
fi

gh auth status >/dev/null
[[ -z "$(git status --porcelain)" ]] || {
  echo "error: catalog activation requires a clean checkout" >&2
  exit 1
}

verify_current_main() {
  local current_main
  current_main="$(gh api "repos/${repo}/git/ref/heads/main" --jq .object.sha)" || {
    echo "error: unable to resolve current main" >&2
    return 1
  }
  [[ "$current_main" =~ ^[0-9a-f]{40}$ && "$(git rev-parse HEAD)" == "$current_main" ]] || {
    echo "error: catalog activation requires the exact current main commit" >&2
    return 1
  }
}

verify_current_main

desired_user="$(jq -c '.[] | select(.kind == "User")' "$target_json")"
desired_policy="$(jq -c '.[] | select(.kind == "Policy")' "$target_json")"
desired_service="$(jq -c '.[] | select(.kind == "Service")' "$target_json")"

check_optional_resource() {
  local kind="$1" name="$2" desired="$3"
  if octeliumctl get "$kind" "$name" --domain "$domain" -o json >"$work/${kind}.json" 2>"$work/${kind}.error"; then
    # Some octeliumctl errors are printed to stdout with exit status zero.
    if grep -Eiq '^Could not get (User|Policy):.*(not found|NotFound)' "$work/${kind}.json"; then
      return 0
    fi
    jq -e --argjson desired "$desired" '.metadata.name == $desired.metadata.name and .spec == $desired.spec' \
      "$work/${kind}.json" >/dev/null || {
      echo "error: existing plan ${kind} differs from the reviewed catalog" >&2
      return 1
    }
  elif ! grep -Eiq 'not found|does not exist' "$work/${kind}.error"; then
    echo "error: unable to determine whether plan ${kind} exists" >&2
    return 1
  fi
}

check_optional_resource user homelab-ci-plan "$desired_user"
check_optional_resource policy homelab-ci-kubernetes-api-plan-access "$desired_policy"

# Refuse to reconcile unrelated Service drift. Only the plan Policy may be
# added to the existing authorization list; all other Service fields must
# already match the reviewed catalog.
octeliumctl get service kubernetes-api-ci.default --domain "$domain" -o json \
  >"$work/service.json" || {
  echo "error: unable to read the existing public Kubernetes API Service" >&2
  exit 1
}
jq -e --argjson desired "$desired_service" '
  (.spec.authorization.policies == ["homelab-ci-kubernetes-api-access"] or
   .spec.authorization.policies == $desired.spec.authorization.policies) and
  ((.spec | .authorization.policies = $desired.spec.authorization.policies) == $desired.spec)
' "$work/service.json" >/dev/null || {
  echo "error: public Kubernetes API Service has unrelated drift" >&2
  exit 1
}

apply_selected_catalog() {
  local output
  output="$(octeliumctl apply --domain "$domain" --include User --include Policy \
    --include Service "$target" 2>&1)" || {
    printf '%s\n' "$output" >&2
    echo "error: Octelium rejected the selected plan catalog" >&2
    return 1
  }
  if grep -Eq 'Could not (list|create|update|apply)|gRPC error' <<<"$output"; then
    printf '%s\n' "$output" >&2
    echo "error: Octelium reported a failed plan catalog change" >&2
    return 1
  fi
  printf '%s\n' "$output"
}

verify_current_main
apply_selected_catalog >"$work/first-apply.log"

for entry in \
  "user:homelab-ci-plan:$desired_user" \
  "policy:homelab-ci-kubernetes-api-plan-access:$desired_policy" \
  "service:kubernetes-api-ci.default:$desired_service"; do
  kind="${entry%%:*}"
  rest="${entry#*:}"
  name="${rest%%:*}"
  desired="${rest#*:}"
  octeliumctl get "$kind" "$name" --domain "$domain" -o json >"$work/verified-${kind}.json" || {
    echo "error: unable to verify applied plan ${kind}" >&2
    exit 1
  }
  jq -e --argjson expected "$desired" '.spec == $expected.spec' \
    "$work/verified-${kind}.json" >/dev/null || {
    echo "error: applied plan ${kind} differs from the reviewed catalog" >&2
    exit 1
  }
done

verify_current_main
apply_selected_catalog >"$work/second-apply.log"
grep -Fq 'No applied changes in Cluster Core resources' "$work/second-apply.log" || {
  echo "error: second plan catalog apply did not prove an empty live diff" >&2
  exit 1
}

echo "Plan User, Policy, and public Service binding match the reviewed catalog."
