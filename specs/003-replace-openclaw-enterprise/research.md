# Research: Fresh OpenClaw Enterprise Replacement

Date: 2026-10-17, America/Los_Angeles. Homelab source:
`4a4c697423ee2b22f62b3582a1e7d3e32f11c2f4`. Research used parallel platform,
Enterprise, and legacy-state inspection. No production mutation occurred.

## R1 — Replace fresh, retain recovery

**Decision:** Follow the owner's clarification in [spec.md](spec.md): retire the
standalone runtime and install stock Enterprise with a fresh Embedded OpenClaw
agent. Preserve old state as private recovery material; do not migrate behavior.

**Rationale:** At inspected upstream `6385c0c`, Embedded rejects enabled channels,
Discord is unsupported, and generated public-model egress excludes private
LiteLLM. Current `33bb74590a749f37934da4502fca6035cd234a55` adds an upgrade preflight,
not compatibility for those integrations. Their removal is now accepted scope.

**Alternatives considered:** A maintained controller/runtime fork would require
channel admission, credential projection, network generation, storage mapping,
and provisioning changes. Rejected after the owner's fresh-install direction.
A console-only installation is staging, not completed assistant replacement.

Sources: [channel admission](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/apps/controller/src/drivers/compute/kubernetes/configuration-rules.ts),
[network boundary](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/reference/drivers/kubernetes-compute/networking-and-isolation.md),
[current legacy runbook](../../clusters/homelab/apps/openclaw/README.md).

## R2 — Upgrade supported platform branches in separate stages

**Decision:** Research targets are Talos 1.14.4, Kubernetes 1.35.9, and Istio
1.30.6. Revalidate advisories and immutable image digests before implementation.
Keep Flannel, Multus, kube-proxy, existing API endpoint, and storage ownership.

**Rationale:** Enterprise requires Kubernetes 1.35+. Talos 1.11 does not support
it; 1.12/1.13 are no longer community-supported. Istio 1.27 is unsupported and
its published matrix excludes even the currently running Kubernetes 1.34.
Istio 1.30 is the shortest currently supported branch spanning 1.34 and 1.35.

**Ordered stages:**

1. Talos `1.11.3 -> 1.11.6 -> 1.12.12 -> 1.13.11 -> 1.14.4`, retaining
   Kubernetes 1.34. Verify every adjacent-hop release requirement.
2. Istio `1.27.3 -> 1.28.10 -> 1.29.9 -> 1.30.6`, retaining Kubernetes 1.34.
   No 1.27.9 hop is required: its Gateway API fix concerns higher-version CRDs,
   none are installed, and the 1.28 upgrade notes do not require that patch.
   For each minor, upgrade base/CRDs, istiod, CNI, ztunnel, then gateways.
3. Kubernetes `1.34.11 -> 1.35.9` through Talos's ordered upgrade operation;
   never apply version-image patches directly or promise a supported downgrade.

