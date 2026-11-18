# Research: Centralize State Encryption

## Generation and enforcement

Decision: use released Terragrunt v1.2.2, narrowly pinned as official four-platform release binaries with fixed hashes
verified against the published release checksum manifest. Rationale: inspected v1.0.8 generator forwards every
non-key_provider map entry into the key-provider body and emits no enforcement; adding enforced there is invalid. The
actual locked nixpkgs revision `29916453413845e54a65b8a1cf996842300cd299` packages Terragrunt 1.0.4, while the
environment helper binary is 1.0.8. Neither is sufficient. The v1.2.2 generator explicitly recognizes
enforced/fallback and appends enforced to both targets; no fallback will be supplied.

Sources inspected:
[official remote_state docs](https://docs.terragrunt.com/reference/hcl/blocks/remote_state/#encrypting-state) ;
[v1.2.2 generation source](https://github.com/gruntwork-io/terragrunt/blob/v1.2.2/internal/codegen/generate.go) ,
especially parseEncryptionTarget and appendEncryptionTarget; pinned nixpkgs Terragrunt package. Coordinator identified
upstream enabling commit `484372bfa1f658b0beb28aba3de2365102016c2c` ; release tag source independently verified.

Package provenance: source at v1.2.2 requires Go 1.27.4, while the repository pins an older toolchain. A
source/vendor-only override would introduce an unrelated compiler upgrade. Use the established flake archive packaging
pattern instead: map x86_64/aarch64 Linux/macOS systems to official linux/darwin amd64/arm64 assets, verify their
SHA256 against the release checksum manifest, and fetch each fixed artifact through Nix. Verify actual version v1.2.2
from the resulting Nix shell. Do not change flake.lock or use an unpinned external executable. This keeps a
reproducible Nix dependency without upgrading the entire package set.

Alternatives rejected: omit enforcement (weakens existing contract); extra override/generated encryption block
(duplicates shared policy and adds merge complexity); globally upgrade nixpkgs (unrelated tool changes); patch old
generator (maintained fork unnecessary when supported release exists); source override requiring new Go 1.27.4
(unrelated compiler scope).

## Persisted metadata identity

Decision: set `encrypted_metadata_alias = "key_provider.aws_kms.main"` on the generated key provider. Rationale:
Terragrunt generates provider/method labels default, while existing policies use main. OpenTofu v1.11.1
`internal/encryption/keyprovider/addr.go` encodes default metadata identity as `key_provider.%s.%s` ;
`internal/encryption/keyprovider.go` chooses EncryptedMetadataAlias over the config address. Its `config/config.go`
names the attribute **encrypted_metadata_alias**, not metadata_alias. This keeps wrapped data-key metadata findable
without rewriting state or changing KMS keys for the previously encrypted modules. Newly protected units need to
retain equivalent encryption after first ciphertext writes during any source rollback; removing their new policy is
not a safe blanket revert. Method labels need not be persisted aliases.

Sources: [OpenTofu config](https://github.com/opentofu/opentofu/blob/v1.11.1/internal/encryption/config/config.go) ,
[metadata lookup](https://github.com/opentofu/opentofu/blob/v1.11.1/internal/encryption/keyprovider.go) ,
[address encoding](https://github.com/opentofu/opentofu/blob/v1.11.1/internal/encryption/keyprovider/addr.go) ,
upstream targets_test.go alias cases.

Alternatives rejected: silently accept default identity (old metadata unavailable); unencrypted fallback (does not fix
encrypted metadata identity and weakens policy); live state rewrite (unnecessary risk).

## Offline verification

Decision: real OpenTofu PBKDF2 old/new state AND saved-plan round trips from a standalone disposable Terragrunt map,
plus separate actual production-root AWS KMS backend generation captured by a non-cloud CLI shim. Rationale: PBKDF2
stores random salt metadata and therefore detects alias errors; no AWS permissions or live state access required. Keep
the standalone provider analogue entirely in ephemeral tests, and explicitly distinguish metadata/format compatibility
from authenticated KMS access. Test missing alias and plaintext records negatively. A local KMS emulator would add
unrelated services/dependencies; static string tests alone cannot prove decryptability.

## Retirement and inputs

Decision: deleted-unit fixture inherits centralized encryption and must delete its own block. Rationale:
`scripts/ci/terragrunt-filter-base.sh` already inherits root, and `terragrunt-stack-test.py` currently inspects its
independent main-policy synthesis. Resource-facing kms_key_id consumers in aws-ssm-parameters and
aws-github-actions-role-policy remain; all policy-only module variables and root propagation are removed.

## Workflow source coverage

Installed local plan command and template read fully, no before/after hooks. Official
[Spec Kit v0.15.1 planning command](https://github.com/github/spec-kit/blob/v0.15.1/templates/commands/plan.md) read
fully and reconciled with local command: integration paths differ, behavior ends after phase 1 design. This is
targeted source coverage, not a claim to have reread the entire upstream corpus. Constitution 1.0.0 reused unchanged.

## Refreshed repository baseline

Coordinator advanced isolated worktree to `093a1b1f5772f2078178590a457f0a53f78ade8b` . Root backend unchanged.
Upstream retirement changes harden inventory/Git failures without changing encryption synthesis. New
`argocd-application-image-updater` module adds an eleventh duplicate policy; existing all-modules requirement already
covers it. Baseline pinned tools verified by coordinator: Terragrunt 1.0.4, OpenTofu 1.11.8; helper binaries
1.0.8/1.12.3 are not the pinned validation environment.

## Documentation and validation ownership amendment

Decision: use source-authored docs/state-encryption.md plus README, as authorized by coordinator after unavailable
OpenWiki lifecycle tools/CLI were established. Rationale: FR-008 requires source-linked
ownership/compatibility/validation/rollback documentation, which this destination supplies without hand-editing
managed wiki or control artifacts. Alternative rejected: claim a wiki lifecycle update that could not be executed. The
wiki remains unchanged and tooling limitation remains disclosed. Actual validation owner is
scripts/ci/offline-checks.sh beside stack regression, consumed by static checks through Nix; avoid duplicate static
registration.
