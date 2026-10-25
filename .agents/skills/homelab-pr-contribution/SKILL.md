---
name: homelab-pr-contribution
description: Prepare a homelab fix, upgrade, or app change as a reviewable pull request with the right source ownership, focused validation, and documentation. Use for creating a PR; use protected-prs for merging and release-verification for deployment.
---

# Homelab PR Contribution

Inspect the owning source, callers, tests, and affected workload README. Consult
[the task route](../../../openwiki/quickstart.md) when the user asks for wiki
context or source inspection leaves an important architecture or dependency
uncertainty. Keep desired state
in the repository: `clusters/homelab/` for runtime resources, `IaC/` and
`IaC/homelab/us-west-2/apps/<app>/terragrunt.stack.hcl` for registration, `IaC/terragrunt-catalog/modules/` for typed
infrastructure, and `.talos/` for Talos patches. Do not edit generated
`IaC/homelab/us-west-2/shared/` units or live resources.

Load only the matching specialist skill: [app onboarding](../homelab-app-onboarding/SKILL.md)
for a new Application, [Terragrunt](../terragrunt-workflows/SKILL.md) for IaC,
[secret contracts](../homelab-secret-contracts/SKILL.md) for credentials, or
[Harbor images](../homelab-harbor-images/SKILL.md) for image changes. An image
upgrade that needs a new mirror digest requires a separate catalog PR and
successful publication before its consuming PR merges.

Run the focused tests and [validation gates](../../../openwiki/operations/validation-gates.md)
for the touched surface: render and policy checks for Kubernetes, format and
plan for IaC, strict validation for Talos, and the relevant script fixture for
code. Run the repository static gate when available; record any unavailable
gate. Check `git diff --check` and inspect the final diff for secret material.

Update the workload README or runbook and affected OpenWiki context when the
change alters operations, contracts, or topology. Follow
[wiki maintenance](../../../openwiki/operations/wiki-maintenance.md); do not
hand-edit generated wiki pages.

Create a signed conventional commit and a PR with a conventional title. Include
the reason, affected path, validation evidence, and rollout or rollback
implications. Keep PR readiness distinct from deployment. When asked to merge,
use [protected PRs](../homelab-protected-prs/SKILL.md); when asked to deploy,
use [release verification](../homelab-release-verification/SKILL.md).
