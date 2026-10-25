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
its PVC. A source-bound UID-1000 Job reads it through a read-only mount and
performs private Installation proof; the protected runner rechecks current
`main` immediately before its UID/resourceVersion-guarded patch of the one
startup Secret annotation, then requires an in-cluster post-patch proof. The
operator ServiceAccount has no Secret patch grant, and no key crosses to the
runner or public logs. The committed disabled operator and unenforced network
policy still prevent a live bind until placement, image, and network receipts
are reviewed.

If `main` advances after Job creation but before the Secret patch, the Job
times out without binding. The dispatcher then refuses any fresh attempt while
that failed Job remains. Inspect its private log, Pod and Job UIDs, and the
startup Secret annotation and resource version read-only. A separate reviewed
cleanup workflow must prove those identities and remove only that failed Job
before a fresh exact-main dispatch. No automatic deletion or patch retry is
authorized by this source slice. T041 stays open until this recovery path and
the live prerequisites are proven.
