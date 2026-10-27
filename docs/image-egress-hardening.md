# Internal images and pod egress

## Target and delivery gates

The target is for applications to pull only from `harbor.stinkyboi.com`; the
full catalog publication and consuming-reference cutover remain pending. Use
public Chainguard images where the application and runtime contracts permit;
retain digest-pinned Harbor copies for unavailable equivalents. Public sources
remain recorded in the publication catalog, never as a reason to allow public
registry access from application pods.

Image pulls are node/containerd traffic, outside Istio pod egress interception.
Private Harbor routing and fail-closed Talos mirrors are separate from pod
policies. Retain the documented upstream cold-bootstrap/recovery path; an empty
cluster cannot bootstrap its own in-cluster registry.

Before the `mirror` project becomes private, reconcile the dedicated
`robot$mirror+pull` credential and verify authenticated registry configuration
on every Talos node. Keep `mirror` public through that node-auth phase; flipping
privacy earlier can strand uncached image pulls.

1. Publish the reviewed [Chainguard scope](harbor-image-mirroring.md#delivery)
   before merging any consuming references. Its seven latest-tag index digests
   were resolved anonymously on 2026-10-10; each index includes Linux amd64
   and arm64. Moving `latest` tags are source discovery only; runtime refs stay
   pinned to the verified index digest.
2. Test each consumer's command, user, CA trust, mounts and original action.
   Python exporter and shell-free curl readiness are the first stateless targets.
   BusyBox consumers require applet and filesystem ownership checks. PostgreSQL,
   Redis and Valkey require version, persisted-data, backup/restore and rollback
   acceptance; a major-version substitution is not an image-only update.
3. Explicitly override chart defaults, hooks, sidecars and operator-created
   images. Reconcile rendered/live images with the catalog; Talos-owned system
   images keep their supported version contract and use strict node mirrors.
4. Require fresh Harbor scan evidence for the exact deployed digest. Count
   vulnerabilities by active digest and severity; aggregate retained-artifact
   counts cannot prove running workloads are CVE-free. Unfixed exceptions need
   an affected digest, advisory, owner and reconsideration condition.
5. Merge consuming changes through normal protection, then verify Argo's
   observed revision, rollout, imageID and original application behavior.

No workload references or live node settings change in the publication
prerequisite. Removing old artifacts is not a vulnerability remediation method;
retain rollback images and backups.

## Admission inventory

The [Harbor-only image policy](../clusters/homelab/platform/image-policy/README.md)
uses Kubernetes native admission to report public references in regular, init,
and ephemeral containers. Its `Warn, Audit` binding has no system or namespace
exceptions, so it observes future Pod writes rather than existing Pods. Use the
separate static and live inventory for existing references. Promote it to `Deny`
only after catalog publication, private node-pull acceptance, and clean
inventories. It does not replace Istio egress controls or node-level Harbor
routing.

## Read-only findings, 2026-10-10

Context `admin@homelab`: 294 total Pods, including 83 completed/failed Pods.
The 211 running Pods reference 122 distinct container/init images; image strings
alone do not establish their transport. Every active public-origin reference
is covered by the existing full mirror catalog; publication and actual node
mirror enforcement still need verification. `zimaboard-2` is NotReady, and Flannel,
Istio CNI and ztunnel each have only three ready instances out of four.
A later read-only check during preparation found all four nodes Ready. Require
fresh node/dataplane readiness before any cluster-wide networking rollout;
transient recovery is not an egress acceptance test.

The Harbor vulnerability exporter returned 147 critical findings for `homelab`
and 345 for `mirror`. These are completed-scan artifact aggregates, including
retained images, not unique CVEs or an active-workload-only assessment.

Anonymous source probes confirmed Python, curl, BusyBox, Redis, Valkey,
PostgreSQL, Cosign, kubectl and nginx indexes. kubectl is not included in the
migration publication scope until client/server skew is checked. Generic nginx
is not a verified replacement for Harbor's coupled nginx-photon component.
Probed pgvector, MySQL, ClickHouse, Envoy, Cloudflared, Grafana, Prometheus-family,
Argo CD/Dex, cert-manager-family, External Secrets, Istio-family, Kiali,
Tailscale, metrics-server, descheduler, Crossplane, NFS provisioner and Harbor
component paths were not anonymously readable. Denial does not prove an image
is absent from Chainguard's production catalog. No production organization
credentials are assumed; approved exceptions remain Harbor-hosted.

## Egress enforcement contract

The cluster uses Istio ambient and Flannel. Flannel does not enforce the
existing Kubernetes NetworkPolicy objects. Istio AuthorizationPolicy currently
restricts inbound traffic for selected meshed workloads; it does not deny all
outbound traffic. `Sidecar` resources do not configure ambient workloads, and
`outboundTrafficPolicy: REGISTRY_ONLY` is not a security boundary.

### Read-only readiness audit, 2026-10-12

All four Flannel and ztunnel DaemonSet instances were Ready. That proves only
dataplane availability: it does not make Kubernetes `NetworkPolicy` enforcing
or add a default outbound deny.

Gateway API CRDs and a `GatewayClass` were absent at this audit. The existing
Istio `networking.istio.io` Gateway resources use the legacy API. Envoy Gateway
and firewall-only kube-router sources are now staged, but their Argo
Applications have automatic sync disabled and no canary node is selected.

No egress enforcement was activated. `zimaboard-2` is not a safe canary: it
has no dedicated taint or isolation, about 1.28 GiB capacity, system DaemonSets
and a live backup workload.

Before activation, publish and verify the pinned images, complete the Talos,
Kubernetes and Istio upgrade ladder, review every rendered and generated
NetworkPolicy, and admit a dedicated tainted canary with measured capacity.
Then qualify allowed and denied traffic and firewall lifecycle behavior through
the [GitOps-owned canary](../clusters/homelab/platform/network-policy/README.md).
The old source-only NRI fragment is not part of this kube-router path. Do not
activate the staged DaemonSet on a shared worker: existing placeholder policies
would become effective and could interrupt controllers, storage, webhooks and
recovery traffic.

Build each allowlist from its workload configuration and verified traffic:
DNS, Kubernetes API for controllers, declared in-cluster services, QNAP NFS,
required identity/provider APIs, certificate issuance, webhooks and application
update/download paths. Image registry access belongs only to nodes and the
Harbor publisher/replication/scanner workflows. Privileged/host-network pods,
VPN/UDP workloads and non-meshed namespaces need explicit controls; they cannot
be declared isolated solely by enrolling ordinary TCP workloads in Istio.

The NOFX frontend has no service-account token, probes its local `/health`
endpoint in-container, and permits only CoreDNS TCP/UDP 53 plus its backend on
TCP 8080/15008. Its declared policy contains no Harbor or public-registry
egress. It is not enforced until the kube-router canary proves the same allow
and deny paths. The backend admits ambient TCP 15008; its Istio
AuthorizationPolicy still limits the decrypted request to the frontend identity.

Acceptance must demonstrate allowed requests succeed and undeclared domains,
direct IPs, alternate ports, IPv6 and gateway bypass fail. Preserve DNS,
controller/webhook calls, storage mounts and the human/CI recovery route.
Roll back through the owning GitOps application and reviewed Talos config;
never repair a deny rule with manual cluster mutation.

Before a policy or egress-gateway canary, compare private, read-only Pod and
NetworkPolicy snapshots with every rendered policy source by using
`scripts/network-policy-inventory.py`. Include chart renders and generated
Octelium policies in `--render`; repository YAML alone is insufficient. The
JSON review file records the exact `sha256` fingerprints emitted by the audit.
Fingerprints cover ingress and egress rules; refresh private reviews made with
an older inventory version. Run it with `--fail-on-findings` for the candidate
namespace. It refuses live-only, drifted, or source-only policies, including
ingress-only generated policies. It also refuses
 wildcard or ranged CIDR/port egress, peer selectors or IP blocks that reach all
other active Pods, unresolved namespace selectors, unreviewed egress, plus
unisolated, host-network, privileged,
NET_ADMIN/NET_RAW/SYS_ADMIN and init-container workloads that require a
separate control-path review. The utility never calls Kubernetes and snapshot
files must remain private.

Candidate containers must explicitly drop `ALL` Linux capabilities before
adding only reviewed capabilities. Otherwise runtime-default capabilities are
reported as a separate-control-path finding.

The Pod snapshot must include active Pod IPs when a candidate uses `ipBlock`.
The audit compares resolved IP blocks against every other active Pod and flags
an incomplete IP snapshot rather than assuming those peers are unreachable.

Sources: [Istio security guidance](https://istio.io/latest/docs/ops/best-practices/security/),
[ambient egress gateways](https://istio.io/latest/docs/ambient/usage/egress-gateway/),
[Chainguard registry access](https://edu.chainguard.dev/chainguard/containers/registry/),
and the [existing isolation contract](runtime-isolation.md).

## Additional publication prerequisite

On 2026-10-11, anonymous index checks refreshed Python, PostgreSQL and Node
`latest-dev` in both publication catalogs; all thirteen staged Chainguard
indexes retain Linux amd64/arm64 manifests. Re-run consumer compatibility
against these exact digests. Earlier publication and compatibility receipts
do not cover changed artifacts. This source refresh changes no consumers,
node configuration or egress enforcement.

Anonymous source inspection resolved public Chainguard Node `latest`, Node
`latest-dev`, Go `latest` and nginx `latest`, each with Linux amd64/arm64 indexes. Add them to the
reviewed full catalog and Chainguard scope before custom build/runtime changes.
The nginx candidate is for generic application frontends such as NOFX, subject
to command, config, UID, temporary-path and actual HTTP/proxy tests. It does not
establish compatibility with Harbor's coupled nginx-photon component.
Public Wolfi base and static indexes are also staged for a NOFX backend rebuild.
Pinned source inspection found no TA-Lib linkage, but GORM's SQLite driver
still requires CGO. Native static-link, database and runtime tests must pass
before removing the existing Alpine exception; do not disable CGO to make a
smaller image compile.
Node uses `/usr/bin/node` and UID 65532; Go uses `/usr/bin/go` and UID 0 in its
build image. Existing shell/npm/CGO/linker, filesystem ownership and application
behavior contracts still require native compatibility tests; a tag lookup does
not prove a replacement works. No consumer changes in this prerequisite.

The full catalog also includes the paused Image Updater chart's actual v1.3.0
image, with Linux amd64/arm64/ppc64le/s390x manifests and source attestations.
Copy the complete index, preserving digests. Keep its zero replicas and promotion
gates unchanged until publication and its internal reference are accepted.
The prior seven-image publication receipt covers only those seven entries,
not the six additions: Go, nginx, Node runtime, Node dev, static and Wolfi base.
Any publication of the expanded scope requires a new
protected production approval and complete authenticated Harbor-pull acceptance.

The publisher stages original multi-platform indexes using Skopeo's `dir:`
transport. The native offline regression in `harbor-publish-test.py` verifies
both architecture children and repeated index descriptors survive staging and
a second complete copy without changing manifest digests. It uses generated
local OCI fixtures with network transports rejected; it proves local transport
behavior, not Harbor publication or a signature accessory.

## Policy-enforcing dataplane prerequisite

The [repository-owned enforcer](../clusters/homelab/platform/network-policy/README.md)
pins kube-router 2.11.1 with only its iptables firewall enabled. Flannel stays
the CNI and kube-proxy stays the service proxy. The Argo Application is dormant
and its node selector matches no node. The separate canary fixture Application
is empty by default; registration does not create probe Pods or policies.

The [read-only policy review](evidence/openclaw-enterprise-policy-review.json)
still records generated-policy ownership gaps and broad egress rules. Qualify
DNS, API, mesh HBONE, webhooks, NFS, host-network and VPN paths plus denied
direct IP, alternate-port and IPv6 traffic on the isolated canary before
expanding enforcement. Prove restart, API-loss, IP-reuse and cold-reboot
behavior; a one-shot probe is insufficient. Cleanup is a separate guarded
GitOps stage because deleting the DaemonSet can leave iptables/ipset rules.
Stock Enterprise's required public TCP/443 access remains a broad-egress
finding: Kubernetes NetworkPolicy cannot turn that into an FQDN allowlist.
Pinned Cordium `ws-main` and Octelium `svc-upstream` generators also allow
public IPv4/IPv6 egress on every port; an additional NetworkPolicy cannot
narrow those allows. The reviewed source patches are staged, and the protected
[`policy-generator-images.yml`](../.github/workflows/policy-generator-images.yml)
lane can build and publish three patched images from the exact current `main`.
It has not run, so there are no accepted Harbor digests or deployed consumers.
After publication, pin the authenticated-pull and signature-verified digests,
update the Octelium bootstrap wrapper, render the real generated policies, and
qualify required and denied traffic on the isolated canary before enforcement.
Publication and offline fixture tests alone do not establish live isolation.
