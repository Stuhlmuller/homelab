# Enrollment Contract

The public input is optional `image_update` on the existing application stack.
It contains `images`, each with a unique alias, `image_name` of
`registry/repository:operator-selected-tag`, and an explicit Helm or Kustomize
mapping, plus exact repository-relative `source_paths` for owned manifests or
values files. A paused flag suppresses updates while retaining effective content.
Exact field names must be reflected consistently in module types, examples and
native CR rendering; the supported semantics below are fixed.

Accepted source forms:

1. `spec.source` with one Helm or Kustomize renderer.
2. `spec.sources[0]` with that renderer and subsequent value refs only.

Reject missing tags, digest-bearing selectors, duplicate aliases/targets,
ambiguous render sources, plugins/hydrators, wildcard applications, and override
any configured runtime override collection, including an empty or image-only
seeded list. Owner-selected bootstrap tags belong in workload source. An empty enrollment cannot accidentally
select every Application. Unenrolled apps never gain runtime field ignores.

Native output uses `argocd-image-updater.argoproj.io/v1alpha1`, `kind:
ImageUpdater`, digest update strategy and `writeBackConfig.method: argocd`.
Validate against the installed/pinned CRD, including exact per-image mapping and
pause schema. The legacy proposal workflow has no direct protected-ref write
route; source changes use protected PR delivery.

Changing the declared selector updates the native CR even when effective image
overrides are ignored by registration. No version promotion or semver selection
is inferred. A tag may intentionally move backwards.

Application resource identity and backend keys remain unchanged when enrollment
selects a different module. Plans that replace an Application are rejected as
migration failures. Removal must explicitly hand back the override collection;
merely deleting the ImageUpdater CR does not remove its old runtime overrides.

Policy integration requires an exact Docker package and exact file Renovate
`enabled: false` rule for every owned pair. Missing or wildcard-only exclusions
reject enrollment. Source paths must be existing files belonging to the
Application's source/value inputs, with no traversal/globs or partially owned
occurrences of the package. No second canonical enrollment registry is added.

A tag-only Harbor reference is exempt from committed-digest matching only for
the exact validated source-path/repository/tag tuple and only with its existing
declared source/provenance path. Matching a package elsewhere does not exempt it.
Absent publication/proxy support is a prerequisite failure, not authorization to
widen catalog or registry policy. Unenrolled checks remain unchanged.

Removal is two reconciled changes: pause first; then remove enrollment while
explicitly declaring an empty or reviewed replacement override collection under
the default module and restoring the exact Renovate ownership. Provider tests
must prove no Application replacement, CR removal and no surviving stale image
override. Field omission alone is not accepted for permanent removal.

## Implemented input names

`image_update.paused` is an optional boolean (default false).
`image_update.images` is a nonempty list of objects containing `alias`,
`image_name`, `source_paths` (a set of exact YAML paths), and exactly one target:
`helm = { name = "image.repository", tag = "image.tag" }`,
`helm = { spec = "container.image" }`, or
`kustomize = { name = "registry.example/app" }`.
These target keys are chart/image identities, not selected release versions.
The native pause setting is `commonUpdateSettings.ignoreTags: ["*"]`; unpause
restores an empty ignore list. Native digest strategy and Argo CD write-back
are fixed by the module, not caller-selectable inputs.

For deliberate atomic multi-source edits, reconcile `paused = true` first,
then move the enrollment mapping from `image_update` to `image_update_handoff`
with `paused = true` while leaving runtime collections absent and applying the
source edit through the default same-address module. The temporary handoff keeps
its exact Renovate exclusion and policy ownership; it creates no native CR.
Restore `image_update` and remove `image_update_handoff` to reenroll. Both
objects at once, an unpaused handoff, or a configured override collection during
handoff are rejected. No hash is copied into source. This temporary preservation
procedure is distinct from permanent removal's explicit override replacement.

The module validates path syntax and containment in the renderer source or
referenced Helm value files. Existence, package occurrence ownership, provenance
and Renovate policy are additionally checked by the enrollment validator; this
foundation module alone is not a completed enrollment gate.
