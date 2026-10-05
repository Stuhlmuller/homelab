---
name: homelab-secret-contracts
description: Add or change homelab SSM, ExternalSecret, and workload credential contracts, including rotation wiring and secret retirement. Use for declared secret names, access boundaries, or refresh behavior, not for retrieving credentials.
---

# Homelab Secret Contracts

Read only the affected rows in the [secret matrix](../../../docs/secrets-aws-ssm.md)
and [identity architecture](../../../docs/knowledge-base/architecture/secrets-and-identity.md),
then trace the actual declaration, reader policy, ExternalSecret and consumer.
The matrix is an index; source files decide the current behavior.

## Change the complete contract

- Put declarations in the authoritative shared SSM or provider-owned catalog
  inputs indexed by `IaC/terragrunt.stack.hcl`, not generated `IaC/live` files.
  App registration inputs under `IaC/stacks/<app>/stack.hcl` reference those
  producer units; they do not own the secret material.
  Preserve the distinction between runtime SSM encryption in `us-west-2` and
  OpenTofu state encryption in `us-east-1`.
- Generated internal credentials belong in OpenTofu encrypted state/SSM;
  external provider credentials use the existing safe placeholder/injection
  contract. Never substitute a plaintext value into git, output, or examples.
- Grant exact parameter names to External Secrets. Check reader policy limits
  and add a namespace to the `aws-ssm` ClusterSecretStore allowlist when adding
  its first ExternalSecret. Do not add a broad `/homelab/*` reader grant.
- Keep privileged bootstrap/root credentials out of app containers. Prefer a
  mounted file when the application supports one; declare the target Secret,
  key and mount path together.
- Trace refresh semantics. `OnChange` needs a repository metadata change;
  version-pinned remote refs need a new version; environment-backed consumers
  need the documented GitOps rollout annotation. Updating SSM alone may not
  refresh either External Secrets or the running consumer.
- Stable encryption/signing keys require the app's backup/recovery plan before
  rotation. For retirement, check all consumers and IAM readers; existing SSM
  tombstones are intentional where deletion is denied. Do not remove state or
  values without a reviewed retirement path.

## Verify

Run the relevant static, render and policy checks from
[validation gates](../../../docs/knowledge-base/operations/validation-gates.md).
Secret-bearing shared SSM and secret materialization units are excluded from
ordinary PR plans: that skip does not validate their production plan. Review the
authorized private saved plan, including unrelated shared-unit changes, through
the [declared apply path](../../../docs/ci-cd.md); never paste it into a public PR.

After an authorized rollout, inspect ExternalSecret readiness, declared target
metadata and the actual consumer action without printing Secret data. Update
the matrix, workload inventory and relevant identity/storage notes in the same
change. Use an existing repository-owned injection/reset workflow for values;
if none exists, add the missing path before changing live credentials.
