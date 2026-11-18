# Implementation Plan: Mutable References and Automatic Image Digests

**Branch**: `codex/mutable-image-digests` | **Date**: 2026-11-16 | **Spec**: [spec.md](spec.md)

**Input**: `specs/20261117-050238-mutable-image-digests/spec.md`

## Summary

Use the installed Image Updater's native digest strategy and Argo CD write-back
for explicitly enrolled Applications. Owners commit mutable image selectors;
the controller owns effective image overrides. Preserve normal Git branch
reconciliation. Add narrow lifecycle ignores paired with provider computed
fields for those override collections, leaving unenrolled Applications and
other source fields unchanged. Remove the legacy workflow's direct protected
branch write path; remaining legacy proposal delivery uses normal protected PRs.

## Technical Context

**Language/Version**: HCL/OpenTofu >=1.10; Terragrunt HCL; Kubernetes YAML;
Python 3 for repository checks.

**Primary Dependencies**: Kubernetes provider 3.2.1; Image Updater v1.3.0;
existing chart 1.3.1; existing Argo CD and Helm/Kustomize sources.

**Storage**: Existing encrypted OpenTofu backend and Kubernetes Application/CR
state. No new database or persistent volume.

**Testing**: Existing Python checks, native HCL console, provider integration
fixture, Helm/Kustomize rendering, workflow syntax and negative-policy checks.

**Target Platform**: Existing homelab Kubernetes and protected GitHub delivery.

**Project Type**: Infrastructure/controller configuration.

**Performance Goals**: New digest or selector effective within two successful
configured controller intervals; unchanged results cause no image update.

**Constraints**: No protected-ref direct writes, no secrets in Git, no invented
operator image channels, no broad source ignores, no unrelated dependency
unpinning. No claims of live acceptance without a selected target.

**Scale/Scope**: One shared opt-in contract; single source or source index zero
plus ref-only sources; exactly one rendering source. No source hydrator/plugin
or multi-render-source enrollment in this increment.

## Constitution Check

| Principle | Before research | After design |
| --- | --- | --- |
| Repository-owned desired state | Pass: enrollment and ownership in code | Pass: native CR and explicit module selection; no manual patches |
| Public repository and secret safety | Pass | Pass: reuse references; no credential material |
| Validate before change | Pass | Pass: provider regression and normal plan gates precede enrollment |
| Reviewable and teachable | Pass | Pass: docs/wiki, protected PR delivery, explicit limitations |
| Reproducible bootstrap and ownership | Pass | Pass: existing unit/backend/resource identity retained |

No constitution amendment or exception is required. Runtime verification remains
conditional on an explicit selected target and existing deployment access.

## Project Structure

### Documentation (this feature)

```text
specs/20261117-050238-mutable-image-digests/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/enrollment.md
├── checkpoint.md
└── checklists/requirements.md
```

### Source Code (repository root)

```text
IaC/terragrunt-catalog/modules/argocd-application-kubernetes/  # existing default
IaC/terragrunt-catalog/modules/argocd-application-image-updater/ # new opt-in
IaC/terragrunt-catalog/units/live/argocd-app/terragrunt.hcl
IaC/homelab/us-west-2/apps/argocd-image-updater/
clusters/homelab/apps/argocd-image-updater/
.github/workflows/image-automation.yml
scripts/ci/argocd-image-updater-test.py
scripts/ci/argocd-image-updater-provider-test.py
scripts/ci/image-automation*.py
scripts/ci/argocd-image-updater-policy.py
scripts/ci/argocd-image-updater-policy-test.py
scripts/ci/harbor-images-check.py
renovate.json
scripts/ci/offline-checks.sh
scripts/ci/offline-static-checks.sh
docs/argocd-image-updater.md
openwiki/architecture/gitops-flow.md
```

**Structure Decision**: Keep existing registration module unchanged for default
applications. The unit selects an opt-in sibling module only when explicit
`image_update` settings are present. That sibling keeps the identical root
resource address `kubernetes_manifest.this`, provider and backend contract;
there is no counted-resource migration across the fleet. It owns a second native
ImageUpdater CR resource with exact application selection. Share small safe
source material where repository conventions allow; otherwise test parity of
provider/encryption/normalization defaults to keep bounded duplication honest.

## Design

### Explicit enrollment and selection

The unit passes a typed `image_update` object to the opt-in module. It includes
image aliases, registry image names with mutable tags, supported manifest target
names, and optional paused state. It must not accept Git write-back settings or
resolved digests. Native ImageUpdater resources use `writeBackConfig.method:
argocd`, `commonUpdateSettings.updateStrategy: digest`, exact application names,
and explicit image mappings. No wildcard fleet selector. Git branch references
stay in the Application's normal source configuration.

