#!/usr/bin/env bash
set -euo pipefail

# Fixed production destinations; only ephemeral GitHub runner state is changed.
[[ $# -eq 1 && ("$1" == publish-cordium || "$1" == publish || "$1" == publish-harbor-core || "$1" == publish-openclaw-enterprise || "$1" == mirror || "$1" == mirror-fleet || "$1" == mirror-bazarr || "$1" == mirror-traefik || "$1" == mirror-chainguard || "$1" == mirror-mastodon || "$1" == mirror-harbor || "$1" == mirror-renovate || "$1" == mirror-dns || "$1" == mirror-litellm || "$1" == mirror-prometheus || "$1" == mirror-postgres) ]] || {
  echo 'Usage: harbor-publish.sh publish|publish-cordium|publish-harbor-core|publish-openclaw-enterprise|mirror|mirror-fleet|mirror-bazarr|mirror-traefik|mirror-chainguard|mirror-mastodon|mirror-harbor|mirror-renovate|mirror-dns|mirror-litellm|mirror-prometheus|mirror-postgres' >&2
  exit 2
}
mode="$1"
publish_outputs=(backend frontend)
core_publication=false
enterprise_publication=false
publish_phase="preflight"
if [[ "$mode" == publish-openclaw-enterprise ]]; then
  # Preflight may fail before the private transport cleanup trap is installed.
  trap 'if [[ $? -ne 0 && -n "${GITHUB_STEP_SUMMARY:-}" ]]; then printf "Enterprise image publication failed at phase: %s\n" "$publish_phase" >>"$GITHUB_STEP_SUMMARY"; fi' EXIT
fi
publish_names=(homelab-nofx-backend homelab-nofx-frontend)
if [[ "$mode" == publish-harbor-core ]]; then
  core_publication=true
  mode=publish
  publish_names=(homelab-harbor-core)
  [[ "${GITHUB_EVENT_NAME:-}" == workflow_dispatch ]]
  [[ "${GITHUB_WORKFLOW_REF:-}" == Stuhlmuller/homelab/.github/workflows/harbor-core-images.yml@refs/heads/main ]]
fi
if [[ "$mode" == publish-cordium ]]; then
  [[ "${GITHUB_EVENT_NAME:-}" == workflow_dispatch ]]
  mode=publish
  publish_names=(homelab-cordium-runner homelab-cordium-controller)
  publish_outputs=(runner controller)
fi
if [[ "$mode" == publish-openclaw-enterprise ]]; then
  enterprise_publication=true
  [[ "${GITHUB_EVENT_NAME:-}" == workflow_dispatch ]]
  [[ "${GITHUB_WORKFLOW_REF:-}" == Stuhlmuller/homelab/.github/workflows/openclaw-enterprise-images.yml@refs/heads/main ]]
  mode=publish
  publish_names=(homelab-oce-controller homelab-oce-runtime homelab-oce-cli homelab-oce-operator)
  publish_outputs=(controller runtime cli operator)
fi
mirror_manifest=scripts/config/harbor-images.json
if [[ "$mode" == mirror-fleet ]]; then
  mode=mirror
  mirror_manifest=scripts/config/harbor-fleet-images.json
elif [[ "$mode" == mirror-bazarr ]]; then
  mode=mirror
  mirror_manifest=scripts/config/harbor-bazarr-images.json
elif [[ "$mode" == mirror-traefik ]]; then
  mode=mirror
  mirror_manifest=scripts/config/harbor-traefik-images.json
elif [[ "$mode" == mirror-mastodon ]]; then
  mode=mirror
  mirror_manifest=scripts/config/harbor-mastodon-images.json
elif [[ "$mode" == mirror-harbor ]]; then
  mode=mirror
  mirror_manifest=scripts/config/harbor-runtime-images.json
elif [[ "$mode" == mirror-renovate ]]; then
  mode=mirror
  mirror_manifest=scripts/config/harbor-renovate-images.json
elif [[ "$mode" == mirror-chainguard ]]; then
  mode=mirror
  mirror_manifest=scripts/config/harbor-chainguard-images.json
elif [[ "$mode" == mirror-dns ]]; then
  mode=mirror
  mirror_manifest=scripts/config/harbor-dns-images.json
elif [[ "$mode" == mirror-litellm ]]; then
  mode=mirror
  mirror_manifest=scripts/config/harbor-litellm-images.json
elif [[ "$mode" == mirror-prometheus ]]; then
  mode=mirror
  mirror_manifest=scripts/config/harbor-prometheus-images.json
elif [[ "$mode" == mirror-postgres ]]; then
  mode=mirror
  mirror_manifest=scripts/config/harbor-postgres-images.json
fi
[[ "${GITHUB_ACTIONS:-}" == true && "$(uname -s)" == Linux ]]
[[ "${GITHUB_REPOSITORY:-}" == Stuhlmuller/homelab ]]
[[ "${GITHUB_REF:-}" == refs/heads/main ]]
[[ "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ ]]
if [[ "${GITHUB_EVENT_NAME:-}" == workflow_dispatch ]]; then
  [[ "${EXPECTED_SHA:-}" == "$GITHUB_SHA" ]]
else
  [[ "$mode" == publish && "${GITHUB_EVENT_NAME:-}" == push ]]
fi

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repository_root"
[[ "$(git rev-parse HEAD)" == "$GITHUB_SHA" ]]
[[ "$(git ls-remote https://github.com/Stuhlmuller/homelab.git refs/heads/main | cut -f1)" == "$GITHUB_SHA" ]]

# Enroll the independently checked public key through review before publication.
if [[ "$mode" == publish ]]; then
  signing_fingerprint="$(jq -er '.public_key_sha256 | strings | select(test("^[0-9a-f]{64}$"))' scripts/config/harbor-signing.json)" || {
    echo 'Enroll the Harbor signing public-key fingerprint before publishing.' >&2
    exit 1
  }
fi

# Validate the mirror inventory before installing credentials or contacting AWS.
if [[ "$mode" == mirror ]]; then
  manifest="$mirror_manifest"
  jq --exit-status '
    (keys == ["images"]) and
    (.images | type == "array" and length > 0 and length <= 1000) and
    ([.images[].source] | unique | length) == (.images | length) and
    ([.images[].source | split("@")[0] | select(contains(":"))] |
      (unique | length) == length) and
    all(.images[];
      keys == ["source"] and
      (.source | type == "string" and test("^(docker[.]io|ghcr[.]io|quay[.]io|registry[.]k8s[.]io|gcr[.]io|mcr[.]microsoft[.]com|public[.]ecr[.]aws|ecr-public[.]aws[.]com|lscr[.]io|xpkg[.]crossplane[.]io|docker[.]langfuse[.]com|cgr[.]dev|codeberg[.]org|factory[.]talos[.]dev)/[a-z0-9]+([._-][a-z0-9]+)*(/[a-z0-9]+([._-][a-z0-9]+)*)*(:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?@sha256:[0-9a-f]{64}$")))
  ' "$manifest" >/dev/null
  if [[ "$manifest" == scripts/config/harbor-dns-images.json ]]; then
    jq --exit-status '.images == [{"source":"codeberg.org/k8s-gateway/k8s_gateway:1.9.0@sha256:0b556f261d46873d7d2e86e5d345bb99db30de6b3869b83e32d273a466e980e4"}]' "$manifest" >/dev/null
  fi
  if [[ "$manifest" == scripts/config/harbor-litellm-images.json ]]; then
    jq --exit-status '.images == [{"source":"ghcr.io/berriai/litellm-database@sha256:2791e3241d7fa59ad942c54c237fb0d53a140b52fad2bd4b40c14a873dbc14a8"}]' "$manifest" >/dev/null
  fi
  if [[ "$manifest" == scripts/config/harbor-prometheus-images.json ]]; then
    jq --exit-status '.images == [{"source":"quay.io/prometheus/prometheus:v3.11.3-distroless@sha256:cff72a3f49918f41c4b5c8a6174dd8433036bebf7878120da538b3720ba3fa0d"}]' "$manifest" >/dev/null
  fi
  if [[ "$manifest" == scripts/config/harbor-postgres-images.json ]]; then
    jq --exit-status '.images == [{"source":"docker.io/library/postgres@sha256:3725f4e2499eef5134592b3b4ab79a543ed7f8e533b05b5b637af926630f6650"}]' "$manifest" >/dev/null
  fi
  if [[ "$manifest" != scripts/config/harbor-images.json ]]; then
    # The fixed rollout scope may only select exact reviewed catalog entries.
    # No caller-supplied repository, digest, manifest path, or destination exists.
    jq --exit-status --slurpfile inventory scripts/config/harbor-images.json '
      ($inventory | length == 1) and
      all(.images[]; . as $image | any($inventory[0].images[]; . == $image))
    ' "$manifest" >/dev/null
  fi
fi

: "${RUNNER_TEMP:?RUNNER_TEMP must be set by GitHub Actions}"
if [[ "$mode" == publish ]]; then
  : "${GITHUB_OUTPUT:?GITHUB_OUTPUT must be set by GitHub Actions}"
fi
: "${OCTELIUM_AUTH_TOKEN:?The production Octelium CI credential is required}"
[[ "${KUBE_API_SERVER_URL:-}" == https://kubernetes-api-ci.stinkyboi.com ]]
[[ ! -e "$HOME/.kube/config" ]] || {
  echo 'Refusing to replace an existing runner kubeconfig.' >&2
  exit 1
}
if grep -Eq '(^|[[:space:]])harbor[.]stinkyboi[.]com([[:space:]]|$)|# homelab-harbor-ci$' /etc/hosts; then
  echo 'Refusing to replace existing Harbor host routing.' >&2
  exit 1
fi

umask 077
if [[ "$mode" == mirror ]]; then
  rm -f -- "$RUNNER_TEMP/harbor-publication-error.gpg"
fi
scratch="$(mktemp -d "${RUNNER_TEMP}/harbor-publish.XXXXXX")"
if [[ "$mode" == mirror ]]; then
  # Capture setup stderr too; transfer commands replace it with their own buffer.
  exec 2>"$scratch/mirror-error"
fi
forward_pid=""
hosts_added=false
kubeconfig_added=false
mirror_source=setup
mirror_phase="setup"
mirror_category="command-failed"
publish_phase="private-route"
cleanup() {
  local result=$?
  trap - EXIT INT TERM
  if "$enterprise_publication" && [[ "$result" -eq 0 ]]; then
    publish_phase="cleanup"
  fi
  if [[ "$mode" == mirror && "$mirror_category" == command-failed && -f "$scratch/mirror-error" ]]; then
    if grep -Eiq 'toomanyrequests|too many requests|status code:? 429' "$scratch/mirror-error"; then
      mirror_category="rate-limited"
    elif grep -Fqi 'no space left on device' "$scratch/mirror-error"; then
      mirror_category="storage-full"
    elif grep -Eiq 'quota exceeded|exceed[^[:cntrl:]]*quota' "$scratch/mirror-error"; then
      mirror_category="quota-exceeded"
    elif grep -Eiq '403 Forbidden|HTTP status(:| code:?)?[[:space:]]*403|status code:?[[:space:]]*403' "$scratch/mirror-error"; then
      mirror_category="http-forbidden"
    elif grep -Eiq '413 Request Entity Too Large|HTTP status(:| code:?)?[[:space:]]*413|status code:?[[:space:]]*413' "$scratch/mirror-error"; then
      mirror_category="request-too-large"
    elif grep -Eiq 'HTTP status(:| code:?)?[[:space:]]*5[0-9]{2}|status code:?[[:space:]]*5[0-9]{2}|50[234] (Bad Gateway|Service Unavailable|Gateway Timeout)' "$scratch/mirror-error"; then
      mirror_category="server-error"
    elif grep -Eiq 'unauthorized|authentication required|access denied|denied:' "$scratch/mirror-error"; then
      mirror_category="authentication-denied"
    elif grep -Eiq 'connection refused|connection reset|unexpected EOF|TLS handshake timeout|i/o timeout|context deadline exceeded' "$scratch/mirror-error"; then
      mirror_category="transport-failed"
    elif [[ "$mirror_phase" == destination-copy ]] && grep -Eiq 'writing blob:|uploading blob:' "$scratch/mirror-error"; then
      mirror_category="blob-upload-failed"
    elif [[ "$mirror_phase" == destination-copy ]] && grep -Eiq 'writing manifest:|uploading manifest:' "$scratch/mirror-error"; then
      mirror_category="manifest-upload-failed"
    elif grep -Eiq 'manifest unknown|name unknown' "$scratch/mirror-error"; then
      mirror_category="manifest-missing"
    fi
  fi
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
  if [[ "$mode" == mirror && "$result" -ne 0 ]]; then
    for diagnostic in port-forward.log readiness.log; do
      if [[ -s "$scratch/$diagnostic" ]]; then
        printf '\n%s:\n' "$diagnostic" >>"$scratch/mirror-error"
        tail -c 65536 -- "$scratch/$diagnostic" >>"$scratch/mirror-error"
      fi
    done
    if [[ -s "$scratch/mirror-error" ]]; then
      if ! python3 -I scripts/ci/harbor-encrypt-diagnostic.py "$scratch/mirror-error" \
          "$RUNNER_TEMP/harbor-publication-error.gpg" >"$scratch/encryption-status" 2>&1; then
        rm -f -- "$RUNNER_TEMP/harbor-publication-error.gpg"
      fi
    fi
  fi
  rm -rf -- "$scratch" || result=1
  if "$enterprise_publication" && [[ "$result" -ne 0 && -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    # Only a fixed publisher phase is public; transfer output remains encrypted.
    printf "Enterprise image publication failed at phase: %s\n" "$publish_phase" >>"$GITHUB_STEP_SUMMARY" || result=1
  fi
  if [[ "$mode" == mirror && "$result" -ne 0 ]]; then
    # Only reviewed catalog text, fixed labels, and the exit status are public.
    printf 'source=%s\nphase=%s\nexit_status=%s\ncategory=%s\n' \
      "$mirror_source" "$mirror_phase" "$result" "$mirror_category" >"$RUNNER_TEMP/harbor-mirror-status"
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Reuse the declared clientless Octelium Kubernetes CI lane. Kubernetes streams
# carry image uploads, avoiding the public HTTP Tunnel's request-size limit.
kubeconfig_added=true
bash scripts/ci/install-kubeconfig.sh
kubectl --request-timeout=15s version >/dev/null
cp "$(command -v kubectl)" "$scratch/kubectl"
chmod 700 "$scratch/kubectl"
sudo -n setcap cap_net_bind_service=+ep "$scratch/kubectl"
forward_timeout=2400
[[ "$mode" != mirror && "$mode" != mirror-renovate ]] || forward_timeout=19800
start_private_forward() {
  local attempt ready status
  for attempt in 1 2 3; do
    timeout --signal=TERM --kill-after=5s "$forward_timeout" \
      "$scratch/kubectl" --kubeconfig "$HOME/.kube/config" \
      --namespace traefik port-forward --address 127.0.0.1 \
      service/traefik-private 443:443 >>"$scratch/port-forward.log" 2>&1 &
    forward_pid=$!
    ready=false
    for _ in {1..30}; do
      if ! kill -0 "$forward_pid" 2>/dev/null; then
        break
      fi
      if status="$(curl --silent --show-error --noproxy '*' --max-time 5 \
        --output /dev/null --write-out '%{http_code}' https://harbor.stinkyboi.com/v2/ \
        2>"$scratch/readiness.log")" && [[ "$status" == 401 ]]; then
        ready=true
        break
      fi
      sleep 2
    done
    if "$ready" && kill -0 "$forward_pid" 2>/dev/null; then
      return 0
    fi
    stop_private_forward
    if [[ "$attempt" -lt 3 ]]; then
      sleep "$attempt"
    fi
  done
  echo 'Harbor TLS and private registry challenge are not ready.' >&2
  return 1
}

stop_private_forward() {
  if [[ -n "$forward_pid" ]]; then
    kill -TERM "$forward_pid" 2>/dev/null || true
    wait "$forward_pid" 2>/dev/null || true
    forward_pid=""
  fi
}

hosts_added=true
printf '%s\n' '127.0.0.1 harbor.stinkyboi.com # homelab-harbor-ci' |
  sudo -n tee -a /etc/hosts >/dev/null
start_private_forward

# Credentials stay in restrictive temporary files; transfer output is withheld
# by the workflow. Harbor validates its normal public hostname and certificate.
if [[ "$mode" == mirror ]]; then
  aws ssm get-parameter --region us-west-2 \
    --name /homelab/harbor/mirror-robot-push-password --with-decryption \
    --query Parameter.Value --output text >"$scratch/mirror-publisher-password"
  [[ -s "$scratch/mirror-publisher-password" ]]
  skopeo login --authfile "$scratch/mirror-publisher-auth.json" \
    --username "robot\$mirror+publisher" --password-stdin harbor.stinkyboi.com \
    <"$scratch/mirror-publisher-password" >/dev/null
  mkdir "$scratch/regctl-empty-docker"
  printf '%s\n' '{"auths":{}}' >"$scratch/regctl-empty-docker/config.json"
  REGCTL_CONFIG="$scratch/regctl-publisher.json" DOCKER_CONFIG="$scratch/regctl-empty-docker" \
    regctl registry login harbor.stinkyboi.com --user "robot\$mirror+publisher" \
    --pass-stdin --skip-check <"$scratch/mirror-publisher-password" >/dev/null
  rm -f -- "$scratch/mirror-publisher-password"

  # Keep the publisher credential on destination writes only. This distinct
  # pull identity is the receipt for the private Harbor consumer path.
  aws ssm get-parameter --region us-west-2 \
    --name /homelab/harbor/mirror-robot-pull-password --with-decryption \
    --query Parameter.Value --output text >"$scratch/mirror-pull-password"
  [[ -s "$scratch/mirror-pull-password" ]]
  skopeo login --authfile "$scratch/mirror-pull-auth.json" \
    --username "robot\$mirror+pull" --password-stdin harbor.stinkyboi.com \
    <"$scratch/mirror-pull-password" >/dev/null
  REGCTL_CONFIG="$scratch/regctl-pull.json" DOCKER_CONFIG="$scratch/regctl-empty-docker" \
    regctl registry login harbor.stinkyboi.com --user "robot\$mirror+pull" \
    --pass-stdin --skip-check <"$scratch/mirror-pull-password" >/dev/null
  rm -f -- "$scratch/mirror-pull-password"
else
  publish_phase="harbor-auth"
  aws ssm get-parameter --region us-west-2 \
    --name /homelab/harbor/robot-push-password --with-decryption \
    --query Parameter.Value --output text >"$scratch/harbor-password"
  [[ -s "$scratch/harbor-password" ]]
  skopeo login --authfile "$scratch/auth.json" --username "robot\$homelab+publisher" \
    --password-stdin harbor.stinkyboi.com <"$scratch/harbor-password" >/dev/null
  mkdir "$scratch/docker"
  docker --config "$scratch/docker" login --username "robot\$homelab+publisher" \
    --password-stdin harbor.stinkyboi.com <"$scratch/harbor-password" >/dev/null
  rm -f -- "$scratch/harbor-password"
fi

if [[ "$mode" == mirror ]]; then
  # Only anonymous upstream reads may populate this public project. Publish real
  # artifacts, not proxy-cache entries that remain dependent on upstream state.
  printf '%s\n' '{"auths":{}}' >"$scratch/anonymous-auth.json"
  mirror_retryable_server_error() {
    grep -Eiq 'HTTP status(:| code:?)?[[:space:]]*5[0-9]{2}|status code:?[[:space:]]*5[0-9]{2}|50[234] (Bad Gateway|Service Unavailable|Gateway Timeout)' "$scratch/mirror-error"
  }
  mirror_retryable_read_error() {
    ! grep -Eiq 'unauthorized|forbidden|denied|authentication required|manifest unknown|name unknown|not found|blob unknown|digest mismatch|digest invalid|hash mismatch|preserve digests|HTTP status(:| code:?)?[[:space:]]*4[0-9]{2}|status code:?[[:space:]]*4[0-9]{2}' "$scratch/mirror-error" &&
      { mirror_retryable_server_error ||
        { ! grep -Eiq 'HTTP status|status code' "$scratch/mirror-error" &&
          grep -Eiq 'connection refused|connection reset|unexpected EOF|TLS handshake timeout|i/o timeout|context deadline exceeded' "$scratch/mirror-error"; }; }
  }
  while IFS= read -r source; do
    oci_index_copy=false
    source_digest="${source##*@}"
    source_repository="${source%@*}"
    source_repository="${source_repository%:*}"
    destination="harbor.stinkyboi.com/mirror/${source_repository}"
    tag="${source_digest#sha256:}"
    mirror_source="$source"
    mirror_phase="digest-lookup"
    if skopeo inspect --raw --authfile "$scratch/mirror-pull-auth.json" \
      "docker://${destination}:${tag}" >"$scratch/manifest.json" 2>"$scratch/mirror-error"; then
      : # Resume only after checking the exact bytes below.
    else
      lookup_status=$?
      if ! grep -Eiq 'manifest unknown|name unknown' "$scratch/mirror-error" &&
          ! grep -Fq "artifact mirror/${source_repository}:${tag} not found" "$scratch/mirror-error" &&
          ! grep -Fq "repository mirror/${source_repository} not found" "$scratch/mirror-error"; then
        exit "$lookup_status"
      fi
      mirror_phase="upstream-download"
      upstream_directory="$(mktemp -d "$scratch/upstream.XXXXXX")"
      if skopeo copy --all --preserve-digests --src-no-creds \
          --src-authfile "$scratch/anonymous-auth.json" \
          "docker://${source_repository}@${source_digest}" "dir:${upstream_directory}" 2>"$scratch/mirror-error"; then
        mirror_phase="upstream-verify"
        skopeo inspect --raw "dir:${upstream_directory}" >"$scratch/upstream-manifest.json" 2>"$scratch/mirror-error"
        mirror_category="digest-mismatch"
        [[ "sha256:$(sha256sum "$scratch/upstream-manifest.json" | cut -d ' ' -f 1)" == "$source_digest" ]]
        mirror_category="command-failed"
        mirror_phase="destination-copy"
        if skopeo copy --all --preserve-digests --src-no-creds \
            --src-authfile "$scratch/anonymous-auth.json" --dest-authfile "$scratch/mirror-publisher-auth.json" \
            "dir:${upstream_directory}" "docker://${destination}:${tag}" 2>"$scratch/mirror-error"; then
          :
        else
          copy_status=$?
          if grep -Fq 'Manifest list must be converted to type' "$scratch/mirror-error" &&
              grep -Fq 'Instructed to preserve digests' "$scratch/mirror-error"; then
            :
          elif jq -e '.mediaType == "application/vnd.oci.image.index.v1+json"' \
              "$scratch/upstream-manifest.json" >/dev/null &&
              grep -Fq "artifact mirror/${source_repository}@${source_digest} not found" \
                "$scratch/mirror-error"; then
            : # Harbor may fail to resolve a child while registering an OCI index.
          else
            exit "$copy_status"
          fi
          REGCTL_CONFIG="$scratch/regctl-publisher.json" DOCKER_CONFIG="$scratch/regctl-empty-docker" \
            regctl image copy "${source_repository}@${source_digest}" "${destination}:${tag}" \
            2>"$scratch/mirror-error"
          oci_index_copy=true
        fi
      else
        grep -Fq 'Manifest list must be converted to type' "$scratch/mirror-error" || exit 1
        grep -Fq 'Instructed to preserve digests' "$scratch/mirror-error" || exit 1
        mirror_phase="destination-copy"
        REGCTL_CONFIG="$scratch/regctl-publisher.json" DOCKER_CONFIG="$scratch/regctl-empty-docker" \
          regctl image copy "${source_repository}@${source_digest}" "${destination}:${tag}" \
          2>"$scratch/mirror-error"
        oci_index_copy=true
      fi
      rm -rf -- "$upstream_directory"
      mirror_phase="digest-verify"
      skopeo inspect --raw --authfile "$scratch/mirror-pull-auth.json" \
        "docker://${destination}:${tag}" >"$scratch/manifest.json" 2>"$scratch/mirror-error"
    fi
    mirror_phase="digest-verify"
    mirror_category="digest-mismatch"
    [[ "sha256:$(sha256sum "$scratch/manifest.json" | cut -d ' ' -f 1)" == "$source_digest" ]]
    mirror_category="command-failed"
    if jq -e '.mediaType == "application/vnd.oci.image.index.v1+json"' "$scratch/manifest.json" >/dev/null; then
      oci_index_copy=true
    fi
    tagged_source="${source%@*}"
    if [[ "$tagged_source" == *:* ]]; then
      # Operators and chart defaults may request tags rather than digests.
      source_tag="${tagged_source##*:}"
      mirror_phase="alias-lookup"
      alias_needs_copy=true
      for attempt in 1 2 3; do
        if skopeo inspect --raw --authfile "$scratch/mirror-pull-auth.json" \
          "docker://${destination}:${source_tag}" >"$scratch/tag-manifest.json" 2>"$scratch/mirror-error"; then
          if [[ "sha256:$(sha256sum "$scratch/tag-manifest.json" | cut -d ' ' -f 1)" == "$source_digest" ]]; then
            alias_needs_copy=false
          fi
          break
        else
          lookup_status=$?
        fi
        if grep -Eiq 'manifest unknown|name unknown' "$scratch/mirror-error" ||
            grep -Fq "artifact mirror/${source_repository}:${source_tag} not found" "$scratch/mirror-error" ||
            grep -Fq "repository mirror/${source_repository} not found" "$scratch/mirror-error"; then
          break
        fi
        if [[ "$attempt" == 3 ]] || ! mirror_retryable_read_error; then
          exit "$lookup_status"
        fi
        sleep "$attempt"
      done
      if [[ "$alias_needs_copy" == true ]]; then
        mirror_phase="alias-copy"
        if "$oci_index_copy"; then
          REGCTL_CONFIG="$scratch/regctl-publisher.json" DOCKER_CONFIG="$scratch/regctl-empty-docker" \
            regctl image copy "${destination}@${source_digest}" "${destination}:${source_tag}" \
            2>"$scratch/mirror-error"
        else
          if skopeo copy --all --preserve-digests \
              --src-authfile "$scratch/mirror-pull-auth.json" --dest-authfile "$scratch/mirror-publisher-auth.json" \
              "docker://${destination}@${source_digest}" "docker://${destination}:${source_tag}" 2>"$scratch/mirror-error"; then
            :
          else
            copy_status=$?
            if ! grep -Fq 'Manifest list must be converted to type' "$scratch/mirror-error" ||
                ! grep -Fq 'Instructed to preserve digests' "$scratch/mirror-error"; then
              exit "$copy_status"
            fi
            REGCTL_CONFIG="$scratch/regctl-publisher.json" DOCKER_CONFIG="$scratch/regctl-empty-docker" \
              regctl image copy "${destination}@${source_digest}" "${destination}:${source_tag}" \
              2>"$scratch/mirror-error"
            oci_index_copy=true
          fi
        fi
      fi
      mirror_phase="alias-verify"
      for attempt in 1 2 3; do
        if skopeo inspect --raw --authfile "$scratch/mirror-pull-auth.json" \
          "docker://${destination}:${source_tag}" >"$scratch/tag-manifest.json" 2>"$scratch/mirror-error"; then
          break
        else
          read_status=$?
        fi
        if [[ "$attempt" == 3 ]] || ! mirror_retryable_read_error; then
          exit "$read_status"
        fi
        sleep "$attempt"
      done
      mirror_category="digest-mismatch"
      [[ "sha256:$(sha256sum "$scratch/tag-manifest.json" | cut -d ' ' -f 1)" == "$source_digest" ]]
      mirror_category="command-failed"
    fi
    mirror_phase="authenticated-pull"
    pull_attempts=(1 2 3)
    if "$oci_index_copy"; then
      # OCI indexes use regctl here; give transient Harbor transport more time
      # without relaxing digest verification or retrying hard failures. Reuse
      # completed blobs across attempts; regctl verifies missing descendants.
      pull_attempts=(1 2 3 4 5)
    fi
    pull_directory=""
    for attempt in "${pull_attempts[@]}"; do
      if [[ -z "$pull_directory" ]]; then
        pull_directory="$(mktemp -d "$scratch/pull.XXXXXX")"
      fi
      if "$oci_index_copy"; then
        if REGCTL_CONFIG="$scratch/regctl-pull.json" DOCKER_CONFIG="$scratch/regctl-empty-docker" \
          regctl image copy --force-recursive \
            "${destination}@${source_digest}" "ocidir://${pull_directory}:verify" \
          2>"$scratch/mirror-error"; then
          break
        else
          read_status=$?
        fi
      elif skopeo copy --all --preserve-digests \
        --src-authfile "$scratch/mirror-pull-auth.json" \
        "docker://${destination}@${source_digest}" "dir:${pull_directory}" 2>"$scratch/mirror-error"; then
        break
      else
        read_status=$?
      fi
      if ! "$oci_index_copy"; then
        rm -rf -- "$pull_directory"
        pull_directory=""
      fi
      if [[ "$attempt" == "${#pull_attempts[@]}" ]]; then
        if "$oci_index_copy" && mirror_retryable_read_error && ! mirror_retryable_server_error; then
          mirror_category="transport-retries-exhausted"
        fi
        exit "$read_status"
      fi
      if ! mirror_retryable_read_error; then
        exit "$read_status"
      fi
      if "$oci_index_copy"; then
        sleep "$((1 << attempt))"
      else
        sleep "$attempt"
      fi
      # A dropped Kubernetes stream can leave the long-lived forward unusable.
      # Recheck TLS and the registry challenge before every authenticated retry.
      mirror_category="transport-failed"
      stop_private_forward
      start_private_forward
      mirror_category="command-failed"
    done
    if "$oci_index_copy"; then
      mirror_phase="pull-verify"
      pulled_digest="$(REGCTL_CONFIG="$scratch/regctl-pull.json" DOCKER_CONFIG="$scratch/regctl-empty-docker" \
        regctl image digest "ocidir://${pull_directory}:verify" 2>"$scratch/mirror-error")"
      mirror_category="digest-mismatch"
      [[ "$pulled_digest" == "$source_digest" ]]
    else
      mirror_phase="pull-verify"
      skopeo inspect --raw "dir:${pull_directory}" >"$scratch/pulled-manifest.json" 2>"$scratch/mirror-error"
      mirror_category="digest-mismatch"
      [[ "sha256:$(sha256sum "$scratch/pulled-manifest.json" | cut -d ' ' -f 1)" == "$source_digest" ]]
    fi
    mirror_category="command-failed"
    rm -rf -- "$pull_directory"
    printf '%s:%s@%s\n' "$destination" "$tag" "$source_digest" >>"$scratch/verified-digests"
  done < <(jq --raw-output '.images[].source' "$manifest")
  mirror_phase="acceptance"
  cat "$scratch/verified-digests" >>"${GITHUB_STEP_SUMMARY:?GITHUB_STEP_SUMMARY is required}"
  exit 0
fi

for name in "${publish_names[@]}"; do
  tag="homelab-${GITHUB_SHA}"
  destination="harbor.stinkyboi.com/homelab/${name}"
  publish_phase="push-${name#homelab-oce-}"
  docker tag "${name}:build" "${destination}:${tag}"
  docker --config "$scratch/docker" push "${destination}:${tag}"
  publish_phase="upload-verify-${name#homelab-oce-}"
  source_digest="$(docker image inspect --format '{{json .RepoDigests}}' "${destination}:${tag}" |
    jq --raw-output --arg prefix "${destination}@" '.[] | select(startswith($prefix)) | split("@")[1]')"
  [[ "$source_digest" =~ ^sha256:[0-9a-f]{64}$ ]]
  skopeo inspect --raw --authfile "$scratch/auth.json" "docker://${destination}:${tag}" \
    >"$scratch/manifest.json"
  destination_digest="sha256:$(sha256sum "$scratch/manifest.json" | cut -d ' ' -f 1)"
  [[ "$destination_digest" == "$source_digest" ]]
  publish_phase="authenticated-pull-${name#homelab-oce-}"
  pull_directory="$(mktemp -d "$scratch/published-pull.XXXXXX")"
  skopeo copy --all --preserve-digests --src-authfile "$scratch/auth.json" \
    "docker://${destination}@${destination_digest}" "dir:${pull_directory}"
  skopeo inspect --raw "dir:${pull_directory}" >"$scratch/pulled-manifest.json"
  [[ "sha256:$(sha256sum "$scratch/pulled-manifest.json" | cut -d ' ' -f 1)" == "$destination_digest" ]]
  rm -rf -- "$pull_directory"
  printf '%s:%s@%s\n' "$destination" "$tag" "$destination_digest" >>"$scratch/verified-digests"
done

if [[ "$mode" == publish ]]; then
  publish_phase="signing-prepare"
  # Only verified, allowlisted digests enter the repository-owned Job template.
  signing_references=()
  while IFS=@ read -r tagged_repository digest; do
    signing_references+=("${tagged_repository%:*}@${digest}")
  done <"$scratch/verified-digests"
  [[ "${#signing_references[@]}" -eq "${#publish_names[@]}" ]]
  signing_subjects="$(printf '%s\n' "${signing_references[@]}" | jq -R . | jq -s .)"
  yq -o=json '.' clusters/homelab/apps/harbor/signing-job.yaml |
    jq --argjson subjects "$signing_subjects" \
      'del(.metadata.name) | .metadata.generateName = "harbor-sign-" |
       .spec.template.spec.initContainers[1].args += $subjects' >"$scratch/signing-job.json"
  if "$core_publication"; then
    signer_image=harbor.stinkyboi.com/mirror/cgr.dev/chainguard/cosign:latest@sha256:3fad8be83b93869051c08bb98f36612afe81dabe06c288e70e41ce09a037ba18
    jq --arg image "$signer_image" \
      '.spec.template.spec.initContainers |= map(.image = $image) |
       .spec.template.spec.containers |= map(.image = $image)' \
      "$scratch/signing-job.json" >"$scratch/private-signing-job.json"
    mv "$scratch/private-signing-job.json" "$scratch/signing-job.json"
  fi
  publish_phase="signing-create"
  kubectl --namespace harbor create -f "$scratch/signing-job.json" -o json >"$scratch/created-job.json"
  signing_job="$(jq -er '.metadata.name' "$scratch/created-job.json")"
  signing_uid="$(jq -er '.metadata.uid' "$scratch/created-job.json")"
  [[ "$signing_job" =~ ^harbor-sign-[a-z0-9]+$ && "$signing_uid" =~ ^[a-f0-9-]{36}$ ]]
  publish_phase="signing-wait"
  kubectl --namespace harbor wait --for=condition=complete --timeout=360s "job/${signing_job}"
  # Pod status contains only the public key emitted by the successful signer.
  # CI never GETs the signing Secret or receives the private key.
  publish_phase="signing-key"
  kubectl --namespace harbor get pods -l "batch.kubernetes.io/controller-uid=${signing_uid}" -o json |
    jq -er --arg uid "$signing_uid" '
      .items | select(length == 1) | .[0] |
      select(any(.metadata.ownerReferences[]; .uid == $uid and .kind == "Job")) |
      .status.containerStatuses[] | select(.name == "public-key" and .state.terminated.exitCode == 0) |
      .state.terminated.message | rtrimstr("\n")' >"$scratch/signing.pub"
  [[ "$(sha256sum "$scratch/signing.pub" | cut -d ' ' -f 1)" == "$signing_fingerprint" ]] || {
    echo 'Harbor signing identity differs from the reviewed fingerprint.' >&2
    exit 1
  }
  publish_phase="signature-verify"
  for reference in "${signing_references[@]}"; do
    DOCKER_CONFIG="$scratch/docker" cosign verify \
      --key "$scratch/signing.pub" --insecure-ignore-tlog \
      --new-bundle-format=false "$reference" >"$scratch/signature-verification.json"
  done
fi

# Publish only allowlisted references after transfer and required acceptance pass.
if [[ "$mode" == publish ]]; then
  publish_phase="receipt"
  mapfile -t published_refs <"$scratch/verified-digests"
  if "$core_publication"; then
    [[ "${#published_refs[@]}" -eq 1 ]]
    [[ "${published_refs[0]}" =~ ^harbor\.stinkyboi\.com/homelab/homelab-harbor-core:homelab-${GITHUB_SHA}@sha256:[0-9a-f]{64}$ ]]
    printf 'core=%s\n' "${published_refs[0]}" >>"$GITHUB_OUTPUT"
  else
    [[ "${#published_refs[@]}" -eq "${#publish_names[@]}" ]]
    [[ "${#publish_names[@]}" -eq "${#publish_outputs[@]}" ]]
    for index in "${!publish_names[@]}"; do
      [[ "${published_refs[$index]}" =~ ^harbor\.stinkyboi\.com/homelab/${publish_names[$index]}:homelab-${GITHUB_SHA}@sha256:[0-9a-f]{64}$ ]]
    done
    for index in "${!publish_names[@]}"; do
      printf '%s=%s\n' "${publish_outputs[$index]}" "${published_refs[$index]}" >>"$GITHUB_OUTPUT"
    done
  fi
fi
cat "$scratch/verified-digests" >>"${GITHUB_STEP_SUMMARY:?GITHUB_STEP_SUMMARY is required}"
