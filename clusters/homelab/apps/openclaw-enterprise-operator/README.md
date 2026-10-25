# Enterprise journal operator (staged source)

This directory is intentionally absent from active Argo CD and Terragrunt
registrations. `kubectl kustomize clusters/homelab/apps/openclaw-enterprise-operator`
renders its future claim and permissions but does not create a Job or PV.
`scripts/config/openclaw-enterprise.json` keeps `journalOperator.enabled: false`.
The `reconcile`, `stop`, and `verification` workflow choices therefore fail
before any Job write. The existing `full-sync` choice remains executable.

The separate `occ-operator-journal` claim needs a fourth node-local static PV
with `persistentVolumeReclaimPolicy: Retain`, `hostPath.type: Directory`, and
exact node affinity. T022 must establish headroom before T035 commits its
actual node and path. The backing directory must already be owned by UID
1000 and mode `0700`; `DirectoryOrCreate` would create a root-owned directory
that the reconciler rejects. Do not mount a file or subPath: journal writes
replace a file and fsync the containing directory. Retain and back up the
journal separately from the chart's bootstrap claim.

The Job uses only GET/LIST Kubernetes proof RBAC, including an unfiltered raw
PodList from the dedicated tenant Namespace for an independent stopped-runtime
check with a resource version. An unlabelled or foreign Pod blocks the stop
receipt. The Job uses projected service-account credentials and a pinned HTTPS
API endpoint. The namespace
policy permits DNS, that API endpoint, and Traefik's private console listener;
Traefik has a matching ingress rule for this Job label. Prove the actual DNS answer, TLS
certificate, CNI policy behavior, and no sidecar before enabling. A Job needs
a signed, fully pulled Harbor operator image from a prior reviewed homelab
source commit with `python3`, `kubectl`, and `yq`. Its image also carries the
reviewed binder, startup checks, and config needed to verify Installation
binding beside the read-only bootstrap key. The protected
`openclaw-enterprise-images.yml` workflow builds it from a clean exact `main`
checkout, embeds the source SHA, then signs and completely pulls it. The
dispatcher requires its embedded reconciler, Installation, and values bytes to
match current `main`, then projects current config with a SHA receipt through an immutable
ConfigMap. This lets a later commit pin the verified image digest. The chart's
bootstrap key must be readable as a
UID-1000-owned `0600` regular file; no root init container or CI artifact
should copy it. The generated Job overrides the image's `USER 10001:10001`
with `runAsUser` and `runAsGroup` 1000. The committed operator declaration
still has UID 10001 as an intentional disabled-state guard; T035 must set it
to 1000 only after the journal directory and upstream bootstrap owner are
proved.

The dispatcher checks current `main` before each write, source file parity,
the retained journal PVC/PV UID, path, and node, and both bootstrap PVC/PV
UIDs, the PV claim UID, Retain policy, local class, and placement on that same
node. It lists every namespace Job and refuses an uncertain `oce-journal-` Job even if
its identifying label was removed. It creates a fixed single-container Job
with no restart, automatic service-account token, subPath, or TTL cleanup, and
with a bounded deadline. The operation script uses the durable journal's
exclusive lock and source-bound pending intent. A failed or uncertain prior Job
stops future dispatch until private state is examined; the runner deletes no
Job or volume. Its public log contains only a fixed pass/block line.

Run `python3 -I scripts/ci/openclaw-enterprise-journal-operator-test.py` for
offline failure and restart checks, and `kubectl kustomize` on this directory
for a render. The rendered bundle is not an apply instruction. Review the
source/image publication path, backing directory ownership, bootstrap file
mode, exact startup Secret hash, and live network proof before wiring the
bundle into GitOps or setting `enabled: true`. Stop and restore/acceptance
stages still require their own live recovery and owner-session receipts.

The protected `bind-installation` workflow keeps the bootstrap service key on
its PVC. Its checkout fetches full history so the dispatcher can prove the
pinned image source is an ancestor of current `main`. A source-bound UID-1000
Job reads the key through a read-only mount and
performs private Installation proof. Before creating that Job, the runner
verifies the exact immutable startup Secret and reviewed candidate bytes, then
pins its UID, resource version, candidate digest and immutable state in the
Job's Pod template. Job and Pod identity checks reject a changed baseline or
resources pending deletion. Pod readback admits only the two Kubernetes default
not-ready/unreachable `NoExecute` tolerations for 300 seconds. An unassigned
`Pending` Pod may wait within the bounded proof loop; a running Pod must be on
the pinned node before its proof is accepted.
The protected runner rechecks current `main` immediately before its
UID/resourceVersion-guarded patch of the one
startup Secret annotation, then requires an in-cluster post-patch proof. The
operator ServiceAccount has no Secret patch grant, and no key crosses to the
runner or public logs. The committed disabled operator and unenforced network
policy still prevent a live bind until placement, image, and network receipts
are reviewed.

If `main` advances after Job creation but before the Secret patch, the Job
times out without binding. The dispatcher then refuses a fresh attempt while
the failed Job remains. Inspect its private log, exact Job and Pod UIDs, and
the startup Secret read-only first. The protected `cleanup-failed-bind` lane
accepts the original source SHA, run ID, attempt, Job UID, and Pod UID. It
requires a terminal Failed Job with one failed Pod, unchanged ancestor source
and candidate bytes, the Pod-template Secret witness still at the same UID and
resource version without an Installation ID, retained PVC/PV identities, and
disabled activation. A still-running Job with an expired readiness receipt is
not eligible. It rechecks exact current `main` beside one foreground REST
DELETE guarded by Job UID and resource version. If the response is lost it
reads the Job and Pod back; it never repeats the DELETE. Completion requires
both gone with the Secret and retained storage unchanged. The production
workflow serializes cleanup with binding and exposes no private logs.

Use the reviewed [operations workflow](../../../../.github/workflows/openclaw-enterprise-operations.yml)
with `enterprise_stage=cleanup-failed-bind`, the current `expected_sha`, and
all five `failed_bind_*` inputs from read-only inspection. A missing Pod,
changed Secret, uncertain deletion, or failed storage proof needs a new review
before another run. The cleanup path is source-only until it passes protected
checks and is merged; T041 remains open pending live prerequisites and proof.

If the Secret patch commits but the Job or its post-patch proof fails, the
startup Secret may already name the Installation. The pre-patch cleanup path
cannot recover that state. Keep binding, retry, automatic Job cleanup, agent
activation and acceptance blocked until T041 supplies a separately reviewed
post-patch identity check and recovery path.