The shared unit currently unconditionally seeds default `sources`; adjust it to
seed that default only when neither `source` nor `sources` is explicitly
provided. Otherwise a legitimate single-source input would receive both forms.
Test the actual rendered unit as well as the module, preserving existing output
for all ordinary default inputs.

Validate exactly one of `spec.source` and `spec.sources`; for multiple sources,
index zero is the only Helm/Kustomize renderer and all remaining entries must be
value refs without another render path. Enrolled Helm `parameters` or Kustomize
`images` must be absent from the desired Application manifest, including empty
lists. These collections are created only by the controller. Normal settings and
owner-selected bootstrap tags belong in workload values/Kustomization. Existing
configured override collections require a reviewed ordinary-registration
transition before enrollment; do not silently erase or migrate them. Multiple
images are supported only through explicit non-overlapping mappings. Reject plugins,
source hydrators, ambiguous mappings and untracked image overrides.

### Enrollment and existing image policy

Extend each image mapping with exact repository-relative `source_paths` for the
workload manifests or values it owns. Reject absolute paths, traversal, globs,
missing files, paths outside that Application's declared source/value files, and
ambiguous partial ownership of the same package within a file. The enrollment
contract remains the canonical per-app `image_update` input; do not add a second
hand-maintained registry. Validation reads resolved Terragrunt inputs for the
explicitly opted-in stacks using the repository's existing render path.

For every enrolled image and source file, require an exact Docker package plus
exact file `enabled: false` rule in `renovate.json`. Do not automatically disable
a package globally or accept a wildcard rule as enrollment proof. The enrollment
checker fails with the missing package/file pair, so the owner adds the narrow
rule in the same reviewed change. Existing unrelated Renovate rules remain
untouched. Validate all occurrences of the same package in each claimed source
file belong to this mapping; reject partial ownership because Renovate's file
scope cannot express an individual container within that file.

`harbor-images-check.py` must retain source-file identity while checking image
references. It may accept a tag-only reference only when its exact normalized
path, repository and tag match a validated enrollment, and when existing catalog
provenance/registry access requirements for that repository/channel are met.
This removes the requirement to commit a rotating resolved digest for the
explicit target, not the requirement that its image source is declared and
available. A target whose repository/channel lacks a declared usable publishing
or proxy path is rejected with that prerequisite; this feature does not create
new mirror publication semantics. Identical tag-only references elsewhere still
fail the existing rules. Existing literal digest references continue through the
unchanged catalog checks. Check negative cases for wrong path, tag, repository,
unproven source, duplicate owner and broad Renovate exclusion.

The `scripts/ci/argocd-image-updater-policy.py` helper obtains enrollment facts from resolved inputs on demand and
shares that result with ownership/Harbor validation in the same run; no committed
generated registry or fleet-wide exception is needed. Empty enrollment preserves
all current policy behavior. Removal deletes the exact Renovate exclusion only
when no remaining enrollment owns that pair, restoring normal source ownership.

### Terraform and controller ownership

The opt-in module declares literal lifecycle ignores limited to supported
`source`/`sources[0]` Helm parameters and Kustomize images. It computes provider
`computed_fields` for only the applicable override collection. Both are needed:
provider read refreshes `object`, not `manifest`; ignoring the old manifest alone
cannot preserve a newer runtime digest. No ignores for complete source objects,
`targetRevision`, metadata, project, destination, or synchronization policy.

Validate lifecycle path shapes against the actual provider before accepting the
module, including absent alternate source forms. If the provider rejects absent
paths, keep distinct single-source and multi-source opt-in module entrypoints
with the same root resource identity; do not broaden ignores to evade a type
error. This is a bounded packaging variation, not a new ownership model.

Selectors live in the separate enrollment/CR configuration, so lifecycle ignores
cannot suppress tag changes. Source inputs and values continue reconciling.
New Applications bootstrap using the owner-selected tag and the updater resolves
the digest. On recreation the same process runs again; no historic Git digest is
presented as the desired release. Enforce absent configured runtime collections
as a resource precondition and policy check; do not seed them from selectors.
This is necessary because provider omission preserves live state only when the
collection was not previously part of desired manifest configuration.

The provider sends a planned object during apply. Keep `force_conflicts=false`
for active enrollment: a controller change after refresh must preserve the newer
image or reject the stale apply. Actual provider 3.2.1 tests cover before-refresh
and between-plan/apply changes. The real Application CRD treats `spec.sources`
as an atomic list; consequently intentional edits within that list may also
conflict. Do not broaden ignores or force active writes to hide this constraint.
Metadata, destination and separate enrollment selector changes remain ordinary
updates. Single-source fields outside the owned image collection retain their
normal field-level ownership.

