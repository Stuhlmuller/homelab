#!/usr/bin/env bash
set -euo pipefail
umask 077

repo="Stuhlmuller/homelab"
environment="homelab-production"
domain="stinkyboi.com"
talos_node="10.1.0.199"
talos_endpoint="talos-api.homelab.local.stinkyboi.com"
octelium_user="homelab-ci"
octelium_policy="homelab-platform-talos-ci-access"
octelium_service="talos-api-ci.homelab"
octelium_credential="homelab-platform-talos-ci"

usage() {
  cat <<'USAGE'
Usage: scripts/platform-maintenance-credentials.sh octelium-client
       scripts/platform-maintenance-credentials.sh talos-client --operator-talosconfig ABSOLUTE_PATH

Run from an exact, clean main checkout. The first mode needs an authenticated
Octelium administrator and creates or rotates only the dedicated CLIENT
credential for the protected Talos TCP service. The second uses a valid local
Talos os:admin client to issue a distinct 30-day os:admin client, verifies it
with a read-only Talos call, and publishes it. Both write only their fixed
homelab-production GitHub environment secret. Neither prints credential data.
USAGE
}

mode="${1:-}"
case "$mode" in
  octelium-client)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    ;;
  talos-client)
    [[ $# -eq 3 && "$2" == "--operator-talosconfig" && "$3" == /* ]] || {
      usage >&2
      exit 2
    }
    operator_talosconfig="$3"
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

for command in git gh jq; do
  command -v "$command" >/dev/null || { echo "error: $command is required" >&2; exit 127; }
done
if [[ "$mode" == "octelium-client" ]]; then
  command -v octeliumctl >/dev/null || { echo 'error: octeliumctl is required' >&2; exit 127; }
else
  for command in talosctl yq base64; do
    command -v "$command" >/dev/null || { echo "error: $command is required" >&2; exit 127; }
  done
fi

root="$(git rev-parse --show-toplevel)"
cd "$root"
main_sha="$(gh api "repos/${repo}/git/ref/heads/main" --jq .object.sha)"
[[ "$main_sha" =~ ^[0-9a-f]{40}$ ]] || { echo 'error: invalid main SHA' >&2; exit 1; }
[[ "$(git rev-parse HEAD)" == "$main_sha" && -z "$(git status --porcelain)" ]] || {
  echo 'error: credential publication requires the exact, clean current main checkout' >&2
  exit 1
}
gh auth status >/dev/null
gh secret list --repo "$repo" --env "$environment" --json name >/dev/null

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

verify_secret() {
  local name="$1"
  gh secret list --repo "$repo" --env "$environment" --json name |
    jq -e --arg name "$name" 'any(.[]; .name == $name)' >/dev/null || {
      echo "error: GitHub did not confirm environment secret ${name}" >&2
      return 1
    }
}

publish_octelium_client() {
  local existing_count credential_args=()

  octeliumctl get user "$octelium_user" --domain "$domain" -o json >"$work/user.json"
  jq -e --arg name "$octelium_user" \
    '.metadata.name == $name and .spec.type == "WORKLOAD"' \
    "$work/user.json" >/dev/null || {
      echo 'error: dedicated Octelium WORKLOAD user differs from reviewed catalog' >&2
      return 1
    }
  octeliumctl get policy "$octelium_policy" --domain "$domain" -o json >"$work/policy.json"
  jq -e --arg name "$octelium_policy" --arg user "$octelium_user" \
    --arg service "$octelium_service" '
      .metadata.name == $name and
      (.spec.rules | length) == 1 and
      .spec.rules[0].name == "protected-maintenance-client" and
      .spec.rules[0].effect == "ALLOW" and
      ([.spec.rules[0].condition.all.of[].match] == [
        "ctx.user.metadata.name == \"" + $user + "\"",
        "ctx.user.spec.type == \"WORKLOAD\"",
        "ctx.session.status.type == \"CLIENT\"",
        "ctx.service.metadata.name == \"" + $service + "\"",
        "ctx.service.spec.mode == \"TCP\""
      ])' "$work/policy.json" >/dev/null || {
        echo 'error: Octelium CLIENT policy differs from reviewed catalog' >&2
        return 1
      }
  octeliumctl get service "$octelium_service" --domain "$domain" -o json >"$work/service.json"
  jq -e --arg name "$octelium_service" --arg policy "$octelium_policy" '
    .metadata.name == $name and .spec.isPublic == false and
    .spec.mode == "TCP" and .spec.port == 50000 and
    .spec.authorization.policies == [$policy] and
    .spec.config.upstream.url == "tcp://10.1.0.199:50000"
  ' "$work/service.json" >/dev/null || {
    echo 'error: Octelium Talos TCP service differs from reviewed catalog' >&2
    return 1
  }

  octeliumctl get creds --items-per-page 1000 --domain "$domain" -o json >"$work/creds.json"
  if grep -Eq '^[[:space:]]*No Credentials found[[:space:]]*$' "$work/creds.json"; then
    printf '{"items":[]}' >"$work/creds.json"
  fi
  jq -e 'type == "object" and (.items | type == "array")' "$work/creds.json" >/dev/null || {
    echo 'error: invalid Octelium credential list' >&2
    return 1
  }
  existing_count="$(jq -r --arg name "$octelium_credential" \
    '[.items[] | select(.metadata.name == $name)] | length' "$work/creds.json")"
  [[ "$existing_count" == 0 || "$existing_count" == 1 ]] || {
    echo 'error: duplicate dedicated Octelium credential' >&2
    return 1
  }
  if [[ "$existing_count" == 1 ]]; then
    jq -e --arg name "$octelium_credential" --arg user "$octelium_user" \
      --arg policy "$octelium_policy" '
        .items[] | select(.metadata.name == $name) |
        .spec.user == $user and .spec.type == "AUTH_TOKEN" and
        .spec.sessionType == "CLIENT" and
        .spec.authorization.policies == [$policy]
      ' "$work/creds.json" >/dev/null || {
        echo 'error: refusing to rotate an unexpected Octelium credential' >&2
        return 1
      }
    credential_args+=(--rotate)
  fi

  octeliumctl create cred --domain "$domain" \
    --user "$octelium_user" --policy "$octelium_policy" \
    --type auth-token --session-type client --expire-in 30days \
    "${credential_args[@]}" -o json "$octelium_credential" >"$work/credential.json"
  jq -e '.authenticationToken.authenticationToken | type == "string" and length > 40' \
    "$work/credential.json" >/dev/null || {
      echo 'error: Octelium did not return the expected credential token' >&2
      return 1
    }
  jq -rj '.authenticationToken.authenticationToken' "$work/credential.json" |
    gh secret set OCE_OCTELIUM_CLIENT_AUTH_TOKEN --repo "$repo" --env "$environment" >/dev/null
  verify_secret OCE_OCTELIUM_CLIENT_AUTH_TOKEN
  echo 'Dedicated Octelium CLIENT credential published and secret name verified.'
}

