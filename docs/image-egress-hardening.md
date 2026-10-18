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

The source-only [NRI fragment](../.talos/patches/nri-containerd.yaml) prepares
an isolated CRI configuration part, but no node has received it and no NRI
plugin or policy-enforcing dataplane is deployed. It has no rollout helper or
node target. The offline gate proves strict machine-config validity only; a
future canary must reject a pre-existing `30-nri.part`, read the rendered CRI
configuration and NRI socket, and restore a complete desired machine config
without that owned entry before treating rollback as complete. Apply only with
a dedicated tainted canary worker and readback contract; enabling the runtime
socket on a shared worker would create a privileged control path before those
safeguards exist.

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

The NOFX frontend has no service-account token, probes its local `/health`
endpoint in-container, and permits only CoreDNS TCP/UDP 53 plus its backend on
TCP 8080/15008. Its declared policy contains no Harbor or public-registry
egress. It is not enforced until the NRI enforcer canary proves the same allow
and deny paths. The backend admits ambient TCP 15008; its Istio
AuthorizationPolicy still limits the decrypted request to the frontend identity.

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
protected production approval and complete authenticated Harbor-pull acceptance.

The publisher stages original multi-platform indexes using Skopeo's `dir:`
transport. The native offline regression in `harbor-publish-test.py` verifies
both architecture children and repeated index descriptors survive staging and
a second complete copy without changing manifest digests. It uses generated
local OCI fixtures with network transports rejected; it proves local transport
behavior, not Harbor publication or a signature accessory.

## Policy-enforcing dataplane prerequisite

`scripts/ci/network-policy-enforcement-check.py` is a CI-only, disposable
dual-stack Kind proof. Its public Kind, CNI, enforcer and Python images are test
fixtures, never homelab workload or node inputs. Passing it proves strict NRI
enforcement behavior only; production still needs the reviewed Harbor image,
dedicated worker, active NRI readback and application-specific egress canary.

The current Kubernetes SIG Network userspace enforcer release is v1.1.2
(2026-09-28). Its reviewed index is cataloged for Harbor publication, including
Linux amd64/arm64/s390x and source attestations; no DaemonSet is activated here.
Flannel continues to supply networking. The enforcer supplies L3/L4 boundaries
needed to prevent bypass of Istio egress waypoints/gateways.

Read-only inspection of worker 10.1.0.200 on 2026-10-11 found no
`/var/run/nri` socket directory and no explicit NRI stanza in its effective CRI
configuration. Verify all nodes and activate the reviewed inactive Talos NRI declaration
before relying on runtime-synchronous Pod IP discovery.
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

## Istio 1.27 external-service routing prerequisite

Use the pinned implementation before selecting an egress feature. Istio 1.27.3
binds ServiceEntries to waypoints and includes explicit or autoallocated service
addresses in the ambient service index. Its IP autoallocation flag defaults to
true, but the source states that TCP routing also requires DNS capture.
Repository [Istio values](../clusters/homelab/apps/istio/values.yaml) currently
set `cni.ambient.dnsCapture: false`. A waypoint label alone therefore does not
establish that application DNS answers route external TCP through that gateway.

Before activation, prove the declared destination receives an allocated address,
the canary resolves that address through capture, ztunnel routes it through the
intended waypoint, and the original application request succeeds. Enforced
network rules must also deny real destination IPs, alternate ports and direct
routes that bypass the waypoint. Test both IP families, TLS SNI/shared-address
cases and unauthorized DNS queries; a captured DNS answer is routing evidence,
not a complete egress security boundary. Keep observations private.

