# Staged network enforcement (HOME-3)

<!-- markdownlint-disable MD013 MD060 -->

This is an **unregistered rollout candidate, not proof of live isolation**.
Source was checked against main `32dc911c8f86638ae2e2012afbe7f80c4d3f17b3`
on 2026-09-29. No live Kubernetes/Talos access was available in the implementation
workspace. The last documented dataplane audit found Flannel without an engine;
that is historical evidence, not a fresh live observation. Existing operator-managed
policy enforcement is unknown. Do not install a second engine before checking.

The candidate is `clusters/homelab/platform/network-isolation-candidate/`.
It is excluded from the Terragrunt stack and all active Kustomizations. Its three
Argo Applications have no automated sync. Merging this candidate does not install
it. OpenClaw sandbox mode stays off: no supported sandbox backend has been added.

## Compatibility decision

| Component | Source evidence | Activation check |
| --- | --- | --- |
| Talos | Last documented 1.11.3; Flannel remains Talos-owned | Authenticated node version, kernel modules and bridge netfilter support on every node |
| Kubernetes | Declared patch 1.34.11 | All node versions, Ready status, Pod/Service CIDRs and kube-proxy mode |
| Flannel | Connectivity owned outside this candidate | Actual DaemonSet image, interface/backend, iptables backend; do not infer image from Talos test fixtures |
| Multus | Repo pins 4.3.0 thick daemon, connectionLimit 4 | Primary-network order and delegated attachments; no secondary interface on protected workloads |
| Istio | Repo charts 1.27.3, ambient, IPv4, DNS capture off | Exact rendered/live chart ports, enrollment, ztunnel health and source principals |
| kube-router | Candidate 2.11.1, digest pinned | Kernel/ipset/iptables compatibility and measured capacity under this exact combination |