publish_talos_client() {
  local operator_cert client_cert operator_key client_key
  [[ -s "$operator_talosconfig" && ! -L "$operator_talosconfig" ]] || {
    echo 'error: operator Talos client config must be a nonempty regular file' >&2
    return 1
  }
  talosctl --talosconfig "$operator_talosconfig" config info -o json >"$work/operator-info.json"
  jq -e '.roles | index("os:admin") != null' "$work/operator-info.json" >/dev/null || {
    echo 'error: operator Talos client lacks os:admin' >&2
    return 1
  }
  talosctl --talosconfig "$operator_talosconfig" --endpoints "$talos_node" \
    --nodes "$talos_node" version --short >/dev/null

  talosctl --talosconfig "$operator_talosconfig" --endpoints "$talos_node" \
    --nodes "$talos_node" config new "$work/talosconfig" \
    --roles os:admin --crt-ttl 720h >/dev/null
  chmod 0600 "$work/talosconfig"
  talosctl --talosconfig "$work/talosconfig" config endpoint "$talos_endpoint" >/dev/null
  talosctl --talosconfig "$work/talosconfig" config node "$talos_node" >/dev/null
  talosctl --talosconfig "$work/talosconfig" config info -o json >"$work/client-info.json"
  jq -e --arg endpoint "$talos_endpoint" --arg node "$talos_node" '
    .roles == ["os:admin"] and .endpoints == [$endpoint] and
    .nodes == [$node] and (.certNotAfter | type == "string" and length > 0)
  ' "$work/client-info.json" >/dev/null || {
    echo 'error: generated Talos client does not match the protected CI contract' >&2
    return 1
  }
  operator_cert="$(yq -o=json '.' "$operator_talosconfig" |
    jq -er '.context as $context | .contexts[$context].crt')"
  client_cert="$(yq -o=json '.' "$work/talosconfig" |
    jq -er '.context as $context | .contexts[$context].crt')"
  operator_key="$(yq -o=json '.' "$operator_talosconfig" |
    jq -er '.context as $context | .contexts[$context].key')"
  client_key="$(yq -o=json '.' "$work/talosconfig" |
    jq -er '.context as $context | .contexts[$context].key')"
  [[ "$operator_cert" != "$client_cert" && "$operator_key" != "$client_key" ]] || {
    echo 'error: generated Talos client reused operator identity' >&2
    return 1
  }
  unset operator_cert client_cert operator_key client_key
  talosctl --talosconfig "$work/talosconfig" --endpoints "$talos_node" \
    --nodes "$talos_node" version --short >/dev/null
  base64 <"$work/talosconfig" | tr -d '\n' |
    gh secret set OCE_TALOSCONFIG_B64 --repo "$repo" --env "$environment" >/dev/null
  verify_secret OCE_TALOSCONFIG_B64
  echo 'Distinct 30-day Talos CI client published and secret name verified.'
}

case "$mode" in
  octelium-client) publish_octelium_client ;;
  talos-client) publish_talos_client ;;
esac
