---
type: runbook
title: "Runtime Isolation"
description: "Current Pod Security and Istio boundaries, plus dormant firewall-only kube-router NetworkPolicy prerequisites and canary gates."
tags: ["runbook", "security", "kubernetes"]
sources:
  - id: openwiki-source-225c4d98c899575724fbc37b
    resource: repo://.github/workflows/policy-generator-images.yml
  - id: openwiki-source-77506acd031f0c0e800c4c2a
    resource: repo://builds/network-policy-generators/cordium-v0.12.7.patch
  - id: openwiki-source-1b8e7ecff7f3e3abcd292cd7
    resource: repo://builds/network-policy-generators/octelium-v0.35.0.patch
  - id: openwiki-source-c73e1fecbb517a520b6d8a37
    resource: repo://builds/network-policy-generators/README.md
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
  - id: openwiki-source-d8dda331a329c9404cfb41cb
    resource: repo://scripts/octelium-cluster-bootstrap.sh
  - id: openwiki-source-aa83e90c74e65ee6187dbbb5
    resource: repo://specs/003-replace-openclaw-enterprise/research.md
generated: { by: "codex", at: "2026-10-28T02:01:41.290Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-28T02:01:41.290Z
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

Historical protected [214-image run `40011909180`](https://github.com/Stuhlmuller/homelab/actions/runs/40011909180)
and [215-image run `40172274517`](https://github.com/Stuhlmuller/homelab/actions/runs/40172274517)
passed publication and authenticated Harbor pulls. Recheck the strict
publication bundle against current `main` before accepting T004.
Before activation, finish policy owner/render review, then admit an isolated
tainted canary with measured capacity and local-storage
placement. No worker has an accepted current canary placement; later
outage-affected rescheduling invalidates earlier request arithmetic as admission
evidence. The [2026-10-27 post-recovery recheck](../../docs/evidence/openclaw-enterprise-acceptance.md)
found 2,895 MiB unreserved on `acer`, 1,201 MiB short of the initial 4,096 MiB
Enterprise request budget. Other workers lacked a safe memory and local-storage
split; `zimaboard-2` still hosted unrelated Pods. Pausing Langfuse and
Dispatcharr would fit request arithmetic but lacks complete independent
whole-service restores, measured peak/restart margin, and isolated-canary
proof. No service was paused or canary admitted. A `NoSchedule` taint leaves
existing Pods in place and is not an isolation proof. T022, T027 and T035
remain open; enforcement remains disabled.
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
pinned generator-binary renders remain unverified. The pinned upstream
`ws-main` and `svc-upstream` constructors hardcode all-port public IPv4 and
IPv6 egress without a public-egress input; additive NetworkPolicies cannot
narrow those allows.
[Staged source patches](../../builds/network-policy-generators/README.md)
remove those two rules. Run
`python3 builds/network-policy-generators/verify-source.py` to check exact
upstream revisions, patch hashes, licenses, application, and targeted Go tests.
This is source-only: no corrected image is published or deployed. The staged
[publisher](../../.github/workflows/policy-generator-images.yml)
can build and publish three patched images from exact current `main`, then
require authenticated Harbor pulls and signature verification before emitting
digests. It has not run, so no accepted digests or deployed consumers exist.
The [Octelium wrapper](../../scripts/octelium-cluster-bootstrap.sh) now reads
its reviewed Genesis image pin, currently `null`. Without a pin it refuses an
installed or unreadable network-policy enforcer before prerequisite waits and
at octops invocation. With a reviewed tagless Harbor digest, it checks both
installed octops commands for `--genesis-image` and forwards the pin before
writes. It still has no reviewed path to install a patched octops binary from
its authenticated and signed image. Its help check is not binary provenance.
Current live policies and expected-spec fixtures retain the broad rules.
Publish and pin reviewed images, install the patched binary, compare complete
actual generator renders, and qualify owner destinations plus private-range
denial on an isolated canary before enforcement.

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
