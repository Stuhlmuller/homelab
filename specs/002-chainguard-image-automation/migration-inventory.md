# Initial migration assessment

<!-- markdownlint-configure-file { "MD013": { "tables": false } } -->

This remains a partial implementation inventory; no live migration evidence has
been claimed. Research date:
2026-10-05 local / 2026-10-06 UTC; repository baseline
`a13975cca42873f490e105b095981d13ee5837cc`.

## Read-only runtime snapshot

On 2026-10-05, `kubectl get pods -A -o json` was inspected from context
`admin@homelab` without changing cluster state. The snapshot contained 287 Pods,
365 container or init-container entries, and 127 unique image references; 74
unique references included immutable `sha256` digests. The following exact
runtime consumers are the Chainguard candidates currently visible in the
cluster. Desired-state paths remain the source of truth for migration.

| Candidate | Runtime reference and child digest | Resource/container evidence | Owner and next evidence |
| --- | --- | --- | --- |
| Python exporter | `docker.io/library/python:3.14.7-alpine3.23@sha256:218761489de417a6eb0808e264cbdd7043ec6659fe5a61898815e9848536541d` | `harbor/harbor-vulnerability-exporter-65f4b87bcd-58hq7:exporter`; `clusters/homelab/apps/harbor/vulnerability-exporter.yaml` | Harbor app owner; publish and verify UID 65532, CA trust, `/livez`, `/metrics`, and scrape before changing the reference. |
| Kiali curl init | `curlimages/curl:8.22.0@sha256:58adaa4e8dca9c988bae2aba4ab3434a0bb2da16bbe3f92dec39ec7785166777` | `monitoring/kiali-69964c44f5-snd7d:wait-for-prometheus`; `clusters/homelab/apps/kiali/values.yaml` | Kiali owner; publish Chainguard curl, replace the shell loop with direct retry arguments, and prove readiness timeout/failure behavior. |
| BusyBox helpers | `busybox:1.38.0@sha256:fd7dc98638c8e305f4dc34e979f1c0fdfdcaeb0fbf8fcff77ae834b6da3d7e6e` | `cordium/cordium-user-namespace-sysctl-tf4vg:enable-user-namespaces`; `media/bazarr-b969764db-jqg8p:prepare-config`; additional backup and init containers | Per-app owners; verify applets, root/sysctl/chown behavior, and QNAP ownership before any substitution. |
| Redis | `redis:7.2.16-alpine@sha256:29e8589c3f9ba699b5f7aa4b3c7733c58852a3626439e619aa0ee78de08c6ca0` | `fleet/fleet-redis-0:redis`; `clusters/homelab/apps/fleet/redis.yaml` | Fleet owner; prove ACL/password files, `/data`, persistence, and client behavior. |
| Valkey | `docker.io/valkey/valkey:8.0@sha256:4436c94fc34ce4af0354b9379d433a1f258998fb955f995c89822f98c14a8cab` | `langfuse/langfuse-valkey-7947dc4f5c-9xzdl:valkey`; `clusters/homelab/apps/langfuse/datastores.yaml` | Langfuse owner; prove version, persistence, clients, and rollback data safety. |
| PostgreSQL | `docker.io/library/postgres:18.6-bookworm@sha256:3725f4e2499eef5134592b3b4ab79a543ed7f8e533b05b5b637af926630f6650` | `harbor/harbor-postgres-0:postgres`; `clusters/homelab/apps/harbor/postgres.yaml` | Harbor platform owner; major-version, collation, extension, backup, and rollback evidence required. |
| pgvector | `pgvector/pgvector:pg17@sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d` | `ai/multica-postgres-7c6894c7c-d5pbb:postgres`; `langfuse/langfuse-postgres-64d488d646-bzpz6:postgres` | Application owners; separate pgvector package and ABI evidence required; plain PostgreSQL is not equivalent. |

The remaining 120 runtime references are platform, coupled application, or
custom-build rows already covered by the family matrix below. They remain
unmigrated until their exact package, access, and recovery evidence is recorded;
the snapshot does not claim compatibility or publication.

## Coverage and completion rule

The repaired `scripts/harbor-image-inventory.py` declaration scan emits 85
named references across 76 repository families, plus seven digest-only chart
pins the helper does not resolve: five cert-manager components, local-path
provisioner and a BusyBox pin. Existing catalog digests can resolve those names.

The checked-in automation enrollment currently contains the public Chainguard
Python pilot with active public import and consumer enrollment paused. This is
not the active workload denominator.
Implementation must repair the
parser, render the pinned charts in `scripts/config/harbor-image-charts.json`,
collect read-only runtime images, and reconcile declarations, hooks, init
containers, sidecars and operator-generated Pods. Each actual consumer gets an
assessment keyed by application/resource/container, source digest, update owner,
evidence and reconsideration condition. Historical catalog entries alone do
not define scope. Completion requires zero unassessed active consumers.

