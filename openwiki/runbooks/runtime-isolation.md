---
type: runbook
title: "Runtime Isolation"
description: "Current Pod Security and Istio boundaries, plus dormant firewall-only kube-router NetworkPolicy prerequisites and canary gates."
tags: ["runbook", "security", "kubernetes"]
sources:
  - id: openwiki-source-d9e93037542f56be8db8a431
    resource: repo://clusters/homelab/apps/cordium-bootstrap/generated-networkpolicies.json
  - id: openwiki-source-3f6d0b26d6634f9dca554267
    resource: repo://clusters/homelab/apps/harbor/networkpolicy.yaml
  - id: openwiki-source-18a0bbca47813e2e084aa71b
    resource: repo://clusters/homelab/apps/kiali/networkpolicy.yaml
  - id: openwiki-source-448cbe27130e9e3c4e8b10b3
    resource: repo://clusters/homelab/apps/kiali/values.yaml
  - id: openwiki-source-259f9ac5704d0293a7850944
    resource: repo://clusters/homelab/apps/mastodon/namespace.yaml
  - id: openwiki-source-a953c7d60cd7a8fdea7b14bd
    resource: repo://clusters/homelab/apps/mastodon/networkpolicy.yaml
  - id: openwiki-source-06c51d450592da5906a7761d
    resource: repo://clusters/homelab/apps/octelium-enterprise/generated-networkpolicies.json
  - id: openwiki-source-eb9ba8868bbd263b0cd40e71
    resource: repo://clusters/homelab/apps/octelium-public/configmap.yaml
  - id: openwiki-source-92921fc2790f07b9b1a48bd3
    resource: repo://clusters/homelab/apps/octelium-public/networkpolicy.yaml
  - id: openwiki-source-f8f5d3b6cb788d6762c27993
    resource: repo://clusters/homelab/apps/octelium/generated-networkpolicies.json
  - id: openwiki-source-9cb199d7fd0a511b7c7d689f
    resource: repo://clusters/homelab/apps/openclaw-enterprise-foundation/namespace.yaml
  - id: openwiki-source-878d8aa0884abae2a8194701
    resource: repo://clusters/homelab/apps/openclaw-enterprise-foundation/README.md
  - id: openwiki-source-1765d2b8de68537c36f7221e
    resource: repo://clusters/homelab/platform/network-policy/canary/fixtures.yaml
  - id: openwiki-source-007543776318a4afbd5fc1b0
    resource: repo://clusters/homelab/platform/network-policy/daemonset.yaml
  - id: openwiki-source-994a8289757a8dfdfff70e1b
    resource: repo://clusters/homelab/platform/network-policy/README.md
  - id: openwiki-source-df5b234ace5ca38a67ae3b6b
    resource: repo://docs/evidence/openclaw-enterprise-acceptance.md
  - id: openwiki-source-d04edc1f961af1e5e8d6ef79
    resource: repo://docs/evidence/openclaw-enterprise-policy-review.json
  - id: openwiki-source-e6fd9160ab2341143a5d45c8
    resource: repo://docs/image-egress-hardening.md
  - id: openwiki-source-556eb082b86343ef048df9f7
    resource: repo://docs/runtime-isolation.md
  - id: openwiki-source-54e352b5d1969695ce29dabe
    resource: repo://scripts/ci/network-policy-peers-test.py
  - id: openwiki-source-020791e1237c864b31f43a39
    resource: repo://scripts/ci/offline-static-checks.sh
  - id: openwiki-source-379810dcab1205ffb941d2cb
    resource: repo://scripts/ci/platform-maintenance-stage.sh
  - id: openwiki-source-79ade26d1f528d349dc08fed
    resource: repo://scripts/network-policy-canary-node.py
  - id: openwiki-source-1d91dece74882a3fae04c364
    resource: repo://scripts/network-policy-cleanup.py
  - id: openwiki-source-221eda5e9e283a2549066105
    resource: repo://scripts/network-policy-inventory.py
  - id: openwiki-source-ba849f5dbd0942cee0b0087d
    resource: repo://scripts/network-policy-ownership.py
  - id: openwiki-source-a347fb1739a2d297e214f41a
    resource: repo://scripts/network-policy-qualification.py
  - id: openwiki-source-aa83e90c74e65ee6187dbbb5
    resource: repo://specs/003-replace-openclaw-enterprise/research.md