[kube-router supports a standalone firewall controller](https://www.kube-router.io/docs/user-guide/).
The candidate disables routing, Service proxy, load balancing and CNI installation.
It writes no CNI config and mounts neither `/etc/cni/net.d` nor `/opt/cni`.
Its read-only Kubernetes RBAC and privileged host-network daemon are dedicated to
policy enforcement. There is no BGP, IPAM, Flannel, Multus or kube-proxy replacement.
The pinned version's `--enable-cni=false` option is checked in
[its source](https://github.com/cloudnativelabs/kube-router/blob/v2.11.1/pkg/options/options.go).
This is the smallest **candidate**, not an upstream certification of this Talos stack.

Alternatives considered:

- [Calico with Flannel](https://docs.tigera.io/calico/latest/getting-started/kubernetes/flannel/install-for-flannel)
  is a documented policy/connectivity split, but its Canal installation also owns
  networking manifests; adapting it to Talos ownership and Multus needs more changes.
- [Cilium chaining](https://docs.cilium.io/en/stable/installation/cni-chaining/)
  can retain the primary CNI while attaching enforcement, but changes the CNI chain
  and needs endpoint replacement/compatibility tests. A complete CNI replacement
  is not justified by the source evidence here.
- Newer [Flannel Helm charts](https://github.com/flannel-io/flannel#network-policy)
  can install a separate policy controller. This cluster uses Talos-managed Flannel,
  not that chart; changing its owner is not the smallest first step.

No claim is made that current Istio 1.27.3 remains upstream-supported. An upgrade
is separate from this enforcement candidate. Before activation, validate the
pinned stack and decide whether version maintenance must precede it.

## Additive policy inventory and staging

`policy-inventory.json` captures every NetworkPolicy in non-candidate source YAML,
including policies embedded in other filenames. The focused test fails on source
policy drift. It is not the complete live inventory: chart-generated, unmanaged,
suspended and unrendered resources must be reconciled before activation.

| Namespace/group | Existing intent | Activation risk |
| --- | --- | --- |
| affine | Server/gateway; database/cache from app | Missing HBONE and direct Octelium allowances |
| ai | OpenClaw ingress; Multica runtime deny ingress; Multica DB isolation | Ambient TCP/15008; runtime currently has unrestricted egress |
| automation | n8n DB; Policy Bot callbacks | Ambient and operator callback paths |
| cordium | Genesis private API; config HTTPS; sysctl deny all | Privileged workspaces and Multus are outside this boundary |
| harbor | Default deny ingress; component/store/bootstrap; signing DNS/gateway | Registry authentication, backup clients, readiness, exporter paths |
| langfuse | App/store ingress plus TCP/15008 | Chart worker/store selectors and actual enrollment |
| media | PostgreSQL clients; local restore/backup/directory Jobs deny all | NFS is mounted by nodes, not governed by Pod egress |
| nofx | Frontend/backend ingress; backend allows all egress | Does not establish agent containment |
| octelium-public | Tunnel public HTTPS/7844; private gateway and DNS | Essential operator ingress must survive |
| octelium-storage | Octelium and backup-to-store ingress; default deny | HOME-2 capture/publication paths |
| octelium-client | Demo client/service proxy ingress | Multus/TUN traffic and source NAT |

`policies/compatibility.yaml` temporarily grants both directions for the existing
policy-bearing namespaces, **excluding** OpenClaw, Multica runtime, signing, and
selected existing no-network Jobs. This preserves the previously permissive L3/L4
state while the engine starts; it does not remove or weaken Istio authorization.
It intentionally means most legacy NetworkPolicies are **not yet restrictive**.
Retire these compatibility grants namespace by namespace in reviewed follow-ups,
after the table's dependencies pass. Do not describe them as default-deny isolation.
They do not cover future namespaces or unexpected chart policies: any live/source
diff is an activation blocker until audited.

[Kubernetes policies are additive](https://kubernetes.io/docs/concepts/services-networking/network-policies/).
A new broad allow selecting a protected Pod defeats its egress restriction. Check
both live policy selection and chart renders; checking one file is insufficient.
The offline fixtures evaluate the union and include a rollback-allow regression
that deliberately demonstrates this failure mode.

## Protected workload contracts

NetworkPolicy selects namespace and labels, not service accounts. Keep the latter
exact for Istio tests and audit RBAC that can change labels, workload specs or
policies. None of these controls contain a cluster administrator or node compromise.

| Source identity | Allowed egress | Explicit residual trust |
| --- | --- | --- |
| `ai/openclaw`, label `app.kubernetes.io/name=openclaw` | CoreDNS TCP/UDP 53; `ai/litellm` TCP 4000/15008; `monitoring/grafana` TCP 3000/15008; public IPv4 TCP 443 | Web search, GitHub release/bootstrap/App API, Nix/package downloads over HTTPS, Discord, Google OAuth, OpenRouter and ChatGPT/Codex use changing endpoints. Arbitrary public HTTPS remains possible, including exfiltration. Plain HTTP, private/tailnet/link-local ranges and other public ports are excluded. |
| `ai/multica-runtime`, same-name app label | CoreDNS TCP/UDP 53; exact Multica backend labels TCP 8080/15008; public IPv4 TCP 443 | GitHub/bootstrap, Codex/provider and connector traffic share the HTTPS exception; no direct LAN/admin API access intended. |
| `harbor/harbor`, label `app.kubernetes.io/name=harbor-image-signing`, part-of `harbor` | CoreDNS TCP/UDP 53; only `istio-system` Pods labeled `app=istio-ingressgateway`, TCP 443 | Shared resolver can carry DNS exfiltration; shared gateway serves more than Harbor and Harbor itself is a permitted data sink. This is destination/port containment, not guaranteed key-exfiltration prevention. |
| Synthetic recovery probe, dedicated restricted non-mesh namespace, no SA token | No declared ingress/egress, including DNS | Local-node traffic and implementation convergence remain exceptions; NOT approved for real archives. |

Keep the HTTPS exception visible until provider/connector traffic can be moved
behind a tested mandatory application proxy. An L3/L4 allowlist cannot enforce
FQDN restrictions. Do not silently add `0.0.0.0/0` for signing, broad HBONE to all
namespaces, all private networks, Kubernetes API, SSH, SMTP or DNS-over-TLS.
CoreDNS itself is trusted to resolve arbitrary names, so the signing boundary
still needs a dedicated fixed-destination resolver/gateway or offline key custody
if stronger exfiltration protection is required.

HBONE TCP/15008 is necessary for [ambient NetworkPolicy interoperability](https://istio.io/v1.27/docs/ambient/usage/networkpolicy/).
OpenClaw ingress retains its existing allowed namespaces and gains HBONE only from
those namespaces. Egress HBONE is restricted to the same allowed destination Pods;
Istio remains responsible for authenticated service-account authorization. This
must be tested for Pod IP, Service IP, DNS, same-node and cross-node paths.

The pinned gateway chart was rendered locally: Service 443 maps to Pod 443 and
uses `app=istio-ingressgateway`. Do **not** copy an older chart's 8443 assumption.
CoreDNS already rewrites `harbor.stinkyboi.com` to this Service. Keep TLS hostname
verification and registry authentication; no public-route fallback is allowed for
signing. Cosign uses a local key with transparency-log upload and ambient OIDC
disabled; exercise a synthetic key/registry project before production signing.

HOME-2 PR #1113 introduces candidate backup publication contracts outside this
network path. Publication requires its own approved egress; archive parsers must
never share its credentials or network. HOME-4 scraping/heartbeat dependencies and
open PR #1114's proposed Multica-to-LiteLLM route require revalidation before phase
one. This candidate grants Multica only the dependencies present in checked main;
merge newer agent routes into the inventory, policies and tests together.
No shared storage, alerting or active IaC resources are changed here.

## Reviewable rollout

Every phase below requires approval of its concrete commit, nodes, privileged
RBAC/DaemonSet and effect. No current issue assignment approves execution.

1. From existing authorized access, collect a private snapshot:

   ```sh
   python3 scripts/network-isolation-probe.py snapshot --output /private/isolation-inventory.json
   kubectl get nodes -o wide
   kubectl get daemonsets -A -o wide
   kubectl get networkpolicies -A -o yaml
   kubectl get endpointslices -A -o wide
   ```

   Reconcile all rendered/live policies with the inventory. Confirm Talos/kernel,
   actual Flannel/kube-proxy/Multus images, bridge filtering, iptables backend,
   ipset support, DNS path and node capacity. Confirm no enforcing engine already
   exists. Verify IPv4-only Pod and Service CIDRs **and no usable IPv6 egress**;
   the candidate explicitly disables IPv6. If dual-stack/routed IPv6 exists,
   stop and add a reviewed dual-family configuration and matrix. Never mark IPv6
   passed from a missing AAAA record or a socket error alone.

2. Check an independent operator path: authenticated Talos plus an existing
   Kubernetes/Argo endpoint outside the affected app ingress. Preserve both.
   Test Octelium login/private API/public callbacks and existing Istio denials
   before and throughout rollout. Confirm node load can tolerate 128Mi requested,
   512Mi capped per engine Pod; these are starting budgets, not measurements.
   Do not schedule this while nodes or the ingress control path are unhealthy.

3. On the exact approved clean main, render/test; commit a completed, non-secret
   probe matrix with actual healthy listener endpoints before executing it:

   ```sh
   nix develop --command python3 -I scripts/ci/network-isolation-test.py
   nix develop --command kustomize build clusters/homelab/platform/network-isolation-candidate/policies
   nix develop --command kustomize build clusters/homelab/platform/network-isolation-candidate/engine
   nix develop --command python3 -I scripts/network-isolation-rollout.py policies
   ```

   The rollout helper previews by default. Following explicit approval, use
   `policies --approved-commit <SHA> --execute` and then separately approved
   `engine --approved-commit <SHA> --execute`. The helper verifies clean local
   HEAD equals remote main and requires the policy app Healthy/Synced at that
   revision before engine activation. It registers only the selected repo-owned
   Argo Application, then syncs the approved SHA explicitly using
   [Argo's revision option](https://argo-cd.readthedocs.io/en/stable/user-guide/commands/argocd_app_sync/).
   No automated sync or prune is enabled.
   Engine activation changes host rules on **all Linux nodes**, not just agents;
   `maxUnavailable: 1` controls updates, not first-install blast radius.

4. Check `kubectl -n kube-system rollout status daemonset/kube-router-policy`
   and daemon logs without exposing credentials. Require one ready engine per
   node, stable Flannel/Multus/ztunnel, no iptables/ipset errors, no operator or
   backup/monitoring regression, and acceptable CPU/memory. Health alone is not
   evidence of denial. Check counters/packet evidence against fresh connections.

5. Run the synthetic matrix below in two rounds. Then verify real application
   behavior under the exact identities: OpenClaw model response, Discord/Google
   callback, GitHub App auth and cold bootstrap; Multica backend polling/tool
   execution; Grafana and LiteLLM access; Harbor TLS/authentication and synthetic
   signing. Existing protected ingress must still reject unauthorized identities.
   Repeat denied probes during Pod replacement and engine restart as well as
   after convergence; the harness's delayed samples do not prove absence of a
   startup race. Real archives stay prohibited.

Only a human acceptance record containing the exceptions, matrix, versions,
node coverage, application results and rollback exercise can close HOME-3.

## Synthetic probe harness

`scripts/network-isolation-probe.py` never applies resources. `snapshot` is
read-only; `render` writes Jobs plus ConfigMaps for later reviewed GitOps delivery.
Use `scripts/config/network-isolation-matrix.example.json` as the starting matrix.
Unresolved placeholders fail. Choose healthy, approved, disposable listeners for
forbidden Pod/Service tests and verify each LAN/public test endpoint is listening.
The same endpoint must be reachable by an unrestricted control in each round.
Use the example node `local_node` field to record the API-defined local-node
exception while still requiring denial from the other nodes. Every node address
and actual workload node must be covered in the approved matrix.

```sh
python3 scripts/network-isolation-probe.py render \
  --snapshot /private/isolation-inventory.json \
  --matrix /private/reviewed-matrix.json --round first \
  --output /private/probes-first.yaml --plan /private/probe-plan.json
# Render again with --round replacement and a different output filename.
python3 scripts/network-isolation-probe.py verify \
  --plan /private/probe-plan.json --records /private/probe-records.json
```

Review and commit the generated synthetic manifests into a dedicated temporary
Argo app through the usual PR workflow; approval precedes sync. The generated
Jobs run on each node with exact source namespace, service account and labels.
They have no Secrets, PVCs or mounted API tokens and cannot become Ready Service
endpoints. A matching `publishNotReadyAddresses` Service fails rendering.
The unrestricted control namespace is non-mesh and restricted by Pod Security.
There is no `kubectl run`, ephemeral-container injection, or exec into a production
credential-bearing Pod. Pod Security/RBAC admission and source labels still need
server-side dry-run validation before the approved sync.

Collect each Job Pod's single JSON log record using read-only `kubectl logs`,
assemble them as a JSON array, and retain Pod UID, source identity hash, matrix
hash, node and round. The verifier requires both `first` and `replacement`, new
Pod UIDs, all sources/nodes/targets and healthy controls. Socket refusal, rejection
or timeout without a healthy control is not denial evidence. DNS lookup failure
is never accepted as denial; DNS UDP and TCP are explicit request/response tests.
For the no-DNS recovery Pod, hostname cases are observations, with mandatory
literal-address and explicit resolver tests providing the negative evidence.

A passing transport matrix does not prove HTTP authorization, application
functionality, absence of startup races or all future routes. Prune only this
temporary synthetic app after acceptance and export its evidence first. No
retained data is attached or deleted.

## Rollback that preserves access

Stopping/removing a policy engine can leave programmed rules behind. Do not rely
on deleting the DaemonSet, flushing all iptables, or rebooting nodes as rollback.
The repo-owned `rollback/allow.yaml` is an explicit additive allow-all set for the
inventoried namespaces. After separate approval, preview then execute:

```sh
python3 scripts/network-isolation-rollout.py rollback
# Only after approval of the exact clean main SHA:
python3 scripts/network-isolation-rollout.py rollback --approved-commit <SHA> --execute
```

Keep the engine running so it reconciles these rules; check fresh connections,
operator access and app readiness. Stop signing/agent work and prohibit all real
archive processing before this rollback: isolation is intentionally lost.
If the controller cannot reconcile, use the independently verified operator path
and a separately reviewed, engine-specific cleanup change. Generic
`--cleanup-config` can touch routing/proxy rules and is not authorized here.
Do not claim rollback is tested until a synthetic exercise proves it on all nodes.
Retiring the engine and removing emergency allowances is a separate approved
change, with absence of stale rules verified before deleting its RBAC.

## Recovery specialist containment contract

A deny-all Kubernetes NetworkPolicy is **insufficient** for processing sensitive
or hostile archives. Kubernetes allows local-node exceptions, privileged/host
network workloads and implementation-specific behavior; Multus attachments and
Pod startup convergence add other paths. The recovery namespace is for synthetic
network tests only. Do not mount a production PVC, backup object, signing key,
cloud token, kubeconfig or service-account token into it.

Before a real-data drill, HOME-2 needs an independently verified disposable
sandbox with **no external network interface or route**, including IPv6, local
node, DNS and metadata endpoints. Prefer a VM with its virtual NIC removed and
no shared host sockets. Stage the archive in a separate trusted downloader, verify
its chosen version/checksum, revoke or remove download credentials, then attach
only the selected input read-only and disposable output storage. Mount no host
runtime socket, production filesystem, sensitive `/proc`, device or network
namespace handle; inherit no connected sockets. Run without privilege, host
networking or network-administration capabilities. Inspect namespace/interface,
route, capability and mount evidence before parsing and keep safe synthetic
negative probes during processing. Authentication secrets needed to start restored
apps must be synthetic or separately approved for that sandbox.

`scripts/ci/recovery-containment-check.py` exercises only the **network namespace
portion** using synthetic IPv4/IPv6 addresses and `unshare --user --net`; it accepts
no archive input and does not isolate mounts. It is not a real-data restore runner.
The implementation workspace denies unprivileged network namespaces (`Operation
not permitted`), so this check and real containment remain **unverified**. Do not
fall back to an ordinary Pod, host networking or OpenClaw sandbox settings.
A functioning approved backend, mount/credential isolation and recorded network
proof remain prerequisites for the recovery specialist.

## Implementation validation record

Local checks on the candidate passed: 20 focused union/probe/rollout tests;
Kustomize renders of engine, policies and rollback; pinned Istio 1.27.3 gateway
render; Conftest repository policy evaluation; Checkov Kubernetes evaluation
(90 passed, 12 justified host-engine exceptions, zero failures); Ruff, YAML lint,
Python compilation and whitespace checks. The existing 16 Harbor render-check
fixtures also passed.

Full `nix run .#validate` could not run because Nix is absent. The broader Harbor
publisher suite was attempted but could not pass with `jq` and `cosign` absent.
No server-side dry run, actual packet matrix, app/signing probe, kernel validation,
resource measurement or rollback exercise was possible without cluster access.
The synthetic offline namespace check failed closed because this workspace
prohibits `unshare --net`. These are operational blockers, not successful tests.
