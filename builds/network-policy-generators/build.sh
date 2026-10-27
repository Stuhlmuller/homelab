#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 0 ]] || { echo 'Usage: build.sh (no arguments)' >&2; exit 2; }

cd "$(dirname "$0")/../.."
repository_root="$PWD"
contract=builds/network-policy-generators/source.json
toolchain="$(jq -er '.goToolchain | select(. == "go1.25.8")' "$contract")"

context="$(mktemp -d "${TMPDIR:-/tmp}/policy-generator-build.XXXXXX")"
trap 'rm -rf -- "$context"' EXIT
python3 -I builds/network-policy-generators/verify-source.py --output-dir "$context/source"

build_image() {
  local name="$1" upstream="$2" package="$3" license="$4" license_id="$5"
  local revision tag patch_hash module_path module_dir binary_path image_context base_key base_image destination base_config built_config ldflags component image_ref
  revision="$(jq -er --arg name "$upstream" '.[$name].revision | select(test("^[0-9a-f]{40}$"))' "$contract")"
  tag="$(jq -er --arg name "$upstream" '.[$name].tag | select(test("^v[0-9]+\\.[0-9]+\\.[0-9]+$"))' "$contract")"
  patch_hash="$(jq -er --arg name "$upstream" '.[$name].patchSha256 | select(test("^[0-9a-f]{64}$"))' "$contract")"
  module_path=github.com/octelium/octelium/pkg/utils/ldflags
  ldflags="-s -w -X ${module_path}.GitCommit=${revision} -X ${module_path}.GitTag=${tag} -X ${module_path}.SemVer=${tag} -X ${module_path}.ImageRegistry=ghcr.io -X ${module_path}.ImageRegistryPrefix=octelium"
  module_dir="${package#github.com/octelium/"$upstream"/}"
  case "$name" in
    cordium-genesis) base_key=cordiumGenesis; destination=/app/cordium-genesis ;;
    octelium-genesis) base_key=octeliumGenesis; destination=/app/octelium-genesis ;;
    octops) base_key=octops; destination=/usr/bin/octops ;;
    *) exit 2 ;;
  esac
  base_image="$(jq -er --arg key "$base_key" '.runtimeBaseImages[$key] | select(test("^ghcr[.]io/octelium/[a-z-]+:[0-9]+[.][0-9]+[.][0-9]+@sha256:[0-9a-f]{64}$"))' "$contract")"
  if [[ "$name" != octops ]]; then
    jq -e --arg image "$base_image" 'any(.images[]; .source == $image)' scripts/config/harbor-images.json >/dev/null
  fi
  image_context="$context/$name"
  mkdir -p "$image_context/licenses"
  binary_path="$image_context/$name"
  (
    cd "$context/source/$upstream/$module_dir"
    GOTOOLCHAIN="$toolchain" CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOAMD64=v1 \
      go build -trimpath -buildvcs=false \
        -ldflags "$ldflags" \
        -o "$binary_path" .
  )
  if [[ "$name" != octops ]]; then
    component="$name"
    component="${component%-genesis}-apiserver"
    image_ref="$(cd "$context/source/$upstream/$module_dir" && \
      GOTOOLCHAIN="$toolchain" CGO_ENABLED=0 go run -trimpath -ldflags "$ldflags" \
        "$repository_root/builds/network-policy-generators/image-ref-probe.go" "$component")"
    [[ "$image_ref" == "ghcr.io/octelium/${component}:${tag#v}" ]]
  fi
  cp "$context/source/$upstream/$license" "$image_context/licenses/LICENSE"
  if [[ "$upstream" == cordium ]]; then
    cp "$context/source/cordium/LICENSE" "$image_context/licenses/UPSTREAM-LICENSE"
  fi
  docker pull --platform linux/amd64 "$base_image" >/dev/null
  docker buildx build --load --platform linux/amd64 \
    --file "$repository_root/builds/network-policy-generators/runtime.Dockerfile" \
    --build-arg "BINARY=$name" \
    --build-arg "BASE_IMAGE=$base_image" \
    --build-arg "DESTINATION=$destination" \
    --label "org.opencontainers.image.source=https://github.com/octelium/$upstream" \
    --label "org.opencontainers.image.revision=$revision" \
    --label "org.opencontainers.image.version=$tag" \
    --label "com.stinkyboi.patched-source-license=$license_id" \
    --label "com.stinkyboi.policy-patch-sha256=$patch_hash" \
    --tag "homelab-$name:build" "$image_context"
  [[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "homelab-$name:build")" == "$revision" ]]
  [[ "$(docker image inspect --format '{{index .Config.Labels "com.stinkyboi.policy-patch-sha256"}}' "homelab-$name:build")" == "$patch_hash" ]]
  base_config="$(docker image inspect --format '{{json .Config}}' "$base_image" | jq -c '{User, Entrypoint, Env, Cmd, WorkingDir}')"
  built_config="$(docker image inspect --format '{{json .Config}}' "homelab-$name:build" | jq -c '{User, Entrypoint, Env, Cmd, WorkingDir}')"
  [[ "$built_config" == "$base_config" ]]
  case "$name" in
    cordium-genesis)
      docker run --rm --network none --entrypoint /bin/sh "homelab-$name:build" -c 'command -v helm && command -v bash && command -v curl && command -v openssl && test -e /etc/ssl/certs/ca-certificates.crt' >/dev/null ;;
    octelium-genesis)
      docker run --rm --network none --entrypoint /bin/sh "homelab-$name:build" -c 'command -v bash && command -v curl && command -v openssl && test -e /etc/ssl/certs/ca-certificates.crt' >/dev/null ;;
    octops)
      docker run --rm --network none --entrypoint /bin/sh "homelab-$name:build" -c 'test "$OCTELIUM_CONTAINER_MODE" = true && test -e /etc/ssl/certs/ca-certificates.crt' >/dev/null ;;
  esac
}

build_image cordium-genesis cordium github.com/octelium/cordium/cluster/genesis cluster/genesis/LICENSE Apache-2.0
build_image octelium-genesis octelium github.com/octelium/octelium/cluster/genesis cluster/genesis/LICENSE AGPL-3.0
build_image octops octelium github.com/octelium/octelium/client/octops client/octops/LICENSE Apache-2.0
[[ "$(docker run --rm --network none homelab-octops:build init --help 2>&1)" == *"--genesis-image"* ]]
