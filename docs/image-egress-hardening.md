# Internal images and pod egress

## Target and delivery gates

Applications pull only from `harbor.stinkyboi.com`. Use public Chainguard
images where the actual application and runtime contract are compatible;
retain digest-pinned Harbor copies for unavailable equivalents. Public sources
remain recorded in the publication catalog, never as a reason to allow public
registry access from application pods.

Image pulls are node/containerd traffic, outside Istio pod egress interception.
Private Harbor routing and fail-closed Talos mirrors are separate from pod
policies. Retain the documented upstream cold-bootstrap/recovery path; an empty
cluster cannot bootstrap its own in-cluster registry.

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

## Publication acceptance, 2026-10-10

The seven-image [publication run](https://github.com/Stuhlmuller/homelab/actions/runs/38092077585)
completed successfully. Read-only Harbor API inspection found completed scans
with zero reported vulnerabilities for all seven indexes and their fourteen
Linux amd64/arm64 manifests. The [scan receipt](chainguard-publication-scans.json)
records exact digests and scan times; child digests match the public source indexes.
This is a scanner snapshot of published artifacts. Active workload migration
and scan coverage for retained exceptions remain unverified.

[Linux compatibility CI](https://github.com/Stuhlmuller/homelab/actions/runs/38094665951)
passed 42 behavior tests inside the exact published Chainguard Python digest:
29 Harbor bootstrap, two exporter and eleven Fleet bootstrap tests, using UID
65532, no network and read-only roots. The Python/curl consumer change remains
staged until private node-to-Harbor transport and original app acceptance pass.

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

## BusyBox consumer compatibility

The consumer draft replaces 13 BusyBox references across 12 workload files
with the published Chainguard index. Its default UID is 65532, so Radarr,
Sonarr and Deluge init containers explicitly retain their existing root identity.
Backups remain UID 1000, NAS directory helpers UID 65534, Grafana uses the
chart's UID 472, and Cordium retains its explicit init/status identities.
No data format, backup retention window or production shell command changes.

`scripts/ci/chainguard-busybox-check.py` runs the declared commands on disposable
volumes in the exact public-source image bytes. Linux CI checks archive contents,
mode 0600, stale-backup/partial cleanup, unrelated-file retention, directory
permissions, ownership preparation, Grafana's retained database copy and
Cordium's file-write/readiness/liveness commands. Containers have no network,
a read-only root filesystem and only the tested capabilities. The CI setup
uses root only to seed its disposable fixture ownership.

Local Docker is unavailable; native Linux CI is required before merge. These
fixtures do not prove NFS root-squash behavior, a live kernel sysctl write or
the long-running Cordium status container. Verify the original operations
through the declared rollout after private Harbor node pulls are accepted.

## Egress enforcement contract

The cluster uses Istio ambient and Flannel. Flannel does not enforce the
existing Kubernetes NetworkPolicy objects. Istio AuthorizationPolicy currently
restricts inbound traffic for selected meshed workloads; it does not deny all
outbound traffic. `Sidecar` resources do not configure ambient workloads, and
`outboundTrafficPolicy: REGISTRY_ONLY` is not a security boundary.

A complete rollout needs a repository-owned policy-enforcing dataplane plus
Istio egress waypoints/gateways and narrow destination policies. Do not activate
an enforcing engine before reviewing all existing placeholder policies: they
would become effective immediately and can interrupt controllers, storage,
webhooks and recovery traffic. Pin the supported Istio version and render its
actual CRDs/charts before selecting current-documentation features.

Build each allowlist from its workload configuration and verified traffic:
DNS, Kubernetes API for controllers, declared in-cluster services, QNAP NFS,
required identity/provider APIs, certificate issuance, webhooks and application
update/download paths. Image registry access belongs only to nodes and the
Harbor publisher/replication/scanner workflows. Privileged/host-network pods,
VPN/UDP workloads and non-meshed namespaces need explicit controls; they cannot
be declared isolated solely by enrolling ordinary TCP workloads in Istio.

Acceptance must demonstrate allowed requests succeed and undeclared domains,
direct IPs, alternate ports, IPv6 and gateway bypass fail. Preserve DNS,
controller/webhook calls, storage mounts and the human/CI recovery route.
Roll back through the owning GitOps application and reviewed Talos config;
never repair a deny rule with manual cluster mutation.

Before an NRI or egress-gateway canary, compare private, read-only Pod and
NetworkPolicy snapshots with every rendered policy source by using
`scripts/network-policy-inventory.py`. Include chart renders and generated
Octelium policies in `--render`; repository YAML alone is insufficient. The
JSON review file records the exact `sha256` fingerprints emitted by the audit.
Run it with `--fail-on-findings` for the candidate namespace. It refuses
wildcard or ranged CIDR/port egress, peer selectors or IP blocks that reach all
other active Pods, unresolved namespace selectors, drifted, unowned and
unreviewed egress, plus unisolated, host-network, privileged,
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
protected production approval and complete anonymous download acceptance.

The publisher stages original multi-platform indexes using Skopeo's `dir:`
transport. The native offline regression in `harbor-publish-test.py` verifies
both architecture children and repeated index descriptors survive staging and
a second complete copy without changing manifest digests. It uses generated
local OCI fixtures with network transports rejected; it proves local transport
behavior, not Harbor publication or a signature accessory.

## Policy-enforcing dataplane prerequisite

The current Kubernetes SIG Network userspace enforcer release is v1.1.2
(2026-09-28). Its reviewed index is cataloged for Harbor publication, including
Linux amd64/arm64/s390x and source attestations; no DaemonSet is activated here.
Flannel continues to supply networking. The enforcer supplies L3/L4 boundaries
needed to prevent bypass of Istio egress waypoints/gateways.

Read-only inspection of worker 10.1.0.200 on 2026-10-11 found no
`/var/run/nri` socket directory and no explicit NRI stanza in its effective CRI
configuration. Verify all nodes and add the supported repository-owned Talos
NRI configuration before relying on runtime-synchronous Pod IP discovery.
The enforcer can fall back to API discovery if NRI initialization fails; that
fallback is not proof that startup traffic is isolated. Require a live socket,
plugin registration and negative startup/bypass tests.

Use explicit `--fail-open=false`, `--strict-mode=true` and a non-conflicting
NFQUEUE ID. Review every existing NetworkPolicy before activation: placeholders
become enforced together. Start with a reviewed worker canary, preserve host/API,
DNS, mesh HBONE, webhook and storage paths, then verify allowed traffic and denied
direct IP/alternate-port/IPv6/gateway bypass before expanding. Runtime and Istio
policy acceptance remain unproved; publication alone does not enforce egress.

Sources: [v1.1.2 release](https://github.com/kubernetes-sigs/kube-network-policies/releases/tag/v1.1.2),
[enforcer](https://kube-network-policies.sigs.k8s.io/) and
[Istio ambient egress](https://istio.io/latest/docs/ambient/usage/egress-gateway/).
