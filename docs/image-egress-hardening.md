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

The publication prerequisite changes no workloads or live node settings.
The transport-only consumer draft changes named references while preserving
tags, digests and all other workload fields; Helm defaults and generated images
remain separate completion gates. Its source-normalized YAML comparison covered
66 changed files. The explicit Harbor bootstrap overlays are inactive in normal
Application sources and still require cold-recovery acceptance. Removing old artifacts is not a vulnerability remediation method;
retain rollback images and backups.

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

## Verified Chainguard publication

[Run 38092077585](https://github.com/Stuhlmuller/homelab/actions/runs/38092077585)
completed successfully on reviewed `main`
`31245542329cb3f74709356c755b3264683e1ef4` on 2026-10-10. The user authorized
its production-environment approval. It published only the seven pinned
entries in [the Chainguard scope](../scripts/config/harbor-chainguard-images.json),
with all-platform digest preservation, matching source-tag aliases and fresh
complete anonymous downloads. The shared full catalog was not published by
this scoped run.

Read-only Harbor API inspection found every expected index digest under
`mirror/cgr.dev/chainguard/<name>`, with successful scan status and two child
references. A missing severity map is not proof of zero vulnerabilities;
require completed summaries for the exact deployed architecture/digest before
claiming CVE remediation. No consuming applications or node configuration were
changed by this publication.

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

Sources: [Istio security guidance](https://istio.io/latest/docs/ops/best-practices/security/),
[ambient egress gateways](https://istio.io/latest/docs/ambient/usage/egress-gateway/),
[Chainguard registry access](https://edu.chainguard.dev/chainguard/containers/registry/),
and the [existing isolation contract](runtime-isolation.md).

## Chart-generated internal references

The staged internal-reference migration overrides the Istio injector, Kiali's
supported default server image and Tailscale's generated proxy image, alongside
their controller images. Kiali keeps ad-hoc CR images disabled. Tailscale
ProxyClass and kube-apiserver ProxyGroup image overrides need separate review.
Grafana's main/test/dashboard images and the Prometheus stack's operator,
config reloader, certificate hooks, kube-state-metrics, Prometheus and
Alertmanager use the cataloged Harbor digests. The operator's default base
repositories also point to Harbor; its Thanos default is pinned. New custom
resources still require an explicitly published version/digest before rollout. Prometheus and Alertmanager
version fields remain separate from their digest-bearing image tags.

These settings preserve existing versions and do not remediate the retained
images' CVEs. Pinned Helm renders and controller-created live Pods both need
verification. Full-catalog publication, private node routing, remaining chart
and controller defaults, compatible Chainguard upgrades and enforced egress
remain rollout gates; the seven-image publication proves only its fixed scope.

The unchanged Prometheus chart also renders an unused default Alertmanager
Secret despite the existing `configSecret` reference. Generic raw-Secret
Conftest rejects that resource in both before/after renders; the canonical
comparison proves its content unchanged. The image migration does not commit
that generated Secret. Review chart `useExistingSecret` ownership separately;
retain the declared ExternalSecret-backed runtime configuration.