For intentional multi-source edits, use three reviewed reconciliations: pause
and verify it has taken effect; temporarily remove enrollment and select the
default same-address module with the runtime image collection still omitted,
including the intended source change; then restore enrollment and resume.
Actual-provider request/state tests show the default module preserves the live
controller-only collection in this omission case, removes the native CR, changes
the intended source and keeps Application identity; reenrollment retains the
same runtime image. No resolved hash is copied into Git. Keep the exact Renovate
exclusion during this temporary maintenance window so another updater cannot
compete, and retain provenance requirements. An explicit paused/handoff ownership
record in the same stack must distinguish this temporary removal from permanent
unenrollment for policy validation; it must not activate a native CR or create a
second canonical registry. Reject contradictory active/handoff declarations.

Permanent removal differs: after pause, use the default module with an explicit
empty or reviewed replacement collection and restore ordinary Renovate ownership.
The temporary omission procedure is supported only for never-configured
collections. Existing seeded histories require migration under ordinary
ownership first; do not infer equivalent behavior from equal-looking current
state. The provider fixture must retain both history cases as regression evidence.

### Controller and legacy write-back configuration

Replace unsupported camelCase Helm configuration keys and the Git API commit
argument with chart-supported keys and native CR settings. Remove Git write-back
credential assumptions. Retain the controller image/chart pins as deployment
tooling; the request concerns operator workload channels, not an unrelated tool
upgrade. Preserve explicit registry credential references and hardened pod
settings, and render the actual pinned chart to prove values take effect.

Register the controller stack through the existing unit pattern and configure
one replica with no enrolled targets only if the existing registry image and
chart are reachable through declared paths and existing access suffices. The
controller can be idle without choosing a workload tag. If those prerequisites
fail, retain the staged declaration and record the exact runtime blocker;
no credential expansion or unrelated mirror migration is permitted. The current
read-only evidence confirms the controller is absent, not active.

Change legacy `image-automation.yml` to deliver validated proposals through the
normal PR route only. Remove its direct PATCH to main and the fallback ordering
that tries the direct write first. Keep existing signature/scope/receipt checks
for legacy candidates. This is not a rewrite of historical Harbor migration or
promotion logic. Ensure the legacy generator cannot enroll the same runtime
managed target, and reject duplicate ownership in validation.

### Transitions and operations

- **Enroll**: declare exact mapping; validate exclusive override ownership and
  registry access; reconcile registration plus native CR through normal apply.
- **Change selector**: update mapping; native updater resolves it. For an atomic
  multi-source list edit, use the paused temporary default-module omission
  handoff above and then reenroll; normal metadata/destination changes do not
  require that handoff.
- **Pause**: set native per-image/application ignore through committed settings;
  retain effective override. Confirm the actual v1.3.0 supported field in render.
- **Remove**: first pause and reconcile the native CR. In a subsequent reviewed
  change remove `image_update`, explicitly set the previously reserved override
  collection to an empty list or reviewed replacement in the normal Application
  source, and restore the exact package/file Renovate ownership. The unchanged
  resource address now uses the default module without the lifecycle ignore;
  its explicit override value performs the handoff. Merely omitting the field
  is not sufficient because provider state may retain an old override. The plan
  must show no Application replacement, removal of the CR and the intended
  collection replacement. The provider regression covers this complete
  opt-in-to-default transition before documentation presents it as supported.
- **Recover**: pause automatic changes, deliberately repoint the mutable channel
  through its existing publisher or follow a reviewed ownership handoff. Do not
  promise an old hash recovery mechanism that no longer owns enrolled images.

## Validation and Delivery

Run native HCL cases for default and opted-in manifests and schema/render checks
for CRs. Prove invalid/multi-render/nonimage-parameter mappings fail. Extend
workflow checks to reject protected-ref writes, bypass flags and force pushes.
A provider fixture must use the pinned real provider and a controlled API fixture
or disposable test cluster: create A, observe controller B, apply unrelated
metadata, verify B; change selector, verify selector accepted; verify source,
destination and normal values edits still apply; verify single and multi source;
verify plan/apply concurrency rejects or preserves the latest digest; verify
paused temporary opt-in-to-default omission preserves effective overrides across
source edits and reenrollment, while permanent removal explicitly clears/replaces
overrides without replacement. Require negative absent-versus-empty/seeded input
cases and distinct active/temporary-handoff/permanent-removal policy cases. A source
scanner or copied Python provider model is not sufficient evidence.

Protected PR checks and plan govern source delivery. Register/reconcile through
the existing repository path and verify the controller revision and health.
Since no workload selector was supplied, keep actual enrollment empty and report
runtime A-to-B acceptance as pending explicit target selection rather than
inventing a canary or silently enrolling historical migration candidates.

