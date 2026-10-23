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
10001 and mode `0700`; `DirectoryOrCreate` would create a root-owned directory
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
source commit with `python3`, `kubectl`, and `yq`. The protected
`openclaw-enterprise-images.yml` workflow builds it from a clean exact `main`
checkout, embeds the source SHA, then signs and completely pulls it. The
dispatcher requires its embedded reconciler, Installation, and values bytes to
match current `main`, then projects current config with a SHA receipt through an immutable
ConfigMap. This lets a later commit pin the verified image digest. The chart's
bootstrap key must be readable as a
UID-10001-owned `0600` regular file; no root init container or CI artifact
should copy it. The current upstream bootstrap UID/mode is not yet proved.

The dispatcher checks current `main` before each write, source file parity,
the retained journal PVC/PV UID, path, and node, and the bootstrap PVC's bound
PV claim UID, Retain policy, local class, and placement on that same node. It
lists every namespace Job and refuses an uncertain `oce-journal-` Job even if
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
