# Invoked by the pinned Nix application from the repository root.
set -euo pipefail

policy=scripts/config/nix-cache.json
if [[ "${1:-}" == --policy ]]; then
    policy="$2"
    shift 2
fi
publish=false
if [[ "${1:-}" == --publish ]]; then
    publish=true
    shift
fi
target=//bazel:all
if [[ "${1:-}" == --target ]]; then
    target="//bazel:$2"
    shift 2
fi

# Keep temporary machine-specific paths out of Bazel's test action inputs.
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
system="$(nix eval --impure --raw --expr builtins.currentSystem)"
nix eval --no-update-lock-file --no-write-lock-file --json ".#checks.${system}" \
    --apply 'checks: builtins.mapAttrs (_: check: check.drvPath) {
      inherit (checks) offline-tests manifest-policy openwiki-setup xerj-autoindex;
    }' > "$work/derivations.json"
jq --arg nix "$(command -v nix)" --slurpfile policy "$policy" '
    ($policy[0] | [.url, .publicKey]) as $cache
    | if all($cache[]; type == "string" and (test("[\r\n]") | not)) then
        map_values([$nix, .] + $cache)
      else error("Invalid Nix cache policy")
      end
' "$work/derivations.json" > "$work/recipes.json"

cache_host=bazel-cache.stinkyboi.com
args=(
    --repo_env="HOMELAB_BAZEL_CHECKS=$work/recipes.json"
    --remote_cache="https://$cache_host"
    --remote_timeout=8s
    --remote_retries=0
)
publish_args=()
publish_startup=()
if [[ "${GITHUB_ACTIONS:-}" == true ]]; then
    if (( $# )) || [[ "$target" != //bazel:all || "$publish" == true ]]; then
        echo 'GitHub Actions runs all offline checks with read-only cache access.' >&2
        exit 2
    fi
    args+=(--remote_upload_local_results=false)
elif [[ "$publish" == true ]]; then
    if (( $# )); then
        echo 'Use --target to select a published check.' >&2
        exit 2
    fi
    command -v aws >/dev/null || {
        echo 'Run the publisher in nix develop with an authorized AWS session.' >&2
        exit 2
    }
    publish_args=(--remote_upload_local_results=true
                  --credential_helper_timeout=25s
                  --credential_helper="$cache_host=$PWD/scripts/ci/bazel-cache-credential.py")
    # A private output base makes a prior local-only test run eligible for upload.
    publish_startup=(--output_base="$work/publisher")
fi

startup=(--batch --nosystem_rc --nohome_rc)
if [[ -r /etc/ssl/certs/java/cacerts ]]; then
    startup+=(--host_jvm_args=-Djavax.net.ssl.trustStore=/etc/ssl/certs/java/cacerts)
fi
bazel "${startup[@]}" "${publish_startup[@]}" test "${args[@]}" "${publish_args[@]}" "$@" "$target"

if [[ "$publish" == true ]]; then
    bazel "${startup[@]}" --output_base="$work/reader" test "${args[@]}" \
        --build_event_json_file="$work/reader.json" "$target"
    if ! jq -es '
      map(.testResult // empty)
      | length > 0 and all(.[]; .executionInfo.cachedRemotely == true)
    ' "$work/reader.json" >/dev/null; then
        echo 'The tests passed, but the read-only cache lookup missed a result.' >&2
        exit 1
    fi
fi