Talos 1.14.4's `upgrade-k8s` appends `:v<target>` to each component image-base
flag ([upstream source](https://github.com/siderolabs/talos/blob/v1.14.4/pkg/cluster/kubernetes/talos_managed.go#L170-L175)). Passing a
`tag@sha256` reference to those flags would create an invalid reference. The
maintenance helper therefore accepts only image bases whose generated target
tags have exact digest-pinned entries in the reviewed Harbor catalog; the
protected publication receipt must verify those tags before upgrade.

Talos 1.14 uses the image factory's `metal-installer` path. Preserve the verified
machine schematic, extensions, disk identity, and authenticated client access.
The current repository has no version-upgrade helper/workflow; create a narrow
maintenance lane before any node changes. Existing mirror helpers are not that lane.
The existing `talos-api.homelab` Octelium TCP policy allows only the owner's
human session ([service policy](../../docs/examples/octelium/homelab-services.yaml));
the protected CI workload has no Talos transport yet. The maintenance workflow
must declare and validate a scoped CI route with authenticated Talos mTLS, while
retaining the direct LAN recovery path, before any upgrade stage is enabled.

Read-only authenticated inspection on 2026-10-17 returned no
`extensionstatus` resources on any of the four nodes. The selected Talos 1.14
empty schematic is
`376567988ad370138ad8b2698212367b8edcb69b5fd68c80be1f2ec7d603b4ba`;
the Image Factory OCI index for v1.14.4 resolved to
`sha256:ac4159f8c36dabd29ea65a8dfe500ed8ef5840711c363a28c18dd0de191e6d02`.
Installer, Istio and Kubernetes target references were resolved through their
registries into `scripts/config/platform-maintenance.json`. This is discovery,
not a Harbor publication receipt or proof that a node upgrade is safe. Recheck
extension and schematic identity before each live hop.

**Alternatives considered:** Stopping at Talos 1.12 or Istio 1.29 minimizes hops
but leaves unsupported branches; upgrading Kubernetes beyond 1.35 adds no value
for this feature. Replacing the CNI is unnecessary if policy-only enforcement passes.

Sources: [Talos support](https://docs.siderolabs.com/talos/v1.14/getting-started/support-matrix),
[Talos upgrades](https://docs.siderolabs.com/talos/v1.14/configure-your-talos-cluster/lifecycle-management/upgrading-talos),
[Talos Image Factory](https://factory.talos.dev/),
[Talos releases](https://github.com/siderolabs/talos/releases),
[Kubernetes 1.35.9](https://github.com/kubernetes/kubernetes/releases/tag/v1.35.9),
[Istio support](https://istio.io/latest/docs/releases/supported-releases/),
[Istio 1.27.9 change](https://istio.io/latest/news/releases/1.27.x/announcing-1.27.9/),
[Istio 1.28 upgrade notes](https://istio.io/latest/news/releases/1.28.x/announcing-1.28/upgrade-notes/),
[ambient upgrades](https://istio.io/latest/docs/ambient/upgrade/helm/).

## R3 — Use firewall-only kube-router, qualify it on Talos

**Decision:** Select kube-router v2.11.1's iptables NetworkPolicy implementation.
Enable firewall and Pod-startup default-deny; disable routing, service proxy,
load balancing, CNI management, experimental native nftables, and IPv6.
Do not enable the existing source-only NRI fragment for this feature.

**Rationale:** Official Talos documentation covers kube-router. The pinned release
has startup and restart isolation tests and retains rules on graceful shutdown.
This avoids replacing Flannel's CNI or kube-proxy. It is a candidate requiring
real combined-stack qualification, not proof of deployment compatibility.

`--netpol-default-deny` is a startup guard until per-Pod chains exist. Pods with
no selecting policy retain normal Kubernetes allow-by-default behavior afterward.
Do not confuse this flag with a permanent cluster-wide deny policy.

Strip the upstream example's CNI installer, CNI ConfigMap/environment settings,
and CNI host mounts. Its firewall-only example still includes CNI-writing setup.
Keep only necessary host networking/firewall privilege and in-cluster read/watch
RBAC. Test the image's iptables compatibility frontend against existing host rules.

**Alternatives considered:** The repo's SIG Network enforcer v1.1.2 deletes rules
on graceful shutdown and does not establish the required first-packet/lifecycle
proof. Treat it as ineligible here. Calico/Canal changes CNI ownership; Cilium
would broaden the migration further. Neither is the initial implementation.

**Required evidence:** Audit ingress and egress for every affected policy;
prove positive/negative traffic, enforcer restart/crash, API interruption,
new-Pod startup, IP reuse, rescheduling, and node reboot. Test IPv6 absence.
Host-network, privileged, VPN, and Multus secondary interfaces are separate
control paths; ordinary NetworkPolicy does not prove their isolation.

Sources: [Talos kube-router](https://docs.siderolabs.com/kubernetes-guides/cni/kube-router),
[pinned options](https://github.com/cloudnativelabs/kube-router/blob/v2.11.1/docs/user-guide.md),
[startup tests](https://github.com/cloudnativelabs/kube-router/blob/v2.11.1/test/e2e/netpol/default_deny_test.go),
[restart tests](https://github.com/cloudnativelabs/kube-router/blob/v2.11.1/test/e2e/netpol/restart_test.go),
[rejected enforcer shutdown](https://github.com/kubernetes-sigs/kube-network-policies/blob/v1.1.2/pkg/dataplane/controller.go#L324-L347),
[existing egress contract](../../docs/image-egress-hardening.md).

## R4 — Capacity is a real execution gate

Read-only live evidence on 2026-10-17: all four amd64 nodes Ready, Kubernetes
1.34.11, Talos 1.11.3, kernel 6.12.52-talos, containerd 2.1.4. Flannel 0.27.4,
Istio CNI/ztunnel 1.27.3, and Multus 4.3.0 were each 4/4. No enforcing DaemonSet
or tainted canary existed. There were 61 NetworkPolicies in 16 namespaces.

| Node | Unreserved CPU | Unreserved RAM | Actual RAM used |
| --- | ---: | ---: | ---: |
| acer | 2814m | 1545Mi | 68% |
| zimaboard-0 | 149m | 69Mi | 83% |
| zimaboard-1 | 1768m | 2694Mi | 79% |
| zimaboard-2 | 1040m | 102Mi | 81% |

**Decision:** Require a reviewed per-node placement/reservation report before
execution. Archive and stop old OpenClaw early if needed to reclaim only its
own resources; remeasure afterward. That can remove its declared 1 CPU/2Gi app
request, but does not solve the other workers' enforcer footprint or create a
safely isolated canary automatically.

Initial planning reservation: API and worker 512Mi each, database 512Mi,
Envoy controller/proxy combined 768Mi, embedded gateway 1792Mi; about 4Gi plus
startup/backup jobs, enforcement, and system headroom. These are proposed
reservations to test, not measured requirements or permission to overcommit.
Upstream gateway limit is 3Gi; test bursts and memory growth before acceptance.

Read-only refresh on 2026-10-17 evening PDT: all four nodes still report Talos
1.11.3 and Kubernetes 1.34.11; Istiod, CNI and ztunnel still run 1.27.3. Flannel,
Istio CNI, ztunnel and Multus remain 4/4. All nodes have no taint. There are still
61 NetworkPolicies in 16 namespaces and no Gateway API CRDs. The legacy `ai`
namespace retains one NFS and three local bound OpenClaw PVCs. Current `top nodes`
memory use is acer 67%, zimaboard-0 84%, zimaboard-1 84%, zimaboard-2 80%.
This refresh does not satisfy T022's post-shutdown reservation/canary admission.

**Alternatives considered:** Running old/new simultaneously is unnecessary after
the fresh-install clarification. Lowering requests to hide the deficit, moving
unrelated workloads, or assuming new hardware is not authorized by this plan.
Failure to obtain an isolated canary or sufficient measured headroom blocks rollout.

## R5 — Stock deployment with repository-owned lifecycle hooks

**Decision:** Pin controller, runtime, CLI, source chart, and initialization
artifacts to upstream `33bb74590a749f37934da4502fca6035cd234a55` and matching build
provenance. Mirror immutable digests through Harbor before use. Chart source
version `0.1.0` does not prove a published OCI package exists; use the pinned
upstream Git chart path. Do not build a behavior fork.

Use the shared Terragrunt Application registration and a narrowly scoped OCE
AppProject. Add repository-owned lifecycle hooks around the stock chart to
check candidate compatibility, stop existing writers, and gate initialization.
Do not assume Helm pre-upgrade hooks or Argo rendering stop old API/worker Pods.
A failed lifecycle hook must prevent normal Deployment synchronization/resume.

**Rationale:** Stock installation supports the new scope; ordinary GitOps ownership
preserves reproducibility. Upgrade safety still requires repository orchestration.

**Alternatives considered:** Manual Helm installation or console-only bootstrap
would bypass the declared setup path. Copying the chart or patching controller
behavior is unnecessary. A bare auto-sync chart without writer fencing is unsafe.

Sources: [chart](https://github.com/openclaw/openclaw-enterprise/tree/33bb74590a749f37934da4502fca6035cd234a55/deploy/helm/openclaw-enterprise),
[image pairing](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/guides/deploy/published-images.md),
[upgrade process](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/guides/deploy/production-upgrade.md).

## R6 — Dedicated state, fresh model configuration, private access

**Decision:** Dedicated PostgreSQL 18.6 with verified TLS, distinct `occ_app` and
`occ_migrator` roles, and separate administrator credentials. Keep bootstrap output,
auth secret, gateway CA/key, tenant metadata/secrets, and agent volumes in recovery
scope. Use SQLite-compatible local storage for the OCE-owned 10Gi RWO agent claim;
the default NFS StorageClass is not suitable for its authoritative SQLite state.

Use native IAM/password login and one fresh Embedded OpenClaw agent. No channels,
repository broker, optional collector, Slack proxy, Backend, or Codex Harness.
Use OpenRouter's `openrouter/free` model through the pinned OCE driver's
supported `openai` provider, `openai-completions` API and
`https://openrouter.ai/api/v1` base URL. OCE's model reference is
`openai/openrouter/free`; the upstream wire model remains `openrouter/free`.
Direct `openrouter/free` as an OCE reference is rejected by the
[pinned Kubernetes driver](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/apps/controller/src/drivers/compute/kubernetes/index.ts#L2267-L2275), while its
[conformance test](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/tests/conformance/kubernetes-compute.test.mjs#L8248-L8255) accepts nested model IDs under `openai`.
[OpenRouter's free-router contract](https://openrouter.ai/docs/guides/routing/routers/free-router) uses `openrouter/free` on the wire.
A dedicated OpenRouter key must be supplied through Agent `harnessAuth` before
inference; do not adopt the example model or reuse LiteLLM/old assistant
credentials. A real model probe is an inference action, not a read-only readiness test.

Use `console.oce.stinkyboi.com` and returned per-agent origins under
`agents.oce.stinkyboi.com`, cookie scope `oce.stinkyboi.com`. Keep both behind
Octelium and route them to OCE API. OCE authorizes the exact agent and forwards
through private Envoy to its gateway. Never expose private Envoy directly.
Keep `openclaw.stinkyboi.com` as an authenticated redirect.

Stock egress permits public TCP/443 and excludes private ranges. This feature
proves the stock boundary; it does not claim domain-level internet filtering or
preserve gateway-only attribution. Keep OCE namespaces outside ambient mesh
initially and test the required private routing and policy paths explicitly.

**Alternatives considered:** Shared unrelated databases, old credential reuse,
public management ingress, a domain-wide session cookie, or NFS-backed active
SQLite weaken ownership or isolation. Requiring custom legacy integrations
contradicts the owner's clarified scope.

Sources: [database roles](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/reference/settings/operations.md),
[storage](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/reference/drivers/kubernetes-compute/storage-and-credentials.md),
[native admin](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/guides/deploy/native-admin.md),
[workspace routing](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/guides/deploy/workspace-routing.md).

## R7 — Reconcile through supported interfaces; retain independent archives

**Decision:** One serialized repository reconciler uses supported OCE API calls
and a protected journal mapping the logical installation/agent/configuration to
server IDs. Use exact generation checks for updates; recover unknown outcomes
before retrying creation/deployment. Embedded does not support the dedicated
provision endpoint's idempotency protocol.

Legacy recovery must cover both local databases and NAS content. Existing
`openclaw-assistant-check.py`, `openclaw-runtime-storage-check.py`, and
`openclaw-github-check.cjs` passed during research; these prove existing helpers,
not a full restore or Enterprise behavior. Retain the old full archives and
`pre-2026.9.2-runtime` checkpoint. No state import into Enterprise is planned.

**Alternatives considered:** A new generalized provisioning controller adds
unnecessary infrastructure. Blind create retries can duplicate resources.
Keeping only daily database snapshots loses workspace and configuration coverage.

Source: [OCE API](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/reference/api.md),
[legacy recovery contract](../../clusters/homelab/apps/openclaw/README.md#durable-runtime-state-and-recovery).

## R8 — Shared Gateway API ownership and supported private Envoy

**Decision:** Use Envoy Gateway/chart/Envoy CRDs v1.9.2, Gateway API v1.6.1
experimental, and Harbor-mirrored Envoy Proxy `distroless-v1.39.3`. The platform
Envoy Application owns the shared CRDs once; Enterprise consumes them.

**Rationale:** Envoy Gateway 1.9 supports Kubernetes 1.35 and remains supported
through February 14, 2027. Its 1.6 example is already unsupported and excludes
Kubernetes 1.35. The selected proxy patch fixes security issues including an
API-key-filter crash relevant to OCE routing. OCE attaches an EnvoyProxy without
merge semantics; its image must be pinned on that resource, not only in global
Helm defaults. Keep the source chart unchanged and override that one object in
the last local Argo source, preserving its rendered fields except the image.

Read-only inspection found no installed Gateway API CRDs. Istio 1.30.6 still
watches TCPRoute/UDPRoute `v1alpha2` and ReferenceGrant `v1beta1`; the experimental
1.6.1 bundle retains those alongside current APIs. Test both controllers after
installation and reject unexpected served/storage-version removal in later upgrades.

**Alternatives considered:** Envoy 1.6 lacks the required supported platform
combination. The 1.6.1 standard Gateway API bundle removes route versions Istio
still watches. Separate controller-owned copies of shared CRDs risk conflicting
updates; a controller/runtime fork is unnecessary for a deployment image pin.

Sources: [Envoy compatibility](https://gateway.envoyproxy.io/news/releases/matrix/),
[1.9.2 security and image override](https://gateway.envoyproxy.io/news/releases/notes/v1.9.2/),
[separate CRD installation](https://gateway.envoyproxy.io/v1.9/install/install-helm/),
[Istio watched APIs](https://github.com/istio/istio/blob/1.30.6/pkg/config/schema/kubeclient/resources.gen.go),
[experimental TCPRoute versions](https://github.com/kubernetes-sigs/gateway-api/blob/v1.6.1/config/crd/experimental/gateway.networking.k8s.io_tcproutes.yaml),
[experimental ReferenceGrant versions](https://github.com/kubernetes-sigs/gateway-api/blob/v1.6.1/config/crd/experimental/gateway.networking.k8s.io_referencegrants.yaml),
[OCE routing template](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/deploy/helm/openclaw-enterprise/templates/gateway-routing.yaml),
[Argo source precedence](https://argo-cd.readthedocs.io/en/stable/user-guide/multiple_sources/).

## Research disposition

Product-scope questions are resolved by the owner's clarification. No technical
selection remains unspecified. Execution gates remain: capacity/canary allocation,
immutable artifact receipts, actual platform compatibility and isolation tests,
the dedicated OpenRouter key, full restores, and real browser/inference acceptance.
These must fail closed during implementation; this document does not mark them passed.
