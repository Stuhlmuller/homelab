# Shared OpenTofu state and plan encryption

[`IaC/root.hcl`](../IaC/root.hcl) owns client-side encryption in
`remote_state.encryption`, alongside backend configuration. Every unit including
that root receives the same AWS KMS policy for state and saved plans; reusable
modules have no encryption-only inputs or encryption blocks. The retired-unit
planning fixture also inherits the root policy.

Use the Nix development shell. It pins official Terragrunt **v1.2.2** release
binaries for Linux/macOS on both supported architectures, with fixed hashes
verified against the release's `SHA256SUMS`. The root rejects older Terragrunt.
Older generators can misinterpret `enforced` as a key-provider attribute;
centralizing the block requires the supported generator as well as HCL changes.
The package-set lock remains unchanged.

## Existing records remain readable

The policy retains `alias/homelab-opentofu`, `us-east-1`, `AES_256` and AES-GCM.
Terragrunt generates provider and method blocks named `default`; the former
module blocks used `main`. Setting
`encrypted_metadata_alias = "key_provider.aws_kms.main"` preserves the metadata
identity stored with existing ciphertext, so moving the configuration does not
require rotating keys or rewriting records. Keep this alias during future
refactors unless an explicit migration is designed and tested.

State and saved plans use `enforced = true` by default. The sole migration
exception is `homelab/us-west-2/operator/application-backup-storage`, whose
existing plaintext state was observed by authenticated CI on 2026-11-18.
Only that exact homelab unit accepts plaintext reads; AES-GCM remains its primary
write method for both state and saved plans. Backend key, KMS key and metadata
identity remain unchanged. No other unit gains a plaintext fallback.

The source-only plan does not rewrite state. During the next declared Terragrunt
apply for this unit, verify the state is encrypted, then remove this exact
fallback so enforced reads resume. Do not expand the exception to another unit
without evidence and a tested migration. Existing encryption tests
prove read-only planning, encrypted state/plan writes, preserved lineage and
strict reads after fallback removal using disposable local state.

S3 bucket identity, object paths, region, locking and SSE-KMS backend settings
are unchanged. Runtime SSM encryption still uses `alias/aws/ssm` in `us-west-2`.
Resource-facing key inputs in the SSM and GitHub role-policy modules remain
separate from client-side state protection. See also the existing
[state storage notes](../openwiki/operations/state-encryption.md).

## Validate the change

```sh
nix develop --command terragrunt --version
nix develop --command python3 -I scripts/ci/state-encryption-test.py
nix develop --command python3 -I scripts/ci/terragrunt-stack-test.py
nix develop --command terragrunt hcl fmt --check
nix develop --command terragrunt --working-dir IaC stack generate
nix develop --command terragrunt hcl validate
```

The encryption regression captures the real generated AWS KMS backend HCL
without contacting AWS, and exercises old/new encrypted local state and saved
plans with real OpenTofu and a disposable PBKDF2 provider. Its metadata-dependent
salt makes missing or wrong aliases fail; plaintext state/plans must also fail.
The retirement regression checks shared inheritance and actual generated
protection. The offline CI gate runs both tests.

These fixtures establish generation and ciphertext-format compatibility; they
do not establish live KMS permissions or prove all remote records are encrypted.
Use the existing [`scripts/ci/terragrunt-plan.sh`](../scripts/ci/terragrunt-plan.sh)
path with its established credentials for authenticated planning. Its protected
SSM/secret units, Langfuse storage and operator lanes have separate coverage;
a successful PR plan does not imply those exclusions were checked. Record missing
credentials explicitly. Never download live state into public test fixtures.

## Roll back source

Before any live operation writes encrypted records, the source change and tool
pin can be reverted together through normal delivery. For units previously
protected by the eleven module policies, preserving the old metadata identity
keeps new records compatible with those old policies.

Units newly covered by the root policy previously had no client-side encryption
configuration. After their first encrypted write, retain equivalent encryption
when reverting source until a separate migration is designed; removing their
policy would make the ciphertext unreadable. Do not treat a blanket source
revert as safe after activating encryption for those units.

Do not overwrite current state with an older state object as a source rollback.
No key, state-object or infrastructure mutation is part of this source refactor.

References: [Terragrunt encryption](https://docs.terragrunt.com/reference/hcl/blocks/remote_state/#encrypting-state),
[OpenTofu state encryption](https://opentofu.org/docs/language/state/encryption/).
