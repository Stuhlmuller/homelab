# Held Istio 1.28.10 hop

The live-owned `IaC/homelab/us-west-2/apps/istio/stack.hcl` stays at Istio
1.27.3 with its existing auto-sync and self-heal behavior. This directory's
[`upgrade-1.28.10.json`](upgrade-1.28.10.json) records a **disabled** candidate
for the first adjacent hop. It is not included in `kustomization.yaml` or the
Argo Application. That disabled 1.28.10 candidate changes no Istio runtime
object or Application sync policy.

The target's four digest-pinned images already live in the reviewed
[`platform-maintenance.json`](../../../../scripts/config/platform-maintenance.json)
and [`harbor-images.json`](../../../../scripts/config/harbor-images.json).
Those pins are source inventory, not successful Harbor publication. The
candidate records the SHA-256 of each official 1.28.10 chart archive and the
intended base/CRDs, istiod, CNI, ztunnel, two-gateway sequence. Offline Helm
renders with the existing release names, values, and parameters found every
resource labeled with its release name and no resource-identity changes except
that the 1.28.10 istiod chart omits the old `istiod` PodDisruptionBudget.
The candidate uses [Istio's replacement chart repository](https://istio.io/latest/blog/2026/retirement-of-gcp/)
at `https://blob.istio.io/istio-release/charts`; its downloaded archives match
these pins. The declared 1.27.3 sources and chart inventories use that same
repository with unchanged versions and package hashes. Apply the chart-source-only
Application change through a reviewed scoped Terragrunt plan, then require the
`istio` Application Synced/Healthy with unchanged workload images and no
unexpected resource diff. Keep the old GCS AppProject entry for rollback until
that live check passes. A failed chart fetch blocks the 1.28 hop; restore the
previous source only through another reviewed plan and apply.
The gateway chart keeps `image: auto`; verify the injected proxy's live image
ID against the published `proxyv2` digest during rollout.

## ztunnel bootstrap image

The reviewed stack declares the upstream Docker Hub reference at the unchanged
1.27.3 digest. On 2026-10-27, `ztunnel` on the Traefik node could not pull its
Harbor reference through the node's `10.96.0.50` registry alias. Renovate's
registry requests failed while that destination HBONE listener was unavailable.
All four nodes had no active `docker.io` mirror at that readback, so this
reference selects Docker Hub instead of the Harbor alias. Keep the staged
strict Talos mirror rollout held until ztunnel has an independent bootstrap
path; that mirror would send this reference back through Harbor. After the
reviewed Terragrunt and Argo CD rollout, require ztunnel available on all four
nodes and a scheduled Renovate dry run without Harbor Docker-token errors.
If upstream pulls fail, restore a working Harbor node route through the
reviewed rollback path before reverting this image parameter through
Terragrunt and Argo CD.

The [Istio 1.28 release](https://istio.io/latest/news/releases/1.28.x/announcing-1.28/)
supports Kubernetes 1.34. Its [upgrade notes](https://istio.io/latest/news/releases/1.28.x/announcing-1.28/upgrade-notes/)
warn that old ztunnels can NACK new `ServiceEntry` resolution `NONE` xDS until
ztunnel is upgraded, `BackendTLSPolicy` v1alpha3 handling is removed, and old
Pilot metric-rotation flags are gone. No Gateway API CRDs are installed by
this candidate; the separately owned Envoy Gateway path handles those.
Istio 1.28 is an intermediate hop, not the final target.

## Release gate

Do not change the active chart revisions until T024's Talos per-node receipts,
measured node capacity, verified legacy recovery, direct API access, a fresh
off-node etcd backup, and complete authenticated Harbor pull receipts exist.
`platform-maintenance.json` still has `activationEnabled: false` and no
admitted canary node. The existing protected maintenance workflow executes
Talos/Kubernetes stages and explicitly leaves Istio to separately reviewed
GitOps changes; it does not provide a guarded Istio sync lane. A later PR
must add that code path and stage-specific readiness receipts before applying
the 1.28.10 revisions. A single manual full sync of six updated chart sources
would bypass the upstream-required sequence; disabling auto-sync alone would
also remove the current mesh's self-heal behavior. Neither is this proposal.

The [upstream ambient upgrade sequence](https://istio.io/latest/docs/ambient/upgrade/helm/)
requires base CRDs first, then istiod, CNI, ztunnel, and manually deployed
gateways. The future lane must stop after each component until CRDs are
Established, webhook Services have ready endpoints, each Deployment or
DaemonSet is Ready on the expected nodes, and original API, DNS, HBONE,
storage, Kiali, Octelium/private-route and admission traffic still works.
CNI has no canary upgrade; ztunnel in-place replacement can interrupt
long-lived node connections. Stop on persistent xDS NACK, readiness errors,
admission failures, or unexpected traffic changes.

The old `istiod` PodDisruptionBudget requires an exact live Argo diff before
any prune. Review its removal only after all stages pass, with no other
unexpected deletion. Rollback requires a reviewed source change in reverse
data-plane order; do not automatically downgrade CRDs without checking stored
versions and schema compatibility. Record the failure and recovery proof
before the 1.29.9 hop.