Sources: [1.27.3 service-entry index](https://github.com/istio/istio/blob/1.27.3/pilot/pkg/serviceregistry/kube/controller/ambient/services.go)
and [1.27.3 autoallocation flag](https://github.com/istio/istio/blob/1.27.3/pilot/pkg/features/pilot.go).
No CNI setting, waypoint or ServiceEntry is activated by this prerequisite.

## Offline NRI prerequisite

Audit live policies privately before activation. Policies are additive: Fleet's
namespace-wide `fleet-ambient` allowance already permits HBONE, and an ingress rule without
`ports` already permits all ports. Do not classify each individual policy as a
standalone deny rule.

LiteLLM, Multica and n8n database policies permit TCP 15008 from their
existing client selectors; the NOFX backend separately admits HBONE for
Istio identity enforcement. Matching Istio AuthorizationPolicy
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

The repository-owned `scripts/talos-nri-canary.py` now supplies the fixed-worker
operator path. Its default is read-only: verify context, all declared nodes,
worker/boot identity, CRI health, absence of the declared policy engine, active
and persistent configuration equality, and strict candidate validation. It
reuses the Harbor operator's configuration capture, including staged/try-state
refusal, while preserving all machine-config documents.

```sh
nix develop --command python3 -I scripts/talos-nri-canary.py \
  --talosconfig /private/path/talosconfig --talosctl /path/to/talosctl-1.11.3
```

Execution requires a clean checkout at exact current reviewed main. Enable and
enabled-state scheduling release also require successful full-scope image
publication under its existing bundle-equality gate. Rollback remains available
without a fresh publication gate. After the
shared image/node recovery hold is released, add `--execute --expected-sha
<CURRENT_MAIN_SHA>`. The helper rechecks configuration and boot around drain,
respects PDBs, refuses unmanaged Pods/emptyDir deletion, applies only its NRI
candidate in `no-reboot` mode, waits for active/persistent and merged CRI readback,
then explicitly restarts CRI. Drain precedes configuration application so any
runtime interruption is confined to the drained canary. Post-restart gates require
healthy CRI, unchanged boot, Ready node and the Flannel/CNI/ztunnel DaemonSet Pods.
The worker remains cordoned on success or failure after drain.

Rollback uses the same helper with `--rollback --execute --expected-sha
<CURRENT_MAIN_SHA>` after withdrawing the declared policy engine through GitOps.
It permits an unhealthy CRI/NotReady canary while requiring the other nodes and
fixed target identity, then enforces the disabled fragment and restart/readback
gates. Successful plumbing acceptance permits a separate `--release-scheduling
--execute --expected-sha <CURRENT_MAIN_SHA>` action; include `--rollback` when
releasing a disabled candidate. Release rechecks declared machine/CRI state,
identity, main, CRI health, dataplane readiness and absence of the policy engine;
it does not change configuration or restart CRI.

Offline canary tests cover sequencing, rollback recovery, context/node/config/
publication refusals, PDB drain failure, failed readback/restart and refusal to
release scheduling with unhealthy dataplane. No helper is executed against live
state by CI. Before deploying the enforcer, review all effective NetworkPolicies
and independently prove NRI registration, synchronization, recovery and allowed/
denied traffic. This path verifies NRI plumbing, not policy enforcement.

Talos 1.11.3's [CRI parts controller](https://github.com/siderolabs/talos/blob/v1.11.3/internal/app/machined/pkg/controllers/files/cri_config_parts.go)
sorts `/etc/cri/conf.d/*.part` and merges them into
`/etc/cri/conf.d/cri.toml`. Its [merge implementation](https://github.com/siderolabs/talos/blob/v1.11.3/pkg/machinery/config/merge/merge.go)
explicitly replaces boolean values even when the new value is `false`.
Standalone fragment validation therefore is only the first gate: before a
controlled restart, the operator path must wait for the merged file to contain
`plugins."io.containerd.nri.v1.nri".disable = false` and the declared socket path,
reject later conflicting fragments, and verify unrelated CRI settings remain
unchanged. After rollback it must prove the merged `disable = true` value.
Keep complete machine/CRI configuration captures private; report only gate
results. After restart, socket existence alone is insufficient: verify plugin
registration, runtime synchronization and traffic enforcement separately.

Validate private before/after merged-file snapshots with:

```sh
nix develop --command python3 -I scripts/talos-nri-effective-check.py \
  --before /private/path/cri-before.toml --after /private/path/cri-after.toml
```

Use `--rollback` for the disabled declaration. The checker takes its owned
values from the committed fragment, requires a boolean NRI state, and rejects
any other semantic CRI change. It withholds private values on failure. Its
regressions cover incorrect state/type, a missing socket and unrelated-setting
drift. It verifies supplied snapshots, not their live freshness or the restart;
the guarded operator path must capture and bind those to the same node/boot.

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

Strict-mode revocation is asynchronous: the pinned implementation's conntrack
runner has a 30-second minimum interval. The held connection must stop within
45 seconds after new requests are denied; continued access beyond that bound
fails CI. Production acceptance must wait for established-flow revocation,
not merely observe denial of a new connection.

The enforcer manifest under `scripts/ci/fixtures/` is CI-only. Its public source
image and the legacy transport are not production application references.
Production keeps Flannel and needs a Harbor-hosted enforcer, the reviewed Talos
canary path and a complete policy audit before activation. This fixture cannot
prove Talos integration, ambient HBONE behavior, public-domain/SNI controls or
the live application's original behavior. Local Docker is unavailable; the
dedicated Linux CI job must pass before this prerequisite is ready.

The same owned Kind fixture also runs `istio-egress-routing-check.py` with
checksum-pinned Istio 1.27.3 charts and catalog-pinned component images. It
installs Gateway API from the same immutable source as the registration
prerequisite and enables DNS capture/IPv6 inside the dual-stack fixture only.
Disabling IPv6 with dual-stack sandbox addresses makes Istio 1.27.3 reject the
Pod before traffic tests, so the fixture retains both address families rather
than suppressing the CNI failure. It requires the
client to resolve the exact allocated ServiceEntry address. Both callers must
succeed before authorization; the waypoint must subsequently deny the
unauthorized service account while preserving the required caller. A direct-IP
baseline in both IPv4 and IPv6 precedes enforced egress isolation, which must
retain the required route while denying both real destination addresses and the
alternate service port. The target listens on both families; an IPv6 denial is
accepted only after that same address/port succeeded before isolation.

This proves an isolated IPv4 TCP routing boundary, not the production domain
allowlist. TLS origination/certificate checks, SNI/shared-IP behavior, DNS-query
leakage, required ambient IPv6 routing, host-network/privileged bypass and original application
actions remain required. Production DNS capture stays disabled. Local Docker is
unavailable; fresh Linux CI must pass this added stage before trusting it.

Sources: [pinned enforcer](https://github.com/kubernetes-sigs/kube-network-policies/tree/v1.1.2)
and [upstream transport-only fixture](https://github.com/kubernetes-sigs/kube-network-policies/blob/v1.1.2/tests/setup_suite.bash).
