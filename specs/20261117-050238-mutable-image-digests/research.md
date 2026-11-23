# Research

## Source coverage

Consulted the local Spec Kit 0.15.1 plan skill and complete official plan command
at `github/spec-kit` revision `a227e38315cd38172b04f2fb8f06ce8b69b38331`.
Repository source and the earlier specification checkpoint supply project context.
XERJ tools are unavailable in this execution interface; no node/corpus was
installed. Used pinned official source directly instead of claiming a corpus hit.
The coordinator's research worker supplied bounded provider/updater findings;
relevant source excerpts were independently read before this design.

## Decision: Native Argo CD write-back

Use v1.3.0 ImageUpdater CRs with digest strategy and Argo CD write-back. The
existing values contain unsupported chart keys and Git proposal configuration;
the pinned chart exposes dotted config names, registry configuration and CLI
arguments, while update strategy and write-back belong to native CRs.

Sources:
- <https://github.com/argoproj/argo-helm/blob/argocd-image-updater-1.3.1/charts/argocd-image-updater/values.yaml>
- <https://github.com/argoproj-labs/argocd-image-updater/blob/v1.3.0/pkg/argocd/argocd.go>

Alternative rejected: committing resolved hashes through Git, which conflicts
with the requested runtime ownership; retaining direct protected-ref promotion.

## Decision: Bounded source topology

`getApplicationSource` at v1.3.0 lines 1319–1364 chooses the first matching render
source, with status-aligned fallback. It is not an arbitrary per-image source
index dispatcher. Require source zero as the sole renderer, followed only by
value refs; support ordinary single-source applications as well.

Alternative rejected: advertising arbitrary multi-Helm/Kustomize mappings that
the controller cannot reliably address.

## Decision: Paired lifecycle and computed fields

Kubernetes provider v3.2.1 `read.go` updates only `object` around line 189.
`plan.go` lines 449–502 retains refreshed computed values when configuration is
unchanged; an explicit configuration change follows a separate path. Therefore
manifest lifecycle ignores alone do not prove protection from rollback.

Sources:
- <https://github.com/hashicorp/terraform-provider-kubernetes/blob/v3.2.1/manifest/provider/read.go>
- <https://github.com/hashicorp/terraform-provider-kubernetes/blob/v3.2.1/manifest/provider/plan.go>
- <https://github.com/hashicorp/terraform-provider-kubernetes/blob/v3.2.1/manifest/provider/apply.go>

Reserve complete image override collections exclusively for enrolled images and
pair their lifecycle ignores with computed paths. Reject mixed normal/image
Helm parameters. Keep selectors outside ignored collections.

Alternatives rejected: computed-only `object` lifecycle ignores; wildcard HCL
paths; ignoring all Application sources; guessing stable parameter positions.

## Decision: Opt-in sibling module preserves identity

Terragrunt selects a sibling module without changing the root resource address
`kubernetes_manifest.this`. Default apps retain existing behavior. This avoids
counted-resource address migrations or a blanket ignore change across the fleet.
Tests verify encryption/provider/normalization parity and absence of replacement.

## Decision: Treat saved-plan concurrency as an acceptance test

The provider applies planned data, not a fresh read at the last instant.
`force_conflicts=false` is a conservative guard, but its name is not proof of
race prevention. Test updater changes both before refresh and between plan/apply.
If the latter can restore old content, leave enrollment disabled and repair the
mechanism through the implementation/convergence loop. No live target is
currently selected, so source development need not expose an application to an
unproven ownership model.

## Decision: Separate controller readiness from enrollment

Current source and coordinator read-only checks show absent updater Application
and Deployment, with its CRD present. Registering an idle controller need not
activate historical candidates. Reuse existing image/chart/registry paths and
credentials; preserve a concrete blocker if these cannot run. No requested tag
exists for new enrollment. Historical `image-automation.json` candidates remain
not enrolled and their compatibility migration is outside this work item.

## Additional path and conflict evidence

The research worker inspected OpenTofu v1.10.6
`internal/configs/configschema/validate_traversal.go` lines 103–109 (dynamic type
validation) and `internal/tofu/node_resource_abstract_instance.go` lines
1511–1522 (missing ignore path skips). This supports literal alternate
single/multi paths in the same opt-in resource; retain a real OpenTofu test.
A separate updater field manager should cause non-forced SSA to reject a stale
planned digest, but actual provider/managedFields verification remains the
acceptance evidence. No broader mutation or local namespace workaround is used.

## Analysis correction: policy and removal boundaries

Analysis C1 identified `renovate.json` global `pinDigests: true` and only two
historical package exclusions, plus direct Harbor reference enforcement in
`scripts/ci/harbor-images-check.py` around lines 399–412. Decision: reuse resolved
per-stack enrollment as the sole source, require exact package/file Renovate
rules, and scope any tag-only policy allowance to exact path/repository/tag plus
existing declared source provenance. No global exclusion, parallel registry or
unrequested mirror redesign. Invalid or incomplete enrollment fails closed.

Analysis C2 identified missing removal proof. Decision: pause, then switch back
to the default same-address module with an explicit empty or replacement owned
collection, removing the native CR and restoring exact Renovate ownership.
Provider transition verification is required; omission is not assumed to clear
API-owned state. These are corrections within FR-009/010, not new scope.

## Provider-evidence correction: atomic source ownership and absent history

Actual provider3.2.1 fixture evidence distinguishes single/multi sources and
seeded/absent configured collection histories. The real CRD has atomic sources;
active multi-source edits conflict with controller ownership under non-forced
SSA. Never-configured collections survive a paused default-module omission
handoff, intended source edit and reenrollment without copying a digest into code
or replacing the Application. Therefore require absent collections at enrollment
and document this explicit temporary handoff. Preserve the existing default
module's force behavior only in the reviewed paused handoff; active enrollment
always remains non-forced. Existing configured collections need prior reviewed
migration, not an automatic state trick.

A temporary `image_update_handoff` record retains the same mapping with paused
true for exact policy/Renovate ownership, while `image_update` is absent. This is
necessary to avoid another updater competing during temporary default ownership;
mutual exclusion and paused state are validated. Permanent removal has neither
record and explicitly clears/replaces overrides. The parent-owned helper paths
are `scripts/ci/argocd-image-updater-policy.py` and
`scripts/ci/argocd-image-updater-policy-test.py`.
