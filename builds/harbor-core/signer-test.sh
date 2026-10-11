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
docker run --rm --network none "$signer" sign --help >"$scratch/sign-help"
for flag in tlog-upload use-signing-config new-bundle-format oidc-disable-ambient-providers; do
  grep -F -- "--$flag" "$scratch/sign-help" >/dev/null
done
echo 'Pinned public Chainguard signer key/API compatibility passed.'
