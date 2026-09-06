# Anonymous restore image verification

Related: [[restore-image-publication]], [[restore-talos-runtime-validation]],
[[validation-gates]].

## Contract and current status

`scripts/ci/restore-image-anonymous-pull.py` consumes only the committed
`images/postgres-restore-egress/published-image.json`. That file is deliberately
absent: no registry is selected and no published image is asserted here.
Missing, malformed, uncommitted, staged or modified pin bytes fail before any
network call. No token, image argument or environment override can supply a pin.

The future reviewed pin must contain exactly these fields. This documentation
example contains placeholders and must not be copied into the consumed path:

```json
{
  "version": 1,
  "image": "REGISTRY/REPOSITORY@sha256:MANIFEST_HEX",
  "config_digest": "sha256:CONFIG_HEX",
  "source_commit": "FULL_REVIEWED_SOURCE_SHA",
  "source_url": "https://github.com/Stuhlmuller/homelab",
  "os": "linux",
  "architecture": "amd64",
  "publication": {"run_id": 0, "run_attempt": 0}
}
```

Actual digests require 64 lowercase hexadecimal characters; the source commit
requires 40. Run identifiers and attempts must be positive integers. Only a fully
qualified digest reference is accepted; tags, credentials and transport prefixes
are rejected. Reviewers must compare image/config/source against the existing
protected publisher's exact output, and record its actual run and attempt.
The image source normally predates the later pin commit. The Talos consumer must
separately bind that source to reviewed main history and its current checkout.

**The committed pin is a human attestation of publisher output.** Public run
metadata proves the cited execution succeeded on the expected main/source and
workflow. Matching image bytes prove retrieval of the reviewed digest. Neither
proves independently that this run emitted the image, that an approval occurred,
or that labels are cryptographic provenance. The existing publisher writes a
receipt to stdout, not a machine-verifiable receipt artifact. This helper does
not change that publisher or its protection, destination or credential scope.

## Verification and consumer interface

Check the local committed contract without network or credentials:

```sh
nix develop --command python3 scripts/ci/restore-image-anonymous-pull.py --check-contract
```

After a genuine publication and reviewed pin commit, run the complete gate:

```sh
nix develop --command nix shell --inputs-from . nixpkgs#skopeo --command \
  python3 scripts/ci/restore-image-anonymous-pull.py
```

The first public request is fixed to the repository's GitHub workflow-run attempt
API. It requires matching run/attempt, source SHA, repository and head repository,
`workflow_dispatch`, `main`, the exact `restore-image-publish.yml` path, and
completed success. Curl ignores curlrc, netrc and proxies; redirects, non-200
responses, oversized bodies and unavailable metadata fail closed. Public
resources support unauthenticated access. [GitHub attempt API][attempt].

Skopeo then copies the complete image into a fresh temporary `dir:` layout with
`--preserve-digests`, explicit `--src-no-creds`, empty auth files, empty client
certificate directory and required TLS verification. The verifier hashes the
exact manifest against the pin, then verifies config and every referenced layer
hash and size. Config digest, source labels and Linux/amd64 identity must match.
Only single-image Docker schema2 and OCI manifests are accepted; indexes,
foreign-layer URLs and inline descriptors fail. No manifest-only HEAD probe,
cached Docker image, alternate tag or mirror can satisfy the gate. The temporary
copy is deleted on success or failure. [Skopeo copy contract][copy].

Successful full verification prints the pin plus
`publication_metadata_verified: true` and `anonymous_pull_verified: true`.
These are this invocation's results, not reusable authorization. The importable
functions are `read_contract(root=ROOT)`, `verify_publication(contract)` and
`pull(contract)`. A later Talos workflow must perform the full sequence before
acquiring live-operation credentials, independently validate its reviewed
checkout/source contract, and keep real backup material excluded. No Job is
created and no Talos compatibility is proven by this helper.

## Credential and primary-registry isolation

Only child tool contexts receive temporary HOME/XDG directories; the caller's
HOME, CODEX_HOME and environment remain untouched. The child environment is
constructed from an explicit minimal allowlist, excluding tokens, proxy values,
registry auth paths, curl settings and certificate overrides. Tool executables
come from the repository-locked shell; no credential helper is configured.

The current flake resolves Skopeo 1.22.2 and its image library v5.39.2.
`--src-no-creds` sets an explicit empty `DockerAuthConfig`; the library returns
that before consulting auth files or helpers. [Skopeo option][no-creds],
[library credential lookup][auth]. A temporary per-user `registries.conf` and
empty user drop-in directory take the early-return path that excludes system
registry files and drop-ins. It defines no mirror or prefix rewrite, so pulls
address the pin's primary registry. The hidden `--registries-conf` flag is not
used because that different path can still load system drop-ins.
[Exact registry-config selection][registries]. The local signature policy
rejects other repositories and permits digest verification for only the pinned
repository; it does not claim signature authentication.

## Validation and rollback

The static gate runs offline tests for both manifest formats, damaged/missing
blobs, bad descriptor sizes/URLs, source/platform/config mismatches, dirty Git
pins, publication metadata mismatches, HTTP redirects, credential isolation and
failed or timed-out copies. These fixtures do not prove a real anonymous pull.
The real gate remains **unexecuted until a published reviewed pin exists**;
Talos runtime proof remains separate. No publication or live operation occurs.

A failure blocks the consumer. Repair the reviewed pin or verifier through a PR;
never add credential fallback, skip a blob, or accept a changed digest. Reverting
this helper removes the verification code only, so any consumer must remain
blocked until an equivalent reviewed gate exists.

[attempt]: https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run-attempt
[copy]: https://github.com/containers/skopeo/blob/v1.22.2/docs/skopeo-copy.1.md
[no-creds]: https://github.com/containers/skopeo/blob/v1.22.2/cmd/skopeo/utils.go
[auth]: https://github.com/podman-container-tools/container-libs/blob/image/v5.39.2/image/pkg/docker/config/config.go#L195-L204
[registries]: https://github.com/podman-container-tools/container-libs/blob/image/v5.39.2/image/pkg/sysregistriesv2/system_registries_v2.go#L568-L586
