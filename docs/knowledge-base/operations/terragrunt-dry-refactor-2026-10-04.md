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

## Evidence

- Compared all 42 generated app-unit configurations against pre-change commit
  `9f295a5e`: inputs, ordered dependencies, complete backend configuration,
  provider generation, and module source are identical. This includes all 41
  Application manifests and the Wazuh retirement unit.
- Six offline regression cases exercise sparse generation, nested overrides,
  list replacement, backend paths, app/Azure selection, and retirement ownership.
- Harbor inventory remains unchanged: 83 declared image references and four
  Fleet images. Extraction now accepts chart sources without Helm overrides
  and rejects unextractable chart pins.
- All seven project skills passed schema validation. An independent onboarding
  exercise generated a new app in an isolated fixture and checked its manifest;
  findings added provider-lock creation under the then-current policy and exact
  AppProject allowlist guidance. The later lock policy below supersedes that
  provider-lock instruction.
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
Keep the same unit paths; no state migration is required.
Normal production delivery still requires the protected plan/apply path.

## Provider Lock Policy Update

The requested removal of committed OpenTofu provider lockfiles supersedes the
lock-creation guidance above. Initialization now creates ignored local
`.terraform.lock.hcl` files and checksums. Exact selected provider versions
remain in module/template HCL; this removal does not upgrade providers or
require a live apply. See [[operations/validation-gates#Terragrunt Checks]].

Removing committed locks also removes the repository's retained provider-package
checksums. Exact HCL constraints preserve versions, but fresh runners trust the
registry's current checksum set instead of comparing it with previously reviewed
hashes. This is a security tradeoff of the requested lockfile removal; exact
versions do not guarantee the same provider bytes across clean runs. See
[OpenTofu checksum verification](https://opentofu.org/docs/language/files/dependency-lock/#checksum-verification).

## Application Folder Split

The subsequent requested source split moves all 42 app-unit input blocks into
`IaC/stacks/<app>/stack.hcl`, including the Wazuh retirement placeholder.
`IaC/stack-defaults.hcl` now owns shared defaults for the 41 active Applications.
The root stack is an explicit index of the same 58 unit labels, template
sources, and historical output paths; non-Application settings remain in their
catalog templates. This supersedes the monolithic ownership description above.

Each app file is loaded through stable `read_terragrunt_config` semantics as the
root unit's `values`; it is not a nested `terragrunt.stack.hcl`. Generation still
runs once from `IaC/`, without changing backend keys or requiring state moves.
Split verification, 2026-10-04:

- All 58 unit labels, template sources, paths, and placement flags are unchanged.
  All 100 generated `terragrunt.hcl`/`terragrunt.values.hcl` files match the
  pre-split output byte for byte.
- The full static gate passed, including 468 tests across 33 unittest suites,
  provider validation, rendering, and security checks. The 11 stack tests cover
  old-to-split ownership, app/default selection, retirement, state keys, and
  source preservation across repeated generation.
- Conftest passed all 25,088 rendered-resource policy tests.
- Chart provenance now identifies each app file; all 23 distinct chart/version
  selections and all 83 declared image references remain unchanged.

Validation used a clean source snapshot without live backend access. This
source-only split did not run a live plan or apply. The preceding evidence
describes the earlier refactor; these results cover the later split.
