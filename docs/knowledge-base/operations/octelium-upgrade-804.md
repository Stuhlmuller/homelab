<!-- markdownlint-disable MD013 -->

# Octelium Upgrade Research for Issue 804

Tags: #operations #octelium #upgrade #research

Status: blocked for staging and rollout. This note covers the requested move
from Octelium core `0.35.0`, Octelium Enterprise `0.22.0`, and Cordium `0.12.7`
to `0.40.0`, `0.29.0`, and `0.13.1` respectively.

Related context: [[runbooks/octelium]], [[architecture/gitops-flow]],
[[architecture/storage-and-state]], [[operations/validation-gates]], and
[[workloads/inventory]].

## Decision

Do not stage version or digest changes yet.

Octelium `0.40.0` moved install-topology options from Genesis flags into
`ClusterConfig.status.installation`. The repository's existing-cluster wrapper
still supplies front-proxy mode through legacy environment variables. The
`0.40.0` upgrade command does not backfill the new status field or forward the
old front-proxy input. Its generators use only the new status field. An upgrade
from the current `0.35.0` object can therefore regenerate the ingress Service on
port `443` and omit `OCTELIUM_FRONT_PROXY_MODE=true`, breaking the repository's
Istio front door. Upstream does not document a supported migration for this
case.
[Repository upgrade wrapper](../../../scripts/octelium-cluster-bootstrap.sh)

