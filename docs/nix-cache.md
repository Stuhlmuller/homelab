# Signed offline check cache

Offline Python and shell fixtures and manifest policies are Nix derivations in
[`flake.nix`](../flake.nix). A successful check creates a `result` file. A
failed check creates no output and cannot populate the cache. The complete
tracked source tree, fixture commands, pinned tools, and platform determine
the derivation; Git commit metadata does not. Testing before a signed commit
therefore remains reusable when the committed files match.

[`offline-checks.sh`](../scripts/ci/offline-checks.sh) owns the extracted
Python checks; [offline-static-checks.sh](../scripts/ci/offline-static-checks.sh)
owns shell fixtures and source contracts. Their generated Terragrunt units are fixtures; it performs no
provider initialization or authenticated cloud/cluster requests.
[`conftest-policies.sh`](../scripts/ci/conftest-policies.sh) owns the second
check. Provider initialization/validation, Helm chart downloads, Git-sensitive
secret scanning, security scanners, live plans, and cluster acceptance still
run fresh. These network-dependent validations are outside the sandboxed
offline suite. NOFX image publication and other credentialed builds retain their
existing workflow and provenance gates.

## Local validation and publication

From the repository root:

```sh
bash scripts/ci/nix-checks.sh
nix develop --command bash scripts/ci/static-checks.sh --offline-verified
nix develop --command python3 -I scripts/nix-cache.py publish --linux \
  --key-file ~/.config/homelab/nix-cache/signing.key
```

Initialize the empty cache endpoint before publishing its first outputs:

```sh
python3 -I scripts/nix-cache.py init-cache \
  --key-file ~/.config/homelab/nix-cache/signing.key
```

The publisher rebuilds or substitutes the expected checks, checks that the
private key matches the committed public key, signs the outputs, and uploads
them to the `nix-cache` GitHub prerelease. It uploads NARs before metadata,
never replaces existing assets, and rejects a differing existing asset.
GitHub authentication requires repository write access; CI readers need no
cache credentials. The private signing key remains outside the checkout and
is never supplied to PR jobs. Both checks produce self-contained outputs.

The cache is an ordinary Nix binary cache hosted as release assets. NAR URLs
are flattened because release assets cannot contain directory paths. Nix
signatures cover store path, NAR hash, size, and references; changing the
download URL does not change the signed fingerprint.

The [homelab Linux builder](../clusters/homelab/apps/nix-builder/README.md)
primes Ubuntu CI through authenticated Kubernetes exec. Stage the exact files
first; `publish --linux` rejects unstaged changes and verifies the returned
outputs against the local Linux derivation paths. The signing key stays local.
Native macOS outputs serve macOS validation when its Nix daemon accepts the
cache and sandbox policy. The client refuses to publish when Nix ignores
those settings. Alternatively, run on another trusted **x86_64 Linux** Nix machine. The platform must match;
macOS or ARM Linux results cannot satisfy x86_64 Linux checks. If copying a key to another builder, protect that machine as carefully as CI. A Linux cache miss builds the checks normally.

New untracked files must first be staged: Git-backed flakes only include
tracked files. Do not stage private key material. Changes to tracked docs or
unrelated configuration also invalidate these broad checks; narrow input
sets only after their complete dependency footprint is established.

## CI trust and freshness

Static jobs fetch `main` and read its
[`nix-cache.json`](../scripts/config/nix-cache.json). PR changes cannot add
trusted cache keys. Before this policy initially lands on `main`, jobs build
without the shared cache. Required checks still run and report success only
after Nix realizes both expected outputs and remaining validation passes.
`require-sigs` and the build sandbox remain enabled. Missing entries build;
signature or content corruption fails verification.

Static jobs no longer restore the entire Nix store from an Actions cache:
existing unsigned store objects could bypass binary-cache signature checks.
Live jobs retain their development-shell dependency cache; live plans and
cluster checks do not consume cached test receipts.

## Key lifecycle and rollback

Initialize a replacement key using the repository-owned command:

```sh
python3 -I scripts/nix-cache.py init-key \
  --key-file ~/.config/homelab/nix-cache/replacement.key
```

This prints only the public key and refuses to overwrite existing files.
Review the new public key and a new release tag/URL in `nix-cache.json`, then
merge through normal protection. Publish into the new cache with that key.
Keep the private key in secure, recoverable operator storage; losing it
requires rotation. A compromised key can forge successful results: revoke
it by removing it from the protected policy before trusting more outputs.

To disable the cache, set `url` and `publicKey` to empty strings in the
protected policy. CI then builds all offline checks. Reverting the workflow,
flake, and extraction restores the previous uncached gate. Cache release
assets are disposable and contain only check outputs; retain a bounded
history or remove the prerelease through a separately authorized repository
cleanup when no longer needed.