generated: { by: "codex", at: "2026-10-24T03:50:35.181Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-31T22:18:24.858Z
---

# Runtime Isolation

Canonical runbook: [`docs/runtime-isolation.md`](../../docs/runtime-isolation.md)

Pod Security, service accounts, Istio authorization, and workload security
contexts are enforced desired state. Existing `NetworkPolicy` objects remain
intent-only while Flannel is the sole active CNI and the staged firewall-only
kube-router Application selects no node.
The protected [`firewall-baseline` stage](../../scripts/ci/platform-maintenance-stage.sh)
uses a fixed, digest-pinned Pod on `zimaboard-2` before enforcement. It reuses
the [cleanup snapshot parser](../../scripts/network-policy-cleanup.py) to require
no kube-router objects in IPv4, IPv6, or ipset, saves the full snapshot
privately, and confirms the Pod is absent before a placement can be admitted.
An orphaned probe has a protected, UID-bound `firewall-baseline-recover` stage
using the original private ownership marker.
The capture does not authorize admission. After private review, protected
[`placement`](../../scripts/network-policy-placement.py) binds the capture
version and checksum from current `main` to fresh Node/Pod identities, Pod
requests, two-minute node metrics, and kubelet nodefs
space, then writes one immutable, versioned receipt per run at
`receipts/<source-sha>/placement/<placement-run-id>.json`. A fresh run can
replace expired evidence on unchanged `main` without rewriting earlier receipts;
an expired baseline needs a new reviewed capture first.
Admission selects the run and exact S3 version, requires placement under
30 minutes old and baseline capture under one hour old, and fails below the
reviewed enforcer/fixture budget plus 128 MiB/100m reserve or 5 GiB filesystem free.
Rules and usage can change after capture; recheck before admission.
The [network-policy runbook](../../clusters/homelab/platform/network-policy/README.md)
describes the Node identity and separate placement review gates.
Most existing non-privileged namespaces declare baseline Pod Security. The
unsynced Enterprise foundation declares restricted enforcement for both
`openclaw-system` and `openclaw-agents`; this is source intent, not live
namespace acceptance.

Kiali's [repository ingress policy](../../clusters/homelab/apps/kiali/networkpolicy.yaml)
replaced the operator-generated `monitoring/kiali` rule without changing its
Pod selector or source-unrestricted TCP 20001/9090 ports. Argo CD applies
`kiali-server-ingress` at wave 0; the [Kiali CR](../../clusters/homelab/apps/kiali/values.yaml)
disables the operator policy at wave 1. The [October 19 read-only recheck](../../docs/evidence/openclaw-enterprise-policy-review.json)
found the old policy absent and the replacement's complete spec equal to the
former rule and source manifest. This proves ownership convergence, not narrower
access or enforcement. Octelium access, Prometheus scraping, and the isolated
enforcement canary remain open under [T018](../../specs/003-replace-openclaw-enterprise/tasks.md).

## Declared peer narrowing

Source policies select routed gateway and monitoring Pods instead of whole
namespaces. Cloudflared private egress selects the two Istio gateway Pod labels
on TCP/443 and the Octelium ingress dataplane labels on TCP/8080. Harbor
component and vulnerability-exporter metrics ingress selects Prometheus Pods
on TCP/8001 and TCP/8080. Harbor nginx and Mastodon gateway ingress select
`istio=ingressgateway` Pods in `istio-system`; Harbor nginx also retains labeled
Traefik Pods and same-namespace Harbor bootstrap Pods. Mastodon's ambient
namespace requires gateway-origin HBONE TCP/15008 before traffic reaches its
TCP/3000 and TCP/4000 application ports.

The offline peer regression ties these selectors to declared Cloudflared
origins, gateway routes, ServiceMonitor settings, and the Mastodon namespace
label. No enforcing canary has tested the flows. Recheck live Service selectors,
EndpointSlices, and Pod labels, then prove allowed paths, Service translation,
ambient HBONE, kubelet probes, and denied peers before activation.

## Egress enforcement prerequisite

The 2026-10-12 read-only audit found all Flannel and ztunnel instances Ready,
but readiness does not add egress enforcement. Gateway API CRDs and a
`GatewayClass` were absent; existing Istio Gateway objects use the legacy API.
Envoy Gateway and firewall-only kube-router are now staged in GitOps with
automatic sync disabled. The prior source-only NRI fragment is not the chosen
enforcement path.

Do not enable default-deny egress, `REGISTRY_ONLY`, an egress waypoint, or the
existing NetworkPolicies globally. Some policies are incomplete or deliberately
broad, and image pulls are node/containerd traffic rather than pod egress.
`zimaboard-2` is not a safe canary because it has no dedicated isolation/taint,
limited capacity, system DaemonSets, and a live backup workload.

The reviewed 214-image catalog passed protected publication and authenticated
Harbor pulls in [run `40011909180`](https://github.com/Stuhlmuller/homelab/actions/runs/40011909180).
Before activation, finish policy owner/render review, then admit an isolated
tainted canary with measured capacity and local-storage
placement. No existing worker currently qualifies without risking unrelated
stateful workloads. The [2026-10-20 13:07–13:15 UTC post-shutdown capacity recheck](../../docs/evidence/openclaw-enterprise-acceptance.md)
found about 3,398 MiB unreserved on the best worker against an initial
4,096 MiB Enterprise reservation, 6,308 MiB actual memory use, and 9.74 GB
root-filesystem space free. Every worker's `/var` uses eMMC and has less than
10.74 GB for a new 10 GiB local claim under the existing `/var/lib` pattern;
`acer` has only 1,802 MiB unreserved against the 2,304 MiB database and gateway
minimum. Unrelated Pods remain on every worker. A `NoSchedule` taint would
leave those Pods in place;
it is not an isolation proof.
The 2026-10-23 recheck still finds `acer` 503 MiB short of the minimum request
despite enough local disk, while the best worker has only 9.00 GiB filesystem
free. Relocating its 38 non-DaemonSet Pods needs about 3,342 MiB against
2,036 MiB combined free on the other nodes. Crossplane's separate 512 MiB
source/live replica drift does not create an isolated canary. Enforcement
remains disabled. The 08:18 UTC recheck on `main` `bcc08cb` separates this
2,304 MiB declared floor from the [initial 4,096 MiB planning reservation](../../specs/003-replace-openclaw-enterprise/research.md)
for API, worker, database, Envoy and gateway: if co-located on `acer`, that
budget exceeds unreserved requests by about 2,295 MiB before startup or peak
margin. The 2026-10-23 snapshot found four unrelated Pods on `zimaboard-2`,
including single-replica `Recreate` Langfuse PostgreSQL. The proposed moves
could leave only 428 MiB by requests after the enforcer and fixtures, without
measured peak or continuity proof. T022 still has no admitted canary or storage
placement.
The [evacuation manifests](../../clusters/homelab/apps/multica/values.yaml)
move Multica frontend to `acer`, the [Harbor exporter](../../clusters/homelab/apps/harbor/vulnerability-exporter.yaml)
to `zimaboard-1`, and [Cloudflared](../../clusters/homelab/apps/octelium-public/deployment.yaml)
across those two nodes. The [admission check](../../scripts/network-policy-canary-node.py)
allows `istio-cni-node` only as a system DaemonSet; it still rejects unrelated
Pods. A read-only 2026-10-26 check found Langfuse PostgreSQL on
`zimaboard-1`; this stage leaves its source placement unchanged. It also
found `zimaboard-2` at 1,330 MiB used (101% of allocatable) with 885 MiB
requested and Harbor exporter plus system Pods still present. A later
PostgreSQL move to `acer` remains backup-gated. After source merges, verify
Argo, endpoints, client paths, and fresh node capacity before treating the
evacuation as live or admitting a canary.

The planned enforcer and fixtures have 704 MiB in memory limits plus a 128 MiB
reserve, so pre-canary measured use must be at most 476 MiB of the observed
1,308 MiB allocatable. The 2026-10-26 measurement exceeds that gate; re-measure
after any declared evacuation, and do not lower the guard without hardware
evidence.
Compare private read-only Pod/NetworkPolicy snapshots and all rendered policies
with `scripts/network-policy-inventory.py`. Its review
fingerprints now cover ingress and egress, and missing or drifted ingress-only
generated policies fail the inventory. Obtain exact generator renders and a
fresh read-only snapshot before the canary. The [source-owner ledger](../../docs/evidence/openclaw-enterprise-policy-review.json)
pins source locations for the original 18 generated policies; 17 still match
their earlier full-spec hashes after Kiali's handoff. Cordium `ws-main` and
Octelium `svc-upstream` retain broad public egress findings, and generator
renders and real traffic remain unqualified. A 2026-10-20 read-only cluster
inventory counted 66 live policies: 17 Genesis-managed and 49 Argo-owned.
All 49 Argo-owned specs matched their rendered repository sources; this is
source convergence, not traffic or enforcement qualification.
The [Cordium expected-spec fixture](../../clusters/homelab/apps/cordium-bootstrap/generated-networkpolicies.json)
binds three complete policy shapes to pinned `v0.12.7` constructors. The
[Octelium expected-spec fixture](../../clusters/homelab/apps/octelium/generated-networkpolicies.json)
binds four Genesis policies to pinned `v0.35.0` constructors. The
[Enterprise fixture](../../clusters/homelab/apps/octelium-enterprise/generated-networkpolicies.json)
binds the remaining ten. All 17 complete expected specs are now source-bound;
pinned generator-binary renders remain unverified. The pinned `ws-main` and
`svc-upstream` constructors hardcode all-port public IPv4 and IPv6 egress
without a public-egress input; additive NetworkPolicies cannot narrow those
allows. Patch the owning generators upstream or build reviewed forks, publish
and pin corrected images, then refresh fixtures from actual generator renders.
Qualify required destinations and private-range denial on an isolated canary
before any enforcement.

Qualify allowed DNS/API/storage/mesh traffic and denied direct IP, alternate port,
IPv6, and gateway bypass on the canary. Prove enforcer restart, API loss,
IP reuse, rescheduling, cold reboot, and ownership-limited cleanup before
expanding to another node. Stock Enterprise's public TCP/443 requirement
remains broad egress; Kubernetes `NetworkPolicy` does not provide an FQDN
allowlist.

The protected `canary-admit` source path requires a fresh measured placement
receipt selected by run ID and exact S3 version, plus exact Node and system Pod
identities. It re-reads the bound firewall
capture and repeats Pod, metrics, node filesystem, and headroom checks before
mutation. It checks that the enforcer, cleanup Pods, and fixture traffic are
absent, then adds the dedicated
`NoSchedule` taint before the selector label. A complete cluster-wide label
inventory must exclude every other selected Node before mutation and just
before labeling; a conflicting post-patch read removes its own label and keeps
the taint. If admission changed the Node but
its final receipt upload failed, owner-only protected `canary-admit-recover`
runs on current `main` with the original admission SHA and run ID. That SHA
must be an ancestor of current `main`. It uses the original immutable attempt
and selected placement version. A same-run privileged probe
confirms the host firewall remains empty and deletes its owned Pod before
UID/resource-version guarded removal of only the canary label and taint. It
works after placement expiry or a newer `main` commit while the reviewed
canary node and taint remain unchanged.
An orphaned recovery probe uses the protected `firewall-baseline-recover`
token/UID deletion path with its recovery run and admission IDs.
After a qualifying traffic probe, exact reviewed GitOps commits
prune the fixtures and then the enforcer. Unrelated commits may land before,
between, or after these two dedicated commits. The protected stage walks full
first-parent history from the qualify SHA and rejects intervening policy
runtime-source changes under the guarded operational roots or Nix flake
inputs. The static gate accepts only five exact policy/canary source
phases; private receipts and live checks still gate protected operations.
Apply the fixture prune and verify
the live `network-policy-canary` namespace and all fixture workloads are absent
before ownership capture. Capture loads the successful admission receipt by
run ID, checks its selected placement run/version, and carries that selection
through ownership approval, cleanup, and release. The owner reviews the private
full firewall snapshot
and freshly approves its digest before `owned-cleanup` can delete those
objects. Capture through release require a complete node Pod inventory
matching the reviewed system DaemonSet UIDs plus the validated cleanup Pod
while it runs. After cleanup Pod deletion, release rechecks that only reviewed
system Pods remain immediately before removing the taint. An incomplete list
or foreign, terminating or replaced Pod blocks the stage. A system Pod restart
changes its UID and blocks the immutable placement path pending separately
reviewed recovery. A partial deletion requires a new capture and approval.
Inventory checks and firewall deletion are not atomic: a taint-tolerating Pod
could arrive during deletion. Live activation remains blocked until isolated
placement rules that out or a reviewed repository-owned isolation path exists.
The later enforcer and fixture rollout also lacks its own protected fresh
capacity gate; admission does not authorize that rollout. The earlier firewall
snapshot may drift after capture because admission does not run another
privileged probe.
`canary-release` verifies the cleanup, ownership and original placement
receipts, the exact two dedicated commits in current `main` history, absent fixture
namespace and workloads, and an empty owned firewall. It removes the label
first and waits for cleanup DaemonSet Pods to disappear cluster-wide, then
rechecks the node Pod inventory before removing the taint. A survivor or
timeout retains isolation. These staged paths do not make a current worker
eligible.

The nine repository-owned DNS egress policies now select only CoreDNS Pods on
TCP/UDP 53. Static renders check their peer and the matching Service/Deployment
selectors; live DNS qualification on the isolated canary remains pending.

The protected [`network-policy-qualification.py`](../../scripts/network-policy-qualification.py)
checks the live firewall-only DaemonSet image, flags, host mount and RBAC, then
checks the admitted tainted node, three fixed fixture Pods and their policy.
It rejects changed fixture commands, arguments, and container security contexts
before probing, so a modified server cannot make blocked traffic appear denied.
Its TCP/UDP allow-and-deny probes also resolve the Kubernetes Service name
through the reviewed `kube-dns` Service over both TCP and UDP 53. Each DNS reply
must contain a complete A record matching the live `default/kubernetes` Service
IP, and each probe requires an explicit remote outcome marker. Transport failure
or a malformed or wrong DNS answer cannot count
as a deny or DNS success. Both DNS results enter a private receipt that lists
the lifecycle scenarios still unverified. The qualifier does not create the
fixture or attest node reboot, enforcer recovery, or real workload traffic;
those remain live gates before enforcement expands.

See [Validation Gates](../operations/validation-gates.md) and [Workload Inventory](../workloads/inventory.md).
