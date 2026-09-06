# Restore image release reference

Related: [[restore-image-publication]], [[restore-image-anonymous-pull]],
[[restore-talos-synthetic-gate]], [[../architecture/gitops-flow]].

## Status and source ownership

The restore candidate remains excluded from the active `octelium-storage`
Application and its CronJob remains suspended. No published image pin exists.
`scripts/ci/restore-activation-reference.py` prepares the future Application
reference; it does not register, sync or activate anything.

The constructor and its tests live under the existing `scripts/ci/restore-*`
publication source binding. They must be finalized before image publication.
The later image pin is the one exact excluded artifact,
`images/postgres-restore-egress/published-image.json`. Embedding that image digest
in the bound candidate instead would change the image's source label and digest
again. No additional source exclusion or image environment file is needed.

The constructor reuses the synthetic gate's local pin/source contract: committed
strict pin, clean checkout, source ancestry, identical scoped Git inventory and
working-file bytes/modes. Missing pin fails before subprocesses, credentials or
network access. This local constructor does not perform or attest the separate
anonymous pull, native CI or actual Talos runtime checks.

Its deterministic JSON declares a dedicated `octelium-postgres-restore-drill`
Application with one source: the unchanged `restore-drill-candidate`
kustomization on `main`. Kustomize overrides the image with the exact pinned
repository digest and explicitly prepends `/usr/local/bin/restore-no-network`
to the CronJob command; Kubernetes' explicit command otherwise bypasses the
image ENTRYPOINT. The override keeps `suspend: true` and selects Linux/amd64
nodes, matching the only platform accepted by the publication pin. It does not
establish compatibility on every matching node; exact Talos runtime and release
placement still need their separate checks. Production PostgreSQL is outside
this Application's source. The existing `homelab` AppProject permits
the destination; `homelab-workloads` currently excludes `octelium-storage`.
[Argo Kustomize overrides and patches](https://argo-cd.readthedocs.io/en/stable/user-guide/kustomize/).

## Dormant Terragrunt template

`IaC/.catalog/units/live/argocd-octelium-restore/terragrunt.hcl.template` uses
the existing Argo Application module and calls the constructor through quiet,
uncached `run_cmd`. It is deliberately unregistered and lacks the canonical
`.hcl` suffix: locked Terragrunt evaluates `run_cmd` even in an unregistered
catalog's `terragrunt.hcl` during `hcl validate`. A missing publication pin must
not break today's root bootstrap. Instantiating the template does fail closed
without the pin; it never substitutes an empty manifest or stock image.

Run the offline render and failure-path tests with the locked toolchain:

```sh
nix develop --command python3 scripts/ci/restore-activation-reference-test.py
```

The normal static gate also runs those tests. They render real Kustomize inputs
and the Terragrunt template with synthetic publication data. Those fixtures are
not publication receipts, live API validation or permission to run a restore.

## Later release and rollback

After prerequisite integration, publish the finalized source and commit its
reviewed pin. Retain separate successful anonymous-pull, native-CI and protected
Talos receipts for the exact source/image. A later reviewed IaC-only change may
instantiate this template, register the dedicated unit with its storage
dependency and provider lock, and validate its final rendered manifests and
Terragrunt plan. Copy and retain the dormant `.hcl.template` for its bootstrap
fixtures; modify the separate canonical release unit. The bound tests check
isolated fixture state, not whether the real stack is permanently unregistered.
Keep the bound constructor, tests and candidate unchanged.

Registration initially remains suspended. Activation requires separate review
of an exact CronJob suspension patch in the release IaC, plus the existing real
backup-read approval and runtime/storage gates. Do not add the candidate to the
production storage kustomization or apply generated JSON manually. Acceptance
then requires scheduled restore success and the existing staleness alert.

The source comparison proves the checkout at construction time. Argo tracks
`main`; it does not continuously enforce that publication contract. Suspend the
drill through reviewed IaC before changing any bound source, then republish and
repeat the receipts before resuming. Suspension prevents future schedules; it
does not terminate an already running Job. Preserve failed diagnostics and use
the documented bounded Job lifecycle. Roll back through reviewed release IaC;
do not rewrite published tags or remove backup storage.
