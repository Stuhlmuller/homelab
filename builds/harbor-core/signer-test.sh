#!/usr/bin/env bash
set -euo pipefail
test "$#" -eq 0 || { echo 'Usage: signer-test.sh (no arguments)' >&2; exit 2; }
signer=cgr.dev/chainguard/cosign:latest@sha256:3fad8be83b93869051c08bb98f36612afe81dabe06c288e70e41ce09a037ba18
scratch="$(mktemp -d "${TMPDIR:-/tmp}/harbor-core-signer.XXXXXX")"
trap 'rm -rf -- "$scratch"' EXIT
umask 077
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$scratch/source.key" 2>/dev/null
docker pull "$signer" >/dev/null
docker run --rm --network none --user "$(id -u):$(id -g)" \
  --cap-drop ALL --security-opt no-new-privileges --read-only \
  --mount "type=bind,source=$scratch,target=/work" --workdir /work \
  --env COSIGN_PASSWORD=fixture-signing-password "$signer" \
  import-key-pair --key /work/source.key --output-key-prefix /work/cosign >/dev/null
docker run --rm --network none --user "$(id -u):$(id -g)" \
  --cap-drop ALL --security-opt no-new-privileges --read-only \
  --mount "type=bind,source=$scratch,target=/work" --workdir /work \
  --env COSIGN_PASSWORD=fixture-signing-password "$signer" \
  public-key --key /work/cosign.key --outfile /work/public.key >/dev/null
openssl pkey -in "$scratch/source.key" -pubout >"$scratch/expected.key"
cmp "$scratch/expected.key" "$scratch/public.key"
# Deprecated flags are hidden from help; exercise the parser without a registry subject.
if docker run --rm --network none "$signer" sign --yes \
  --tlog-upload=false --use-signing-config=false --new-bundle-format=false \
  --oidc-disable-ambient-providers >"$scratch/sign-parser" 2>&1; then
  echo 'Signer unexpectedly accepted an empty subject list.' >&2
  exit 1
fi
grep -F 'requires at least 1 arg(s), only received 0' "$scratch/sign-parser" >/dev/null || {
  cat "$scratch/sign-parser" >&2
  exit 1
}
echo 'Pinned public Chainguard signer key/API compatibility passed.'
