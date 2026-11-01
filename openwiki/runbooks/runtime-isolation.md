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
margin. `zimaboard-2` has four unrelated Pods, including single-replica
`Recreate` Langfuse PostgreSQL; moving them could leave only 428 MiB by
requests after the enforcer and fixtures, without measured peak or continuity
proof. T022 still has no admitted canary or storage placement.

The [private-ingress candidate](../../docs/runtime-isolation.md#private-ingress-on-an-existing-worker-candidate-2026-11-01)
keeps live Traefik on `zimaboard-1` and stages a second Traefik controller on
`acer` with a userspace Tailscale sidecar, leaving the old controller and
LoadBalancer serving during tests. Its Pod must match no existing private,
Funnel, or registry Service selector. Private HTTP/HTTPS listeners would bind
only to Pod loopback, with raw TCP Serve exposing HTTPS 443 first while Traefik
retains TLS termination. Port 80 needs separate review. This could close the
private listener when kube-router or the sidecar is absent, without clearing
another worker. Its source is staged but the runtime is not deployed or
proven. The current Tailscale operator uses a separate proxy;
[`tailnet-dns`](../../clusters/homelab/platform/tailnet-dns/README.md) derives
answers from its LoadBalancer status,
[`tailscale-ingress-sign.py`](../../scripts/tailscale-ingress-sign.py) signs
that fixed proxy, and
[CoreDNS](../../clusters/homelab/platform/dns/coredns-configmap.yaml) sends
Harbor and Octelium API names to its Service. A selectorless headless Service
with a ready EndpointSlice could publish the sidecar device IP, but a static
device IP is unsafe after reassignment. The candidate is a pinned-provider
[Tailscale Service](https://tailscale.com/docs/features/tailscale-services)
with a stable IPv4 TailVIP and one exact, signed canary host approved through a
repo-owned script.
The [Service host approval command](../../scripts/tailscale-service-host-approve.py)
requires live policy to match reviewed source, one test-user grant for only
Service TCP 443, a single pending host, the exact `acer` canary Pod and
persistent state identity, matching Tailscale device ID/public node key/tag,
signed Tailnet Lock state, and raw TCP Serve to loopback 8443. Its preview
fingerprint binds a later current-main approval to that observed identity.
It rejects auto-approval and rechecks immediately before its sole host
approval write; the staged policy and canary do not yet satisfy preflight.
The first live preview must confirm the `/vip-services` definition read and
`/services` pending-host shape before execution. Traffic and wrong-host
withdrawal probes remain required after API approval.
The Service endpoint uses raw TCP 443 to the canary loopback listener. A
selectorless headless Service and reviewed EndpointSlice would publish that
TailVIP; DNS may still answer it while the host is offline, so a cached-A
negative test must show traffic fails after drain, peer loss, or wrong-host
advertisement. Keep the approved-name A/AAAA view without public `fallthrough`
or `forward`, and its allowlist aligned with Traefik routes and the Service
annotation. Probe immediately after withdrawal, before the 30-second resolver
cache expires; client caches may last longer. Narrow the broad tailnet grant,
then add an explicit `svc:homelab-private-ingress` TCP 443 grant for intended
test and production clients with positive and negative policy tests before DNS
cutover. November 1
read-only checks found the Terragrunt OAuth credential lacks Services write
(403), and the SSM-backed operator credential returned 401 at token exchange;
resolve a repo-owned credential path before activation. Confirm the connected
Tailscale v1.40 NAS is not an ingress consumer or upgrade it. Preserve the old
internal Service until the replacements work. `loadBalancerClass` cannot be
changed in place; create a distinct internal Service before retiring the old
one. Prove
these contracts, persistent sidecar
identity, a canary-only tailnet tag, Tailnet Lock, same-node/remote-node
Pod-IP HTTP/HTTPS and tailnet-IP negative probes, native clients, and
[legacy-route retirement](../../scripts/ci/legacy-ingress-retirement-check.py)
before cutover, while preserving named Octelium control paths. The 18 legacy
app routes still have 54 source entries. The
existing-node evacuation below remains a separate general `NetworkPolicy`
canary candidate, not a prerequisite for the sidecar test.

The [dormant sidecar source](../../clusters/homelab/apps/traefik/canary/README.md)
renders independently and is absent from the live Traefik Argo source. It has
distinct Pod and Service labels, route ConfigMap, and ServiceAccount. Its
first raw TCP Serve exposes only tailnet 443. The current broad grant reaches
every signed device regardless of tag; narrow it and prove the applied policy
denies every canary client before using the `--canary-only` signer. Add a test
client grant after signing. Port 80 needs separate review. The
Tailscale container alone receives its projected API token and file-backed auth
key. Tailscale creates its mutable state Secret; Argo does not reconcile it.
Backend Istio identity, Tailnet Lock signing, capacity, and negative-path probes
remain activation gates. The November 1
read-only capacity recheck found only about 580 MiB sampled peak headroom on
`zimaboard-1`, below the canary's 768 MiB memory limit. `acer` had about
3,164 MiB before that limit and about 2,396 MiB after it; remeasure before
registration, preserve its control-plane reserve, and prove image pull and
admission there.

The November 1 existing-node recheck found `zimaboard-2` at 1,339 MiB used
against 1,308 MiB allocatable before the 576 MiB enforcer/client limit budget
and 128 MiB reserve. It cannot host the staged canary. `zimaboard-0` is only
a conditional candidate: 64 active app Pods remain, including 55 Octelium
Pods, plus 19 completed backup Pods and the `kube-system/image-rewrite`
Deployment Pod. The admission code rejects all 84 foreign assigned Pods,
including completed Jobs and ordinary Pods in system namespaces. Deluge,
Radarr, Sonarr, and Bazarr config PVs are locally pinned.
Its 1,430 MiB observed free memory leaves about 214 MiB after one enforcer,
client, Traefik Pod, and reserve; the current Traefik surge exceeds that
headroom. [The runbook](../../docs/runtime-isolation.md#networkpolicy-canary-on-an-existing-node-2026-11-01)
records the conditional maintenance route: verify local-volume archives;
pause Prometheus and four media apps through GitOps, including Bazarr's
z0-pinned PostSync Jobs; make seven backup CronJobs discard successful Job
history and pause the four media schedules; move
Prowlarr and Octelium placement through their source owners; then use a
Terragrunt-owned temporary `NoExecute` taint to clear remaining Pods before
protected admission. Restore the missing `homelab-plan` required reviewer
before its credentialed plan or apply. The five paused workloads remove about 2,512
MiB in requests, closing a 681 MiB destination deficit. Prove Octelium's
native/Multus path on `acer` before eviction and all replacement health after.
This route incurs monitoring and media outages plus an Octelium/private-app
interruption during eviction. A persistent guard must deny
Traefik Pod traffic before container start and through enforcer restart,
independently of kube-router; no such guard is implemented. Cold boot,
image-cache miss, IP reuse, and legacy ClusterIP bypass tests remain required.
PRs #1583 and #1584 targeted `zimaboard-2` and were closed as superseded by
the z0 route; neither changed live state. No worker is admitted.
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
receipt and exact Node and system Pod identities. It checks that the enforcer,
cleanup Pods, and fixture traffic are absent, then adds the dedicated
`NoSchedule` taint before the selector label. A complete cluster-wide label
inventory must exclude every other selected Node before mutation and just
before labeling; a conflicting post-patch read removes its own label and keeps
the taint. After a qualifying traffic probe, exact reviewed GitOps commits
prune the fixtures and then the enforcer. Unrelated commits may land before,
between, or after these two dedicated commits. The protected stage walks full
first-parent history from the qualify SHA and rejects intervening policy
runtime-source changes under the guarded operational roots or Nix flake
inputs. The static gate accepts only five exact policy/canary source
phases; private receipts and live checks still gate protected operations.
Apply the fixture prune and verify
the live `network-policy-canary` namespace and all fixture workloads are absent
before ownership capture. The owner reviews the private full firewall snapshot
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