## Candidate and exception matrix

“Candidate” means access/packaging supports a runtime test, not that compatibility
has passed. Anonymous HTTP 403 means unavailable anonymously; organization
entitlement was not inspected. “No equivalent confirmed” is not proof no offering
exists. All exceptions retain their current digest and update owner, normally
Renovate or the upstream chart/platform owner.

Track migration and automation eligibility separately. A compatible accessible
image must migrate even when its existing reviewed owner is retained because
Image Updater cannot address the consumer. That limitation is an automation
exception only, not a migration exception.

| Family / consumers | Assessment | Required evidence or reconsideration condition |
| --- | --- | --- |
| Python: Harbor vulnerability exporter | First migration candidate | Public `python:latest`; UID/GID 65532, `python3 -I -B`, stdlib, read-only root and no PVC align. Verify imports, CA trust, `/livez`, `/metrics` and original Prometheus scrape. |
| Python: Harbor/Fleet bootstrap | Candidate after exporter | Same public package; test complete bootstrap behavior and file-mounted credentials, with idempotent reconciliation. |
| Python: Multica runtime/init | Startup exception | Init needs Bash, curl, sha256sum, tar, cp and mkdir; runtime needs downloaded native `/tools/multica`. Resolve utility/loader contract before substituting minimal Python. |
| BusyBox: media, backup, Grafana init, Cordium sysctl, storage helpers | Candidate per consumer | Public image defaults UID 65532, uses glibc and includes shell. Verify applets, root/chown/sysctl cases, QNAP UID 65534/1000 and copy/tar behavior. |
| curl: Kiali readiness init | Candidate with a small migration path | Candidate is enrolled in the paused automation contract as `chainguard-curl`; replace the shell/sleep loop with direct curl retry arguments after Harbor publication, then test timeout/failure semantics. Do not select `latest-dev`. |
| Cosign: Harbor signing template | Migration candidate; updater-enrollment exception | Public binary/user align; test existing key and legacy bundle commands. If compatible, publish and migrate its reference through the existing protected signing/publication path. Keep that update owner because the CI-created Pod is not an Argo target; do not use this automation limitation to defer a compatible image migration. |
| kubectl: Cordium cleanup | Version-skew exception | Current public package 1.37.1 versus repository Kubernetes 1.34.11. Reconsider with a supported client/server pairing; no silent major cap. |
| PostgreSQL: media/n8n/Harbor/Fleet/Octelium/AI and backup clients | Stateful migration candidate | Public package PG 18.6 versus PG 14/17 consumers; UID 70 data ownership, default User 0, entrypoint and PGDATA differ. Prove major migration, collation/reindex, extensions, init scripts, backup/restore and rollback compatibility per consumer. |
| pgvector: Affine/AI/vector datastores | Entitlement/extension exception | Separate pgvector offering; establish access, extension version and PostgreSQL ABI/data compatibility. Plain PostgreSQL is not equivalent. |
| Redis: Fleet/Octelium/Affine/AI | Stateful candidate | Public 8.10.2 includes BusyBox and redis-cli. Verify ACL/password-file usage, UID 65534, `/data`, clients and persistence compatibility. |
| Valkey: directly declared datastore | Stateful candidate | Public 9.1.2 versus current 8.0; UID 65532 and `/data`. Prove data/client behavior. Harbor's `valkey-photon` remains a separate coupled component. |
| MySQL: Fleet | Access and data exception | Anonymous candidate pull 403. Establish actual access, correct MySQL version, UID/data path, SQL upgrade and recovery; MariaDB is not a name-based substitute. |
| ClickHouse: Langfuse | Mapping/access exception | Establish exact offering and entitlement; preserve version, schema/query behavior, mounts and backups. |
| Harbor core/exporter/jobservice/portal/registryctl/nginx-photon/registry-photon/trivy-adapter-photon/valkey-photon | Coupled platform/access exception | Map all chart components and versions together; preserve database/blob state and cold bootstrap. Generic nginx/registry/Valkey are not verified replacements. |
| Envoy / Cloudflared | Access exception | Anonymous pulls returned 403. Verify entitlement, entrypoint/configuration, routing and recovery dependencies before migration. |
| Grafana | Access/state exception | Anonymous pull 403. Verify plugins, SQLite upgrade/backup, UID/data paths, SSO, dashboards and queries. |
| Prometheus/operator/config-reloader/Alertmanager/Thanos/kube-state-metrics | Render/access/coherence gate | Public Prometheus pull 403. Complete generated-Pod inventory, CRD/controller/sidecar mapping, reload, TSDB, scrape and alert acceptance. |
| Argo CD/Dex/Redis chart dependencies | Render/access/bootstrap gate | Confirm package split and every binary/override; preserve repo-server/plugins/init and GitOps recovery. |
| Cert-manager's five components | Digest resolution/access/coherence gate | Resolve current pins; include dynamic ACME solver Pods and startup hook. Prove chart/CRD coherence and certificate renewal. |
| External Secrets | Access/coherence gate | Offering exists; establish entitlement and controller/webhook/cert-controller mapping compatible with chart/CRDs. |
| Istio pilot/proxyv2/install-cni/ztunnel | Coupled platform/access exception | Include injected proxies and privileged CNI. Require coordinated version, network and recovery acceptance. |
| Kiali/operator | Mapping/access gate | Offering exists; verify operator CR mapping, generated deployment, UID 1000 and `/opt/kiali/kiali`. Curl init assessed separately. |
| Tailscale operator/proxy | Access/generated-Pod gate | Offering exists; map both operator and `proxyConfig.image.repository`; test kernel/userspace networking. |
| Metrics-server/descheduler/crossplane/webhook-certgen | Render/mapping/access gate | Metrics-server offering confirmed; verify other exact mappings, hooks, Kubernetes API/CRD compatibility. |
| Local-path/NFS provisioners | Mapping/storage gate | Include helper Pods, QNAP all-squash behavior, provisioning/deletion lifecycle and path protection. NFS offering confirmed. |
| Talos-managed Kubernetes components, CoreDNS, etcd, flannel, pause | Platform ownership exception | Talos supplies/version-locks images. Reconsider only with a supported coordinated version/skew/privilege/bootstrap path. |
| LinuxServer Bazarr/Deluge/Prowlarr/Radarr/Sonarr | No equivalent confirmed | Preserve `/init`, s6, `/lsiopy/bin/python3`, PUID/PGID, extensions and mounts. Reconsider after exact package and original-action acceptance. |
| Gluetun / UPnP helper | No equivalent confirmed | Preserve VPN/firewall and UPnP executable contracts; require exact mapping and network acceptance. |
| Octelium/OcteliumEE/Cordium, every component | No equivalent confirmed | Preserve privileged gateways, agents, init and generated Pods; require exact application packages. |
| Compass/OctoBot/FleetDM/policy-bot/podinfo | No equivalent confirmed | Verify actual app identity and original action. Rancher Fleet and Elastic fleet-server are not FleetDM. |
| Langfuse web/worker, LiteLLM database image, Dispatcharr, Multica backend/web, n8n, OpenClaw, Affine | No equivalent confirmed | Packaged application code, extensions and migrations are required. A Python/Node base image alone is not an application replacement. |
| Private NOFX backend/frontend | Custom build exception | Preserve private project and signing/build contract. Rebuilding on a new base is separate work. |
| Nix runner | Toolchain exception | Preserve Nix/tool availability; reconsider with an identified complete runtime replacement. |

