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

## Offline NRI prerequisite

The activation audit found 60 live NetworkPolicies, including 16 that select
egress, on 2026-10-10. Policies are additive: Fleet's namespace-wide
`fleet-ambient` allowance already permits HBONE, and an ingress rule without
`ports` already permits all ports. Do not classify each individual policy as a
standalone deny rule.

LiteLLM, Multica and n8n database policies and the NOFX backend now permit TCP
15008 from their existing client selectors. Matching Istio AuthorizationPolicy
rules restrict decrypted traffic to database port 5432 or backend port 8080;
n8n uses its declared `n8n` service account. These database health probes use
local exec, so no network probe exception is needed. The signer uses Harbor's
application route on Traefik 8443; node pulls use the distinct registry listener
9443. Keep those paths separate.

Remaining activation checks include chart-generated Kiali rules, health-probe
SNAT addresses, backup clients and dynamically generated Cordium policies.
NOFX still has unrestricted egress, Cordium workspace/upstream rules permit
public networks, and several controller/bootstrap policies allow broad CIDRs.
These need destination-specific Istio routing plus enforced bypass prevention;
HBONE compatibility alone does not constrain outbound traffic.

See [ambient NetworkPolicy behavior](https://istio.io/latest/docs/ambient/usage/networkpolicy/).

The candidate policy enforcer needs containerd's Node Resource Interface (NRI).
The committed `.talos/patches/network-policy-nri.yaml` declares its CRI fragment;
it is inactive. Talos strategic merge appends `machine.files`, so blindly applying
enable and rollback patches can leave duplicate declarations for one path.
The offline preparer replaces only the owned fragment, preserves every other
configuration document and refuses duplicate existing NRI entries.

Keep the authenticated node configuration and generated candidate outside git:

```sh
nix develop --command python3 -I scripts/talos-nri-config.py \
  --input /private/path/worker-current.yaml \
  --output /private/path/worker-nri-candidate.yaml
```

The output must be a new file outside this checkout. It is written with mode
`0600` only after `talosctl validate --mode metal --strict` succeeds. The helper
never contacts a node. Use a CLI matching the installed Talos release via
`--talosctl /path/to/talosctl` when needed. Existing owned entries use
`overwrite`, including re-enable after rollback; unrelated files stay intact.

Prepare rollback from the enabled configuration with `--rollback` and a new
private output path. Withdraw the policy enforcer before disabling NRI.
`scripts/ci/talos-nri-config-check.py` checks generated worker/control-plane
configs, enable/rollback/re-enable, preserved fields and private output guards.
These checks passed with Talos 1.11.3 and 1.13.2.

This change provides preparation only. Before activation, add the repository
operator path for a drained worker canary and controlled CRI restart, review all
existing NetworkPolicies, and prove NRI registration, recovery and allowed/denied
traffic. No NRI setting, DaemonSet or live NetworkPolicy enforcement is activated
by this prerequisite.

Sources: [Talos NRI CRI fragment](https://github.com/siderolabs/talos/discussions/10068)
and [Talos patch semantics](https://docs.siderolabs.com/talos/v1.11/configure-your-talos-cluster/system-configuration/patching).

## Isolated enforcement acceptance

`scripts/ci/network-policy-enforcement-check.py` creates a disposable dual-stack
Kind cluster with NRI enabled and a private temporary kubeconfig. Every kubectl
call names that file; the helper refuses an existing cluster of the same name
and deletes only its own fixture cluster. No production credentials are loaded.

The fixture first uses the upstream test suite's pinned transport-only Kindnet
image and verifies that policies alone leave traffic unrestricted. It then
installs the pinned enforcer with `--fail-open=false`, `--strict-mode=true` and
NRI enabled, requiring runtime synchronization on both nodes. TCP/UDP probes
cross node boundaries and test allowed destinations, denied destinations,
alternate ports and both IP families. Separate checks cover Service DNAT,
cluster DNS, allowed/denied init-container requests on a fresh sandbox and
revocation of an established TCP connection.

The enforcer manifest under `scripts/ci/fixtures/` is CI-only. Its public source
image and the legacy transport are not production application references.
Production keeps Flannel and needs a Harbor-hosted enforcer, the reviewed Talos
canary path and a complete policy audit before activation. This fixture cannot
prove Talos integration, ambient HBONE behavior, public-domain/SNI controls or
the live application's original behavior. Local Docker is unavailable; the
dedicated Linux CI job must pass before this prerequisite is ready.

Sources: [pinned enforcer](https://github.com/kubernetes-sigs/kube-network-policies/tree/v1.1.2)
and [upstream transport-only fixture](https://github.com/kubernetes-sigs/kube-network-policies/blob/v1.1.2/tests/setup_suite.bash).

Sources: [Istio security guidance](https://istio.io/latest/docs/ops/best-practices/security/),
[ambient egress gateways](https://istio.io/latest/docs/ambient/usage/egress-gateway/),
[Chainguard registry access](https://edu.chainguard.dev/chainguard/containers/registry/),
and the [existing isolation contract](runtime-isolation.md).
