#!/usr/bin/env bash
set -euo pipefail

# Fixed production destinations; only ephemeral GitHub runner state is changed.
[[ $# -eq 1 && ("$1" == publish || "$1" == publish-harbor-core || "$1" == mirror || "$1" == mirror-fleet || "$1" == mirror-bazarr || "$1" == mirror-traefik || "$1" == mirror-chainguard || "$1" == mirror-mastodon) ]] || {
  echo 'Usage: harbor-publish.sh publish|publish-harbor-core|mirror|mirror-fleet|mirror-bazarr|mirror-traefik|mirror-chainguard|mirror-mastodon' >&2
  exit 2
}
mode="$1"
core_publication=false
publish_names=(homelab-nofx-backend homelab-nofx-frontend)
if [[ "$mode" == publish-harbor-core ]]; then
  core_publication=true
  mode=publish
  publish_names=(homelab-harbor-core)
  [[ "${GITHUB_EVENT_NAME:-}" == workflow_dispatch ]]
  [[ "${GITHUB_WORKFLOW_REF:-}" == Stuhlmuller/homelab/.github/workflows/harbor-core-images.yml@refs/heads/main ]]
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
elif [[ "$mode" == mirror-chainguard ]]; then
  mode=mirror
  mirror_manifest=scripts/config/harbor-chainguard-images.json
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
      (.source | type == "string" and test("^(docker[.]io|ghcr[.]io|quay[.]io|registry[.]k8s[.]io|gcr[.]io|mcr[.]microsoft[.]com|public[.]ecr[.]aws|ecr-public[.]aws[.]com|lscr[.]io|xpkg[.]crossplane[.]io|docker[.]langfuse[.]com|cgr[.]dev)/[a-z0-9]+([._-][a-z0-9]+)*(/[a-z0-9]+([._-][a-z0-9]+)*)*(:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?@sha256:[0-9a-f]{64}$")))
  ' "$manifest" >/dev/null
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
cleanup() {
  local result=$?
  trap - EXIT INT TERM
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
[[ "$mode" != mirror ]] || forward_timeout=19800
timeout --signal=TERM --kill-after=5s "$forward_timeout" \
  "$scratch/kubectl" --kubeconfig "$HOME/.kube/config" \
  --namespace traefik port-forward --address 127.0.0.1 \
  service/traefik-private 443:443 >"$scratch/port-forward.log" 2>&1 &
forward_pid=$!
hosts_added=true
printf '%s\n' '127.0.0.1 harbor.stinkyboi.com # homelab-harbor-ci' |
  sudo -n tee -a /etc/hosts >/dev/null

ready=false
for _ in {1..30}; do
  kill -0 "$forward_pid"
  if status="$(curl --silent --show-error --noproxy '*' --max-time 5 \
    --output /dev/null --write-out '%{http_code}' https://harbor.stinkyboi.com/v2/ \
    2>"$scratch/readiness.log")" && [[ "$status" == 401 ]]; then
    ready=true
    break
  fi
  sleep 2
done
"$ready" || {
  echo 'Harbor TLS and private registry challenge are not ready.' >&2
  exit 1
}

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
  rm -f -- "$scratch/mirror-pull-password"
else
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
  while IFS= read -r source; do
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
      skopeo copy --all --preserve-digests --src-no-creds \
        --src-authfile "$scratch/anonymous-auth.json" \
        "docker://${source_repository}@${source_digest}" "dir:${upstream_directory}" 2>"$scratch/mirror-error"
      mirror_phase="upstream-verify"
      skopeo inspect --raw "dir:${upstream_directory}" >"$scratch/upstream-manifest.json" 2>"$scratch/mirror-error"
      mirror_category="digest-mismatch"
      [[ "sha256:$(sha256sum "$scratch/upstream-manifest.json" | cut -d ' ' -f 1)" == "$source_digest" ]]
      mirror_category="command-failed"
      mirror_phase="destination-copy"
      skopeo copy --all --preserve-digests --src-no-creds \
        --src-authfile "$scratch/anonymous-auth.json" --dest-authfile "$scratch/mirror-publisher-auth.json" \
        "dir:${upstream_directory}" "docker://${destination}:${tag}" 2>"$scratch/mirror-error"
      rm -rf -- "$upstream_directory"
      mirror_phase="digest-verify"
      skopeo inspect --raw --authfile "$scratch/mirror-pull-auth.json" \
        "docker://${destination}:${tag}" >"$scratch/manifest.json" 2>"$scratch/mirror-error"
    fi
    mirror_phase="digest-verify"
    mirror_category="digest-mismatch"
    [[ "sha256:$(sha256sum "$scratch/manifest.json" | cut -d ' ' -f 1)" == "$source_digest" ]]
    mirror_category="command-failed"
    tagged_source="${source%@*}"
    if [[ "$tagged_source" == *:* ]]; then
      # Operators and chart defaults may request tags rather than digests.
      source_tag="${tagged_source##*:}"
      mirror_phase="alias-copy"
      skopeo copy --all --preserve-digests \
        --src-authfile "$scratch/mirror-pull-auth.json" --dest-authfile "$scratch/mirror-publisher-auth.json" \
        "docker://${destination}@${source_digest}" "docker://${destination}:${source_tag}" 2>"$scratch/mirror-error"
      mirror_phase="alias-verify"
      skopeo inspect --raw --authfile "$scratch/mirror-pull-auth.json" \
        "docker://${destination}:${source_tag}" >"$scratch/tag-manifest.json" 2>"$scratch/mirror-error"
      mirror_category="digest-mismatch"
      [[ "sha256:$(sha256sum "$scratch/tag-manifest.json" | cut -d ' ' -f 1)" == "$source_digest" ]]
      mirror_category="command-failed"
    fi
    mirror_phase="authenticated-pull"
    pull_directory="$(mktemp -d "$scratch/pull.XXXXXX")"
    skopeo copy --all --preserve-digests \
      --src-authfile "$scratch/mirror-pull-auth.json" \
      "docker://${destination}@${source_digest}" "dir:${pull_directory}" 2>"$scratch/mirror-error"
    mirror_phase="pull-verify"
    skopeo inspect --raw "dir:${pull_directory}" >"$scratch/pulled-manifest.json" 2>"$scratch/mirror-error"
    mirror_category="digest-mismatch"
    [[ "sha256:$(sha256sum "$scratch/pulled-manifest.json" | cut -d ' ' -f 1)" == "$source_digest" ]]
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
  docker tag "${name}:build" "${destination}:${tag}"
  docker --config "$scratch/docker" push "${destination}:${tag}"
  source_digest="$(docker image inspect --format '{{json .RepoDigests}}' "${destination}:${tag}" |
    jq --raw-output --arg prefix "${destination}@" '.[] | select(startswith($prefix)) | split("@")[1]')"
  [[ "$source_digest" =~ ^sha256:[0-9a-f]{64}$ ]]
  skopeo inspect --raw --authfile "$scratch/auth.json" "docker://${destination}:${tag}" \
    >"$scratch/manifest.json"
  destination_digest="sha256:$(sha256sum "$scratch/manifest.json" | cut -d ' ' -f 1)"
  [[ "$destination_digest" == "$source_digest" ]]
  pull_directory="$(mktemp -d "$scratch/published-pull.XXXXXX")"
  skopeo copy --all --preserve-digests --src-authfile "$scratch/auth.json" \
    "docker://${destination}@${destination_digest}" "dir:${pull_directory}"
  skopeo inspect --raw "dir:${pull_directory}" >"$scratch/pulled-manifest.json"
  [[ "sha256:$(sha256sum "$scratch/pulled-manifest.json" | cut -d ' ' -f 1)" == "$destination_digest" ]]
  rm -rf -- "$pull_directory"
  printf '%s:%s@%s\n' "$destination" "$tag" "$destination_digest" >>"$scratch/verified-digests"
