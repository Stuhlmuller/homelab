#!/usr/bin/env bash
set -euo pipefail

# Fixed production destinations; only ephemeral GitHub runner state is changed.
[[ $# -eq 1 && ("$1" == publish || "$1" == migrate) ]] || {
  echo 'Usage: harbor-publish.sh publish|migrate' >&2
  exit 2
}
mode="$1"
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

# Validate every migration input before installing credentials or contacting AWS.
manifest=scripts/config/harbor-migration.json
jq --exit-status '
  (keys | sort) == ["releases"] and
  (.releases | type == "array" and length == 2) and
  ([.releases[].source_revision] | unique | length) == 2 and
  ([.releases[].source_workflow_run] | sort) == [
    "https://github.com/Stuhlmuller/homelab/actions/runs/34815485548",
    "https://github.com/Stuhlmuller/homelab/actions/runs/34926391605"
  ] and
  all(.releases[];
    (keys | sort) == ["images", "source_revision", "source_workflow_run"] and
    (.source_revision | type == "string" and test("^[0-9a-f]{40}$")) and
    (.images | type == "array" and length == 2) and
    ([.images[].name] | sort) == ["homelab-nofx-backend", "homelab-nofx-frontend"] and
    all(.images[];
      (keys | sort) == ["digest", "name"] and
      (.digest | type == "string" and test("^sha256:[0-9a-f]{64}$"))))
' "$manifest" >/dev/null

: "${RUNNER_TEMP:?RUNNER_TEMP must be set by GitHub Actions}"
if [[ "$mode" == publish ]]; then
  : "${GITHUB_OUTPUT:?GITHUB_OUTPUT must be set by GitHub Actions}"
fi
: "${OCTELIUM_AUTH_TOKEN:?The production Octelium CI credential is required}"
[[ "${KUBE_API_SERVER_URL:-}" == https://kubernetes-api-ci.stinkyboi.com ]]
[[ "$mode" != migrate || -n "${GITHUB_TOKEN:-}" ]]
[[ ! -e "$HOME/.kube/config" ]] || {
  echo 'Refusing to replace an existing runner kubeconfig.' >&2
  exit 1
}
if grep -Eq '(^|[[:space:]])harbor[.]stinkyboi[.]com([[:space:]]|$)|# homelab-harbor-ci$' /etc/hosts; then
  echo 'Refusing to replace existing Harbor host routing.' >&2
  exit 1
fi

umask 077
scratch="$(mktemp -d "${RUNNER_TEMP}/harbor-publish.XXXXXX")"
forward_pid=""
hosts_added=false
kubeconfig_added=false
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

# Reuse the declared clientless Octelium Kubernetes CI lane. Kubernetes streams
# carry image uploads, avoiding the public HTTP Tunnel's request-size limit.
kubeconfig_added=true
bash scripts/ci/install-kubeconfig.sh
kubectl --request-timeout=15s version >/dev/null
cp "$(command -v kubectl)" "$scratch/kubectl"
chmod 700 "$scratch/kubectl"
sudo -n setcap cap_net_bind_service=+ep "$scratch/kubectl"
timeout --signal=TERM --kill-after=5s 2400 \
  "$scratch/kubectl" --kubeconfig "$HOME/.kube/config" \
  --namespace istio-system port-forward --address 127.0.0.1 \
  service/istio-ingressgateway 443:443 >"$scratch/port-forward.log" 2>&1 &
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
aws ssm get-parameter --region us-west-2 \
  --name /homelab/harbor/robot-push-password --with-decryption \
  --query Parameter.Value --output text >"$scratch/harbor-password"
[[ -s "$scratch/harbor-password" ]]
skopeo login --authfile "$scratch/auth.json" --username "robot\$homelab+publisher" \
  --password-stdin harbor.stinkyboi.com <"$scratch/harbor-password" >/dev/null
if [[ "$mode" == migrate ]]; then
  printf '%s' "$GITHUB_TOKEN" |
    skopeo login --authfile "$scratch/auth.json" --username "$GITHUB_ACTOR" \
      --password-stdin ghcr.io >/dev/null
  unset GITHUB_TOKEN
else
  mkdir "$scratch/docker"
  docker --config "$scratch/docker" login --username "robot\$homelab+publisher" \
    --password-stdin harbor.stinkyboi.com <"$scratch/harbor-password" >/dev/null
fi
rm -f -- "$scratch/harbor-password"

while IFS=$'\t' read -r revision name source_digest; do
  tag="homelab-${revision}"
  destination="harbor.stinkyboi.com/homelab/${name}"
  if [[ "$mode" == migrate ]]; then
    skopeo copy --all --preserve-digests --authfile "$scratch/auth.json" \
      "docker://ghcr.io/stuhlmuller/${name}@${source_digest}" \
      "docker://${destination}:${tag}"
  else
    docker tag "${name}:build" "${destination}:${tag}"
    docker --config "$scratch/docker" push "${destination}:${tag}"
    source_digest="$(docker image inspect --format '{{json .RepoDigests}}' "${destination}:${tag}" |
      jq --raw-output --arg prefix "${destination}@" '.[] | select(startswith($prefix)) | split("@")[1]')"
    [[ "$source_digest" =~ ^sha256:[0-9a-f]{64}$ ]]
  fi
  skopeo inspect --raw --authfile "$scratch/auth.json" "docker://${destination}:${tag}" \
    >"$scratch/manifest.json"
  destination_digest="sha256:$(sha256sum "$scratch/manifest.json" | cut -d ' ' -f 1)"
  [[ "$destination_digest" == "$source_digest" ]]
  printf '%s:%s@%s\n' "$destination" "$tag" "$destination_digest" >>"$scratch/verified-digests"
done < <(jq --raw-output --arg mode "$mode" --arg revision "$GITHUB_SHA" '
  if $mode == "migrate" then
    .releases[] | .source_revision as $source_revision |
    .images[] | [$source_revision, .name, .digest] | @tsv
  else
    # Release history must not duplicate publication of the current build.
    ([.releases[].images[].name] | unique[]) as $name |
    [$revision, $name, ""] | @tsv
  end
' "$manifest")

if [[ "$mode" == publish ]]; then
  # Only verified, allowlisted digests enter the repository-owned Job template.
  signing_references=()
  while IFS=@ read -r tagged_repository digest; do
    signing_references+=("${tagged_repository%:*}@${digest}")
  done <"$scratch/verified-digests"
  [[ "${#signing_references[@]}" -eq 2 ]]
  yq -o=json '.' clusters/homelab/apps/harbor/signing-job.yaml |
    jq --arg backend "${signing_references[0]}" --arg frontend "${signing_references[1]}" \
      'del(.metadata.name) | .metadata.generateName = "harbor-sign-" |
       .spec.template.spec.initContainers[1].args += [$backend, $frontend]' >"$scratch/signing-job.json"
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

if [[ "$mode" == migrate ]]; then
  # Independently exercise the namespace-scoped pull credential and every blob.
  # Publisher credentials and the local image cache cannot satisfy this check.
  aws ssm get-parameter --region us-west-2 \
    --name /homelab/nofx/harbor-pull-password --with-decryption \
    --query Parameter.Value --output text >"$scratch/pull-password"
  [[ -s "$scratch/pull-password" ]]
  skopeo login --authfile "$scratch/pull-auth.json" --username "robot\$homelab+pull" \
    --password-stdin harbor.stinkyboi.com <"$scratch/pull-password" >/dev/null
  rm -f -- "$scratch/pull-password"
  printf '%s\n' '{"auths":{}}' >"$scratch/anonymous-auth.json"
  while IFS=@ read -r tagged_repository expected_digest; do
    repository="${tagged_repository%:*}"
    # A new empty directory for each artifact prevents one release's blobs
    # from masking an incomplete pull of another release of the same image.
    pull_directory="$(mktemp -d "$scratch/pull.XXXXXX")"
    skopeo copy --all --preserve-digests --src-authfile "$scratch/pull-auth.json" \
      "docker://${repository}@${expected_digest}" "dir:${pull_directory}"
    skopeo inspect --raw "dir:${pull_directory}" >"$scratch/pulled-manifest.json"
    pulled_digest="sha256:$(sha256sum "$scratch/pulled-manifest.json" | cut -d ' ' -f 1)"
    [[ "$pulled_digest" == "$expected_digest" ]]
    if skopeo inspect --raw --no-creds --authfile "$scratch/anonymous-auth.json" \
      "docker://${repository}@${expected_digest}" \
      >"$scratch/anonymous-manifest" 2>"$scratch/anonymous-error"; then
      echo 'Anonymous access to a private migrated artifact was allowed.' >&2
      exit 1
    fi
    # A network/TLS failure is not evidence that the registry denied access.
    grep -Eiq 'unauthorized|authentication required|requested access to the resource is denied' \
      "$scratch/anonymous-error"
    rm -rf -- "$pull_directory"
  done <"$scratch/verified-digests"
fi

# Publish only allowlisted references after transfer and required acceptance pass.
if [[ "$mode" == publish ]]; then
  mapfile -t published_refs <"$scratch/verified-digests"
  [[ "${#published_refs[@]}" -eq 2 ]]
  [[ "${published_refs[0]}" =~ ^harbor\.stinkyboi\.com/homelab/homelab-nofx-backend:homelab-${GITHUB_SHA}@sha256:[0-9a-f]{64}$ ]]
  [[ "${published_refs[1]}" =~ ^harbor\.stinkyboi\.com/homelab/homelab-nofx-frontend:homelab-${GITHUB_SHA}@sha256:[0-9a-f]{64}$ ]]
  printf 'backend=%s\nfrontend=%s\n' "${published_refs[0]}" "${published_refs[1]}" >>"$GITHUB_OUTPUT"
fi
cat "$scratch/verified-digests" >>"${GITHUB_STEP_SUMMARY:?GITHUB_STEP_SUMMARY is required}"
