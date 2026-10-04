# Terragrunt Application Refactor

Tags: #operations #terragrunt #validation

## Change and Ownership

`IaC/terragrunt.stack.hcl` now supplies shared Application defaults to the same
`IaC/.catalog/units/live/argocd-app` template for all 41 existing workload and
platform registrations. Entries contain only app-specific metadata/spec and
dependency overrides. Native stack generation still writes ignored units to
their historical locations. The stack decreased from 3,785 to 2,017 lines.

All 58 stack unit identities, source paths, and output paths are unchanged.
Bootstrap, non-Application units, and Wazuh retirement retain their contracts.
Argo self-management, Cordium bootstrap, and the two storage provisioner child
Applications retain their lifecycle owners under those stack deployments.
Moving those children into independent OpenTofu state would be an ownership
migration, beyond this behavior-preserving refactor.

See [[patterns/helm-chart-organization]] for the researched decision to keep
pinned upstream charts, adjacent values, and Kustomize extras. The focused
project skills cover onboarding, secret contracts, Harbor publication,
protected PRs, and release verification. The Terragrunt skill now describes the
actual explicit-stack workflow.

## Pre-release Validation

- Compared all 42 generated app-unit configurations against current main commit
  `71f9424b`: inputs, ordered dependencies, complete backend configuration,
  provider generation, and module source are identical. This includes all 41
  Application manifests and the Wazuh retirement unit.
- Six offline regression cases exercise sparse generation, nested overrides,
  list replacement, backend paths, app/Azure selection, and retirement ownership.
- Harbor inventory remains unchanged: 83 declared image references and four
  Fleet images. Extraction now accepts chart sources without Helm overrides
  and rejects unextractable chart pins.
- All seven project skills passed schema validation. An independent onboarding
  exercise generated a new app in an isolated fixture and checked its manifest;
  findings added provider-lock creation and exact AppProject allowlist guidance.
- HCL formatting/validation, isolated OpenTofu module validation, and Conftest
  policy checks passed (95 policy self-tests, 1,120 workflow checks, and 25,088
  rendered-manifest checks). The full Nix static gate passed in the clean copy,
  including Checkov and secret scanning. No live plan or apply was performed.

The first whole-repository static run stopped at the secret-artifact gate on
pre-existing ignored backend cache files. Those files were retained; validation
used a clean isolated copy so local artifacts could not weaken the gate. The
eight changed executable/configuration files were byte-identical to this
worktree when the gate completed.

## Rollback

Revert stack, template, and catalog fixture changes together, then regenerate.
Keep the same unit paths and reviewed lockfiles; no state migration is required.
Normal production delivery still requires the protected plan/apply path.