done

if [[ "$mode" == publish ]]; then
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
  kubectl --namespace harbor create -f "$scratch/signing-job.json" -o json >"$scratch/created-job.json"
  signing_job="$(jq -er '.metadata.name' "$scratch/created-job.json")"
  signing_uid="$(jq -er '.metadata.uid' "$scratch/created-job.json")"
  [[ "$signing_job" =~ ^harbor-sign-[a-z0-9]+$ && "$signing_uid" =~ ^[a-f0-9-]{36}$ ]]
  kubectl --namespace harbor wait --for=condition=complete --timeout=360s "job/${signing_job}"
  # Pod status contains only the public key emitted by the successful signer.
  # CI never GETs the signing Secret or receives the private key.
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
  for reference in "${signing_references[@]}"; do
    DOCKER_CONFIG="$scratch/docker" cosign verify \
      --key "$scratch/signing.pub" --insecure-ignore-tlog \
      --new-bundle-format=false "$reference" >"$scratch/signature-verification.json"
  done
fi

# Publish only allowlisted references after transfer and required acceptance pass.
if [[ "$mode" == publish ]]; then
  mapfile -t published_refs <"$scratch/verified-digests"
  if "$core_publication"; then
    [[ "${#published_refs[@]}" -eq 1 ]]
    [[ "${published_refs[0]}" =~ ^harbor\.stinkyboi\.com/homelab/homelab-harbor-core:homelab-${GITHUB_SHA}@sha256:[0-9a-f]{64}$ ]]
    printf 'core=%s\n' "${published_refs[0]}" >>"$GITHUB_OUTPUT"
  else
  [[ "${#published_refs[@]}" -eq 2 ]]
  [[ "${published_refs[0]}" =~ ^harbor\.stinkyboi\.com/homelab/homelab-nofx-backend:homelab-${GITHUB_SHA}@sha256:[0-9a-f]{64}$ ]]
  [[ "${published_refs[1]}" =~ ^harbor\.stinkyboi\.com/homelab/homelab-nofx-frontend:homelab-${GITHUB_SHA}@sha256:[0-9a-f]{64}$ ]]
  printf 'backend=%s\nfrontend=%s\n' "${published_refs[0]}" "${published_refs[1]}" >>"$GITHUB_OUTPUT"
  fi
fi
cat "$scratch/verified-digests" >>"${GITHUB_STEP_SUMMARY:?GITHUB_STEP_SUMMARY is required}"