## Registration apply guard correction

The real registration runner currently rejects every `kubernetes_manifest`
delete action before saved-plan apply. This blocks both supported handoffs,
because removing enrollment deletes `kubernetes_manifest.image_updater` while
retaining `kubernetes_manifest.this`. The provider fixture alone did not exercise
this delivery guard. Correct the owning guard in
`scripts/ci/terragrunt-apply.sh`, using a small read-only JSON validator
`scripts/ci/argocd-registration-plan-check.py` in place of its blanket delete
predicate and its adjacent existing-only create predicate. Keep Conftest,
no-new-Application protection, exact saved-plan application, current-main
verification and all other stage ordering unchanged.

Validate each unit's plan independently; another file must never supply the
retained Application. Reject every Kubernetes manifest deletion/replacement
except a pure `["delete"]` at the exact managed resource address
`kubernetes_manifest.image_updater`. Its `before.manifest` AND refreshed
`before.object` must identify the native
`argocd-image-updater.argoproj.io/v1alpha1` `ImageUpdater`, with the same nonempty
name and namespace `argocd`, and both must have
`spec.commonUpdateSettings.ignoreTags == ["*"]`. Missing/unknown observed state,
unpaused refreshed state, replacement actions and ambiguous identities fail
closed. Require the native one-Application mapping (exact same-name
`applicationRefs` selector, no wildcard or pause-setting override) rather than
accepting an unrelated CR merely because its kind matches.

In that same plan require exactly one retained managed resource at
`kubernetes_manifest.this`, actions `["no-op"]` or `["update"]`, with concrete
before/after Application identities (`argoproj.io/v1alpha1`, `Application`, same
name as the updater, namespace `argocd`). A missing, renamed, unknown, created,
deleted or replaced Application cannot justify the exception. All other manifest
deletes remain rejected. No flag disables the guard and no new live mutation or
protection bypass is introduced. This permits only the already-paused CR removal
needed by temporary omitted-field handoff and permanent explicit-clear removal.

The same validator accepts an explicit existing-only mode. In that mode retain
the rejection of manifest creates except pure `["create"]` at exact managed
`kubernetes_manifest.image_updater`, with a concrete native identity and exact
same-name Application mapping in `after.manifest`, accompanied by the same
retained Application proof above. A newly created CR has no observed object, so
its identity comes from the planned manifest; unknown identity/mapping fails
closed. The native digest/Argo CD write-back contract must match the emitted
module CR; active or paused enrollment is allowed. No Application create, CR
replacement, arbitrary resource create, mismatched target or cross-unit proof is
allowed in existing-only mode. Outside that mode ordinary create behavior is
unchanged. This preserves the mode's no-new-Application intent while allowing
enrollment/reenrollment of a retained Application.

Add realistic plan fixtures and integration assertions in
`scripts/ci/terragrunt-apply-test.py`: accept paused deletion with retained
no-op/update Application for both transitions; reject stale manifest-only pause,
missing object, unknown/mismatched identity, wrong kind/API/address, CR
replacement, arbitrary manifest deletion, absent/renamed/replaced Application,
and an otherwise matching Application in another unit plan. Assert every rejected
case stops before apply. Use the real guard from the mocked-tool runner, not a
copied test predicate. Run the existing replacement and staged-policy failure
cases unchanged, plus Conftest's Terraform regression suite. Add existing-only
positive native CR enrollment/reenrollment with retained Application, and
negative arbitrary creates, Application creates, replacement, unknown identity,
wrong native mapping/address and cross-unit matching cases.

Inspection of `policy/terraform.rego` found no blanket manifest-deletion deny:
sensitive-resource deletion rules concern KMS, SSM and Secret resource types;
Application source policy examines planned after manifests. No Rego exception is
needed. Tests must retain those denials; this correction only narrows the
registration runner's blanket guards without relaxing their Application safety
contract.

## Complexity Tracking

No constitutional violations. One opt-in sibling module is justified by static
lifecycle expressions and the need to leave all unenrolled Applications unchanged.
Duplicated provider/encryption defaults require parity checks. Generated dynamic
lifecycle expressions, broad source ignores, and fleet-wide resource moves were
rejected as less reviewable for this bounded contract.

## Loopback fixture credential correction

Checkov CKV_SECRET_6 flags the provider fixture's inert literal bearer token.
The isolated loopback API does not authenticate requests, so omit the unnecessary
provider token entirely. Preserve the explicit loopback host and environment
isolation. Validate with the actual provider regression and pinned Checkov secret
scan; do not suppress the finding or change scanner policy.