The repository also records PostgreSQL restore as unproven, while PostgreSQL is
Octelium's primary resource store. The official upgrade guide and reviewed
release pages provide no rollback or downgrade procedure. Both gaps must be
resolved before the rollout can be called recoverable.
[Upstream storage contract](https://octelium.com/docs/octelium/latest/install/cluster/bootstrap)
[Repository storage evidence](../architecture/storage-and-state.md)

The fresh-install path has the same front-proxy defect independently of the
existing-object migration. The repository bootstrap file omits
`spec.ingress.frontProxy.enable`, while `0.40.0` init derives installation
state from that file rather than the wrapper's legacy environment variables. A
disaster rebuild would therefore also regenerate ingress on port `443`.

## Intended Upgrade Order

| Phase | From | To | Upstream operation | Advance only when |
| --- | --- | --- | --- | --- |
| Core | `0.35.0` | `0.40.0` | `octops upgrade <domain> --version 0.40.0 --wait` | Core, front proxy, API, Sessions, policies, and Services pass |
| Enterprise | `0.22.0` | `0.29.0` | `octops install-package <domain> --package octeliumee --version 0.29.0 --upgrade` | Enterprise workloads, stores, console, and access portal pass |
| Cordium | `0.12.7` | `0.13.1` | `octops install-package <domain> --package cordium --version 0.13.1 --upgrade` | Workspace lifecycle and nested access pass |

The public core upgrade guide presents one exact-version upgrade operation and
does not prescribe intermediate hops. It does not publish a compatibility
matrix that explicitly guarantees this five-release skip. The command above is
therefore the documented mechanism, not proof that the exact skip is safe.
[Upstream upgrade guide](https://octelium.com/docs/octelium/latest/install/cluster/upgrade)

Core-first is the safest sequencing inference because Enterprise installs into
an already running Octelium cluster. Enterprise `0.29.0` pins a core commit
shortly before `0.40.0`, but Cordium `0.13.1` pins core commit `b9c16b89` from
2026-07-19, before core `0.38.0`. Neither dependency pin proves that the exact
`0.40.0`/`0.29.0`/`0.13.1` combination is compatible. Enterprise-before-Cordium
follows this repository's existing Terragrunt dependency graph and limits
simultaneous change; a combined smoke gate must still prove the final tuple.
[Enterprise installation contract](https://github.com/octelium/octelium-ee/blob/v0.29.0/README.md)
[Enterprise target dependency](https://github.com/octelium/octelium-ee/blob/v0.29.0/cluster/genesis/go.mod)
[Cordium target dependency](https://github.com/octelium/cordium/blob/v0.13.1/cluster/genesis/go.mod)
[Cordium pinned core commit](https://github.com/octelium/octelium/commit/b9c16b89a300db3d22163b0f99815eae1ddbb7ce)
[Pinned commit to core 0.38.0](https://github.com/octelium/octelium/compare/b9c16b89a300...v0.38.0)
[Repository dependency graph](../../../IaC/terragrunt.stack.hcl)

## Compatibility Findings

### Core `0.35.0` to `0.40.0`

The intervening releases add MMDB authentication, RDP Web and SOCKS5 Service
modes, Redis Streams for resource watches, Windows QUIC support, PKCE login,
MCP/LLM Service modes, and stronger Linux capability restrictions. The
`0.40.0` release reduces capabilities across most cluster-side workloads; the
GatewayAgent exception is detailed below.
[0.36.0](https://github.com/octelium/octelium/releases/tag/v0.36.0)
[0.37.0](https://github.com/octelium/octelium/releases/tag/v0.37.0)
[0.38.0](https://github.com/octelium/octelium/releases/tag/v0.38.0)
[0.39.0](https://github.com/octelium/octelium/releases/tag/v0.39.0)
[0.40.0](https://github.com/octelium/octelium/releases/tag/v0.40.0)

Generated API comparison found no removed fields in the repository-used core
`ClusterConfig`, `Service`, `User`, `Group`, `Policy`, `IdentityProvider`,
`Credential`, or `Namespace` messages. Additions include MMDB authentication,
device probes, and `ClusterConfig.status.installation` for SPIFFE, CNI, and
ingress topology. The bootstrap schema also adds SPIFFE, CNI, ingress, and
network bit-allocation inputs; the current storage and QUIC inputs remain.
[0.35.0 core API](https://github.com/octelium/octelium/blob/v0.35.0/apis/main/corev1/corev1.pb.go)
[0.40.0 core API](https://github.com/octelium/octelium/blob/v0.40.0/apis/main/corev1/corev1.pb.go)
[0.40.0 bootstrap API](https://github.com/octelium/octelium/blob/v0.40.0/apis/cluster/cbootstrapv1/cbootstrapv1.pb.go)

Most `0.40.0` cluster-side workloads drop Linux capabilities. Named ingress,
Vigil, and managed Service-proxy containers may add only `NET_BIND_SERVICE`.
GatewayAgent may additionally add `NET_ADMIN`, `NET_RAW`, and `MKNOD`, and its
node-init container remains privileged. Repository policy must allow only those
named exceptions and reject every other capability addition.
[0.40.0 GatewayAgent security context](https://github.com/octelium/octelium/blob/v0.40.0/cluster/genesis/genesis/components/gwagent.go#L110-L208)
[0.40.0 ingress security context](https://github.com/octelium/octelium/blob/v0.40.0/cluster/genesis/genesis/components/ingress.go#L307-L320)
[0.40.0 Service-proxy security contexts](https://github.com/octelium/octelium/blob/v0.40.0/cluster/nocturne/nocturne/controllers/services/controller.go#L215-L325)

The breaking repository interaction is the front-proxy migration:

1. The upstream change moves topology state into
   `ClusterConfig.status.installation`.
2. `0.40.0` parses the former flags as hidden/deprecated, but `RunUpgrade`
   receives an empty option set.
3. The current `octops` Genesis launcher passes only `upgrade`; it does not
   forward `OCTELIUM_INGRESS_FRONT_PROXY`.
4. The ingress generator selects front-proxy mode only from
   `status.installation.ingress.frontProxy.enable`.
5. Without that value, the generated ingress Service uses port `443` instead
   of the repository-required front-proxy port `8080`, and the deployment omits
   `OCTELIUM_FRONT_PROXY_MODE=true`.

[Topology migration change](https://github.com/octelium/octelium/commit/4dee89a39a711fc0d56067b0733c6eff0bbe5fd2)
[0.40.0 Genesis entrypoint](https://github.com/octelium/octelium/blob/v0.40.0/cluster/genesis/main.go)
[0.40.0 upgrade command](https://github.com/octelium/octelium/blob/v0.40.0/cluster/genesis/genesis/cmd_upgrade.go)
[0.40.0 Genesis launcher](https://github.com/octelium/octelium/blob/v0.40.0/client/octops/commands/install/genesis.go)
[0.40.0 installation state reader](https://github.com/octelium/octelium/blob/v0.40.0/client/octops/commands/install/installation.go)
[0.40.0 common generator](https://github.com/octelium/octelium/blob/v0.40.0/cluster/genesis/genesis/components/common.go)
[0.40.0 ingress generator](https://github.com/octelium/octelium/blob/v0.40.0/cluster/genesis/genesis/components/ingress.go)

Fresh init is independently unsafe. The current repository wrapper's bootstrap
file has no `spec.ingress`, and `0.40.0` copies installation state from that
bootstrap field. The Genesis launcher does not forward the legacy front-proxy
environment variables. A rendered fresh-init contract must prove Service port
`8080` and `OCTELIUM_FRONT_PROXY_MODE=true`; fixing only the existing-cluster
migration is insufficient.
[Repository bootstrap input](../../../scripts/octelium-cluster-bootstrap.sh)
[0.40.0 init installation state](https://github.com/octelium/octelium/blob/v0.40.0/cluster/genesis/genesis/cmd_init.go#L365-L395)
[0.40.0 init launcher](https://github.com/octelium/octelium/blob/v0.40.0/client/octops/commands/install/genesis.go#L151-L210)

### Enterprise `0.22.0` to `0.29.0`

Enterprise release pages provide comparison links but no migration narrative.
The source delta adds a managed Access Portal/API path, moves the system API
from identity to access, hardens the console, changes generated security
contexts and resource settings, and contains data-store migrations. For
example, the DuckDB limit helper falls from `4000m`/`3000Mi` to
`1500m`/`1500Mi` and adds an FS group. The upgrade command regenerates
components and Octelium-native resources.
[0.29.0 release](https://github.com/octelium/octelium-ee/releases/tag/v0.29.0)
[0.22.0...0.29.0 comparison](https://github.com/octelium/octelium-ee/compare/v0.22.0...v0.29.0)
[0.29.0 upgrade source](https://github.com/octelium/octelium-ee/blob/v0.29.0/cluster/genesis/genesis/cmd_upgrade.go)
[0.29.0 initialization source](https://github.com/octelium/octelium-ee/blob/v0.29.0/cluster/genesis/genesis/cmd_init.go)
[0.29.0 component defaults](https://github.com/octelium/octelium-ee/blob/v0.29.0/cluster/genesis/genesis/components/common.go)

Generated Enterprise API comparison found no removed `ClusterConfig` fields;
the target adds license status. That does not make a tag-only manifest edit
safe because the generator changes object topology and workload fields.

Metric history does not migrate implicitly. Enterprise `0.22.0` writes the
legacy `metrics` table to `/octelium-data/store.db`. Enterprise `0.29.0`
defaults to `/octelium-data/metricstore.db` on the same PVC, so it starts a new
store and leaves the old history unread; pointing it at the old file is also
unsupported because the target explicitly rejects the legacy table. Before
upgrading, either prove a supported migration/export-import or approve and
document a reset while archiving `store.db`. A known pre-upgrade metric query
must be checked after rollout; PVC binding and file retention are insufficient.
[0.22.0 DuckDB path](https://github.com/octelium/octelium-ee/blob/v0.22.0/cluster/common/ovutils/ovutils.go#L93-L112)
[0.22.0 legacy metric table](https://github.com/octelium/octelium-ee/blob/v0.22.0/cluster/metricstore/metricstore/server.go#L152-L179)
[0.29.0 metric database](https://github.com/octelium/octelium-ee/blob/v0.29.0/cluster/metricstore/metricstore/config.go#L23-L76)
[0.29.0 legacy-schema rejection](https://github.com/octelium/octelium-ee/blob/v0.29.0/cluster/metricstore/metricstore/db.go#L335-L348)

### Cordium `0.12.7` to `0.13.1`

The `0.13.1` release has no release narrative. Its source comparison includes
Go and Octelium dependency updates, a Portal migration to `@octelium/apis`,
supervisor propagation of `OCTELIUM_DOMAIN` and
`OCTELIUM_AUTH_PROXY_SOCKET`, and Vigil activity tracking. The generated
Cordium `ClusterConfig` message is unchanged, so the repository's
`cordium-local` workspace storage rule remains schema-compatible.
[0.13.1 release](https://github.com/octelium/cordium/releases/tag/v0.13.1)
[0.12.7...0.13.1 comparison](https://github.com/octelium/cordium/compare/v0.12.7...v0.13.1)

Cordium has a native `upgrade` path that updates generated components and
system resources. The permanent bootstrap Job must remain an `init` path for a
fresh cluster; changing it to `upgrade` would break first install. An existing
cluster needs a separate one-shot, repository-owned upgrade phase.
[Cordium upgrade source](https://github.com/octelium/cordium/blob/v0.13.1/cluster/genesis/genesis/cmd_upgrade.go)
[Cordium Genesis commands](https://github.com/octelium/cordium/blob/v0.13.1/cluster/genesis/main.go)
[Core package upgrade command](https://github.com/octelium/octelium/blob/v0.40.0/client/octops/commands/installpackage/cmd.go)
[Repository Cordium bootstrap](../../../clusters/homelab/apps/cordium-bootstrap/genesis.yaml)

## Manifest Strategy

Regenerate, capture, scrub, and review target manifests. Do not hand-edit image
tags or digests in the existing generated captures.

Official install documentation defines Genesis as the Kubernetes Job that
performs installation and upgrades; it documents no complete declarative
render/export operation. Enterprise and Cordium upgrade commands likewise
regenerate resources. Tag-only changes would miss new objects, renamed paths,
security contexts, resource limits, and migrations.
[Upstream bootstrap guide](https://octelium.com/docs/octelium/latest/install/cluster/bootstrap)

The safe repository workflow, after resolving the blockers, is:

1. Add a reviewed, declarative phase that prevents Argo CD from racing the old
   Enterprise capture or replaying the old Cordium `init` hook.
2. Run the exact upstream upgrade generator for one layer only.
3. Capture its complete generated output; remove runtime metadata and Secrets.
4. Pin every referenced image by the resolved target digest.
5. Reapply repository invariants: node roles, `Recreate`, `Replace=true`, PVC
   retention, proxy-image drift ignore, and least-privilege ownership.
6. Render and policy-check the capture before re-enabling sync/self-heal.

The same capture rule applies to core emergency dataplane resources: they
contain generated proxy and Service identity details that are coupled to the
target version. The current 26 fallbacks reuse production Service selectors
while the two native dataplane workers are NotReady. Service-level checks can
therefore pass through old core, Enterprise, or Cordium fallback images. Recover
the native fleet and probe Pod IPs directly for 24 hours before upgrading, or
define an atomic phase-aligned fallback transition for every image and generated
Service UID.
[Repository capture contract](../../../clusters/homelab/apps/octelium-enterprise/README.md)
[Repository dataplane recovery contract](../architecture/cluster-topology.md)

## Validation Gates

### Before any upgrade

- The staged repository change passes every command below:

  ```sh
  terragrunt hcl fmt --check
  terragrunt hcl validate
  nix develop --command bash scripts/ci/static-checks.sh
  nix develop --command bash scripts/ci/conftest-policies.sh
  git diff --check
  ```

- A fresh PostgreSQL backup completes and an isolated restore proves usable
  resources, not only that `pg_restore --list` can read the archive.
- Coordinated checkpoints exist for PostgreSQL, Redis/secondary state, and the
  Enterprise rscstore, logstore, and metricstore PVCs. Record the exact old
  repository revision, rendered manifests, and image digests.
- Metricstore v1 history has either a supported migration/export-import or an
  approved reset with `store.db` archived. Record a known metric query and its
  pre-upgrade result for the Enterprise acceptance gate.
- The package-managed native dataplane fleet has been Ready for 24 hours and
  passes direct Pod-IP probes. If incident fallbacks must remain, encode and
  review an atomic version-coherent transition; Service-level E2E alone cannot
  advance an upgrade phase.
- A supported method makes
  `ClusterConfig.status.installation.ingress.frontProxy.enable` explicitly
  `true` before `0.40.0` Genesis runs. Do not patch status or the backing store
  ad hoc.
- The fresh-bootstrap input explicitly sets
  `spec.ingress.frontProxy.enable: true`, and a rendered init test proves
  ingress Service port `8080` plus `OCTELIUM_FRONT_PROXY_MODE=true`.
- The Argo CD capture/self-heal transition is encoded and reviewed.
- All target tags and their platform manifests resolve in the primary registry.

### Core phase

- The exact-version Genesis Job succeeds and all core Deployments,
  DaemonSets, and StatefulSets become ready.
- The Region version reports `0.40.0`.
- `ClusterConfig.status.installation.ingress.frontProxy.enable` is `true`.
- `octelium-ingress-dataplane` still exposes port `8080`, and its deployment
  still has `OCTELIUM_FRONT_PROXY_MODE=true`.
- API access, a current Session, a new Session, IdentityProvider login,
  policies, and representative Services work.
- `scripts/octelium-e2e-check.sh` passes, including the public gRPC probe.

Stop before Enterprise if any core check fails.

### Enterprise phase

- The package Genesis Job succeeds and the package version reports `0.29.0`.
- All Enterprise deployments and Services are ready; rscstore, logstore, and
  metricstore PVCs remain bound and retain data.
- A query for the recorded pre-upgrade metric returns the required history, or
  the approved reset/archive record proves that history loss was intentional.
- The Enterprise console and new Access Portal/API work.
- The recaptured `resources.yaml` renders with no Secrets or generated runtime
  metadata; all images are digest-pinned and repository rollout/PVC/ignore
  invariants remain.
- Argo CD reports Synced and Healthy with no unexplained drift, then
  `scripts/octelium-e2e-check.sh` passes again.

Stop before Cordium if any Enterprise check fails.

### Cordium phase

- The package Genesis Job succeeds and the package version reports `0.13.1`.
- Cordium controllers and proxies become ready, and the repository
  `ClusterConfig` still selects `cordium-local` for workspaces.
- `cordium status -o json` succeeds.
- Create and start one bounded ephemeral workspace, wait for `RUNNING`, run
  `cordium exec <workspace> --no-stdin -- true`, then delete it and verify its
  Pod and PVC are removed.
- `scripts/octelium-e2e-check.sh` passes the default Cordium Service and nested
  workspace TLS checks. The existing nested-wildcard Cloudflare TLS finding is
  an independent blocker if it remains unresolved.

## Rollback Gate

Trigger rollback on a failed Genesis Job, readiness timeout, wrong version,
lost front-proxy state, API/Session/policy/Service regression, Enterprise
console or access failure, or Cordium lifecycle failure. Stop before the next
phase.

Do not run an older Genesis image as a downgrade: upstream documents upgrade,
not rollback or downgrade. Restore the checkpoint taken immediately before the
failed phase while writers are fenced, restore the matching old repository
revision/manifests/digests, then rerun that phase's acceptance gates. Take
checkpoints before core, after core/before Enterprise, and after
Enterprise/before Cordium so a later package failure does not automatically
discard a healthy earlier upgrade.

Rollback is not currently executable because the repository does not record a
successful isolated PostgreSQL restore drill or coordinated Redis/Enterprise
store restore. This is a release blocker, not a post-upgrade verification item.

## Primary Artifact Check

Verified against GHCR on 2026-08-29. The requested target tags exist as
multi-architecture Linux images for `amd64` and `arm64`:

| Artifact | Target digest |
| --- | --- |
| `ghcr.io/octelium/octelium:0.40.0` | `sha256:02f24f884899ce74d43909c09ca4416b362b5eeb9411ed2f5cf45dedcd595e11` |
| `ghcr.io/octelium/octelium-genesis:0.40.0` | `sha256:fc9f4e74c60aeb5c8b22ab9245373b3d1986fb57e28875d799279ca2aa12a3cf` |
| `ghcr.io/octelium/octeliumee-genesis:0.29.0` | `sha256:6b16176b5a850c5a2409f84892f0f9845e9f9c64524eeec626c5cf6bb5b60af6` |
| `ghcr.io/octelium/cordium:0.13.1` | `sha256:00cf2ce3217fa885ffba9ed7511fa9d12cec8dbab03a14dd1db535f0d245add7` |
| `ghcr.io/octelium/cordium-genesis:0.13.1` | `sha256:ea9bf15fc5ad02c9694defaf9de5bdeb93c4e827bceb6687444f4f68a9371087` |

All production component image families referenced by the target core,
Enterprise, and Cordium generators also expose the requested target tags. Pin
the exact generated set during recapture rather than copying this sample list.
[Core Genesis package](https://github.com/octelium/octelium/pkgs/container/octelium-genesis)
[Enterprise Genesis package](https://github.com/octelium/octelium-ee/pkgs/container/octeliumee-genesis)
[Cordium Genesis package](https://github.com/octelium/cordium/pkgs/container/cordium-genesis)

## Blocking Work

1. Obtain an upstream-supported migration or fix for existing front-proxy
   clusters upgrading to `0.40.0`, then encode it in repository-owned desired
   state. Do not invent a live status or database patch.
2. Fix the separate fresh-install bootstrap contract and prove its rendered
   front-proxy Service and environment.
3. Prove PostgreSQL restore and define coordinated recovery for Redis and the
   three Enterprise stores.
4. Decide metricstore v1 disposition: supported migration/export-import, or an
   approved reset with `store.db` archived and history-loss acceptance.
5. Recover and directly validate the native dataplane fleet for 24 hours, or
   define an atomic phase-aligned transition for all 26 emergency fallbacks.
6. Encode a staged Argo CD transition so self-heal cannot revert generator
   output while manifests are recaptured.
7. Define a one-shot Cordium upgrade path distinct from its permanent fresh
   `init` bootstrap, then prove the complete target tuple through workspace and
   nested-access smoke tests.
8. Resolve or explicitly gate the known nested-workspace wildcard TLS failure.

Until items 1-7 are complete, code staging would create a rollout that is
neither topology-safe, version-coherent, nor recoverable.