## Research evidence

Anonymous latest manifests were readable for Python, BusyBox, Redis, curl,
Cosign, PostgreSQL, Valkey and kubectl; inspected indexes covered linux/amd64
and linux/arm64. This verifies access/platform metadata, not runtime behavior.
Version observations are a dated snapshot; resolve immutable digests again
during implementation.

- [Public build definitions](https://github.com/chainguard-images/images/tree/main/images)
  identify package contents, users, entrypoints and current version locks.
- [Registry access](https://edu.chainguard.dev/chainguard/containers/registry/overview/)
  distinguishes public access and production entitlements.
- [Python](https://images.chainguard.dev/directory/image/python/overview),
  [BusyBox](https://images.chainguard.dev/directory/image/busybox/overview),
  [curl](https://images.chainguard.dev/directory/image/curl/overview),
  [PostgreSQL](https://images.chainguard.dev/directory/image/postgres/overview)
  and [pgvector](https://images.chainguard.dev/directory/image/pgvector/overview)
  describe the candidate packages.
- [External Secrets](https://images.chainguard.dev/directory/image/external-secrets/overview),
  [Tailscale](https://images.chainguard.dev/directory/image/tailscale/overview),
  [Kiali](https://images.chainguard.dev/directory/image/kiali/overview),
  [metrics-server](https://images.chainguard.dev/directory/image/metrics-server/overview)
  and [NFS provisioner](https://images.chainguard.dev/directory/image/nfs-subdir-external-provisioner/specifications)
  establish offerings, not this homelab's entitlement or compatibility.
