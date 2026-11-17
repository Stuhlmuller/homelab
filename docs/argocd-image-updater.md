# Argo CD Image Updater

The native ImageUpdater controller resolves an operator-selected mutable image
tag and writes its digest to the Application through Argo CD. It does not write
workload versions or hashes to Git. Git source branches remain ordinary
Application configuration; a Git branch is not an image tag.

The declared controller has one replica and no enrolled workloads. Source
configuration and registry manifest availability have been checked; controller
readiness and a real workload update are still pending deployment evidence.

## Enroll a workload

Use the shared `argocd-app` Terragrunt unit and add `image_update` to its stack
values. This example uses placeholders, not a recommended channel:

```hcl
image_update = {
  paused = false
  images = [{
    alias        = "app"
    image_name   = "harbor.stinkyboi.com/PROJECT/IMAGE:OPERATOR_TAG"
    source_paths = ["clusters/homelab/apps/APP/values.yaml"]
    helm         = { name = "image.repository", tag = "image.tag" }
  }]
}
```

For a chart with one combined image field use `helm = { spec = "image" }`.
For Kustomize use `kustomize = { name = "ORIGINAL_IMAGE_NAME" }` instead.
Set the same mutable tag in the referenced workload file. Each source path must
contain exactly one occurrence of the selected repository with that tag; multiple
occurrences of the same package in one file are rejected. Paths must belong to
the Application source or its referenced values file. Existing Harbor publication
and provenance policy still applies; this does not create a new mirror channel.

The Application must have one Helm or Kustomize renderer at `spec.source` or
`spec.sources[0]`. Additional sources may only supply references. Plugins,
hydrators, other renderer positions, and mixed owners are rejected. Keep the
Application's `helm.parameters` or `kustomize.images` collection **absent** from
Git, including empty arrays. Put ordinary chart settings in values files. Existing
configured override arrays must first be removed through the default module's
normal reviewed reconciliation before enrollment; this is not automatic migration.

Add one exact Renovate rule for each owned repository/file pair:

```json
{
  "description": "Argo CD runtime digest ownership",
  "matchDatasources": ["docker"],
  "matchPackageNames": ["harbor.stinkyboi.com/PROJECT/IMAGE"],
  "matchFileNames": ["clusters/homelab/apps/APP/values.yaml"],
  "enabled": false
}
```

Broad rules do not establish ownership. Policy rejects missing, orphaned or
conflicting rules and legacy/runtime dual enrollment. Unenrolled images retain
the existing digest and Renovate policies.

## Change selectors, pause and edit sources

Change both the workload bootstrap tag and `image_update.images[].image_name`
together. Do not commit the resolved digest. Set `paused = true` and let that
change reconcile to pause the native CR. Metadata and destination edits retain
ordinary Terraform ownership.

The opt-in module retains the same `kubernetes_manifest.this` address. Literal
`ignore_changes` paths and provider `computed_fields` preserve runtime overrides;
other Application fields remain managed. Kubernetes treats multi-source arrays
atomically, so concurrent source edits may fail with a field ownership conflict.
The enrolled module uses `force_conflicts = false`: resolve the conflict through
the following declared handoff, never by forcing an apply or patching the cluster.

1. Reconcile `image_update.paused = true` before editing the source.
2. Move the same mapping to `image_update_handoff` with `paused = true`, removing
   `image_update`. Keep override collections absent and make the intended source
   edit. The default module retains the current runtime digest while removing the
   updater CR. The default module uses its existing forced ownership only after
   this declared pause and ownership transfer. Keep the exact Renovate rules and workload tag unchanged unless
   intentionally changing that selector. Handoff metadata keeps policy ownership.
3. Restore `image_update`, remove `image_update_handoff`, and reconcile before
   resuming. Reenrollment preserves the current digest. No hash is copied to code.

The saved-plan registration guard permits updater deletion only when both the
configured and refreshed observed CR are paused and the same plan retains the
same Application. Existing-only registration may create the native updater CR
beside a retained Application, but cannot create a new Application. Unknown state,
identity mismatches, replacements and proof borrowed from another unit fail before
apply. The actual-provider regression exercises this guard on both removal plans
and the reenrollment plan; it does not prove live controller reconciliation.

The two inputs are mutually exclusive. The handoff is only supported after the
runtime collections were absent throughout enrolled desired configuration.

## Remove ownership or recover

Permanent removal is different from temporary handoff: pause and reconcile,
remove both ownership inputs, explicitly clear or replace the override collection
through the default module, and restore the ordinary workload/Renovate policy
(including removing its marked exception). Omission alone preserves runtime data
and therefore is not permanent removal. Review the resulting plan for no
Application replacement. Recreation uses the declared bootstrap selector until
the controller resolves it again; observe that reconciliation before declaring
recovery complete.

The real provider regression uses a local API fixture to inspect refresh, plan,
apply payloads and conflict propagation. It is not evidence of live Kubernetes
managed-field behavior or successful controller reconciliation. Runtime acceptance
requires publishing two digests behind an operator-selected tag, observing the
second, and confirming an unrelated normal apply preserves it.

## Protected delivery and validation

All configuration changes use ordinary protected pull requests. The historical
image catalog remains separate; its optional proposal workflow can create/reuse
a PR and request normal auto-merge for the exact validated head. It cannot write
`main` directly or bypass checks. GitHub's default workflow token may not trigger
new PR checks; if those checks are absent, delivery waits for the normal permitted
CI path rather than bypassing protection.

Offline checks run native HCL/unit, policy and protected-PR regression fixtures.
The `Argo CD runtime image ownership` pull-request workflow downloads the pinned
provider for an isolated API test and renders the pinned Helm chart. See the
[validation quickstart](../specs/20261117-050238-mutable-image-digests/quickstart.md)
for commands and the distinction between source validation and runtime evidence.
