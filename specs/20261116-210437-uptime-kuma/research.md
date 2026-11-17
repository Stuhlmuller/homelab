# Research decisions

All research was read-only. These decisions constrain implementation; they do
not claim a working deployment or image publication.

## Version and native adapter

Decision: pin Uptime Kuma 2.5.11, released 2026-11-12, revision
`4433aba09a1a4cf8ec13141f2a73436ab87a2366`. Docker Registry v2 returned manifest
index digest `sha256:7554dba313c84e44fee921ef3b5626ba1c711e412e82815e8c957517026112a9`
with linux amd64/arm64/arm images and attached attestations. Preserve index
coverage through the protected publisher. Resolve any publisher incompatibility
without silently dropping provenance.

The research subagent inspected pinned server handlers and dependencies; the
planning owner independently inspected Dockerfile, server config, database and
setup code. Sources:

- [Release](https://github.com/louislam/uptime-kuma/releases/tag/2.5.11)
- [package.json](https://github.com/louislam/uptime-kuma/blob/4433aba09a1a4cf8ec13141f2a73436ab87a2366/package.json)
- [Native Socket.IO handlers](https://github.com/louislam/uptime-kuma/blob/4433aba09a1a4cf8ec13141f2a73436ab87a2366/server/server.js)
- [Container build](https://github.com/louislam/uptime-kuma/blob/4433aba09a1a4cf8ec13141f2a73436ab87a2366/docker/dockerfile)
- [Server CLI config](https://github.com/louislam/uptime-kuma/blob/4433aba09a1a4cf8ec13141f2a73436ab87a2366/server/config.js)
- [Database setup](https://github.com/louislam/uptime-kuma/blob/4433aba09a1a4cf8ec13141f2a73436ab87a2366/server/setup-database.js)

Rationale: production dependencies include socket.io-client ~4.8.3; the server
supports `--host`, `--port`, and `--data-dir`. An init can privately initialize
through the same native interface without direct application SQL writes or
external clients. Native events are version-sensitive and must be integration
tested. Reject a third-party operator, Python client, live UI-only provisioning
or direct database configuration writes: these add dependencies or bypass the
app's semantics. `db-config.json` is supported file-backed DB selection.

## Existing signals and coverage

Decision: direct backend health checks where meaningful, otherwise native
`json-query` using JSONata against existing Prometheus metrics. Evidence:
[monitor implementation](https://github.com/louislam/uptime-kuma/blob/4433aba09a1a4cf8ec13141f2a73436ab87a2366/server/model/monitor.js)
and local `clusters/homelab/apps/grafana/README.md` workload/probe rules.

Use a primitive JSONata result:
`(status = "success" and $count(data.result) = 1 and data.result[0].value[1] = "1") ? "1" : "0"`.
Source freshness is bounded by twice the actual configured source observation
period, including periods below 60 seconds; record configuration evidence in
the catalog. It belongs inside PromQL; the instant-query response timestamp is
query time and cannot establish scrape freshness. No custom health HTTP bridge
or new Kubernetes watcher is needed. Do not equate scrape availability to
healthy target state. Health paths and component selectors are catalog data,
verified against source and live endpoints during implementation.

Observed baseline: 55 source app directories and 56 live Applications, union
60. A live `Healthy` state may coexist with zero replicas; stopped and staged
entries require explicit evidence. This is why the catalog validates lifecycle
classification instead of generating blind probes from every Service.

## Storage and recovery

Decision: local SQLite with Recreate, online SQLite backup and NFS archives.
[README](https://github.com/louislam/uptime-kuma/blob/4433aba09a1a4cf8ec13141f2a73436ab87a2366/README.md)
explicitly disallows NFS active storage.
[database.js](https://github.com/louislam/uptime-kuma/blob/4433aba09a1a4cf8ec13141f2a73436ab87a2366/server/database.js)
uses WAL and graceful checkpointing. Existing Bazarr local-storage and backup
patterns show repository support for retained local data and checked archives.
Acer has the largest observed allocatable resource capacity; actual scheduling
headroom is a rollout check, not inferred from capacity alone.

Reject a new MariaDB service: SQLite is sufficient for this bounded inventory
and avoids a second database lifecycle. Reject plain live-file copy and NFS
SQLite because neither is a safe backup/runtime contract. Set
`keepDataPeriodDays=30`; see pinned `server/jobs/clear-old-data.js`.

## Access, secrets and delivery

Decision: `monitoring` namespace and existing `homelab` project, which already
permits its destination and PV/StorageClass resources. `homelab-workloads` lacks
monitoring and cluster resources; widening it adds no value here. Current
Traefik README/routes, rather than older Octelium-default prose, own private
app routing. Existing SSM store already permits monitoring; shared catalog
supports generated password entries and exact reader grants.

`scripts/ci/terragrunt-apply.sh` has an explicit targeted prerequisite lane for
secret-bearing apps. Kuma must join that lane with its exact namespace/storage
checks rather than assuming Application registration creates SSM values.
Image skill requires catalog/publication before consuming source; implement a
fixed Kuma scope with negative tests rather than publishing unrelated catalog
entries or bypassing strict mirrors.

## XERJ and workflow coverage

XERJ MCP tools and installed CLI were unavailable in this cloud environment;
no node/corpus was installed or indexed. This is a recorded reference-search
limitation, not a claim that XERJ searched successfully. Inspected the pinned
`homelab-peer` recursive tree at `1b88ad5c211113d0526a676aa26cdcd8282644ff`:
no Kuma path; read its pinned
[Grafana chart generator](https://github.com/kn-lim/homelab/blob/1b88ad5c211113d0526a676aa26cdcd8282644ff/kubernetes/bases/grafana/helm-chart/helm-chart.yaml).
It confirms pinned upstream chart ownership, but supplies no Kuma-specific
adapter. Local app-template conventions and official Kuma source govern design.
No peer code copied. Peer manifest records reviewed Unlicense.

Invoked installed `speckit-plan`, executed `setup_plan.py --json`, and read
upstream `templates/commands/plan.md` at the Spec Kit revision recorded in
checkpoint.md. Empty hooks apply. All design unknowns resolved; exact catalog
endpoints and pinned-image execution are implementation validation, not claimed
research results.

## Image prerequisite execution evidence (2026-11-17)

The exact Kuma index above executed locally with network disabled: Node
22.23.5, bundled socket.io-client 4.8.4, @louislam/sqlite3 15.1.6 using
SQLite 3.41.1. The package-range research was not an installed-version claim.
The same image includes Python 3.11.2 with SQLite 3.40.1 and the standard
Connection.backup API. Use this same pinned image for backup/restore jobs;
no additional helper image or runtime dependency installation is required.
Cross-binding live-WAL backup correctness remains an explicit integration test.

The base GitHub CLI lacks --slurp; the repository Nix environment supplies the
supported CLI. Nix execution requires the approved sandbox escalation here.


## P1 repair: restore execution fencing before native startup

Separate narrow plan-repair turn, 2026-11-17. Reused spec/constitution and invoked
installed setup_plan.py; it preserved the existing plan. No extension hooks.
No production/source implementation or database modification occurred here.

**Finding:** a deny-all NetworkPolicy does not establish actual isolation on the
current Flannel cluster. `clusters/homelab/platform/network-policy/README.md`
lines 3–11 describe the separate kube-router enforcer as staged, and its source
DaemonSet selects only a canary. The restore Job must not depend on that future
platform outcome or use the production monitor identity.

**Pinned evidence**, upstream revision
`4433aba09a1a4cf8ec13141f2a73436ab87a2366`:

- [server.js](https://github.com/louislam/uptime-kuma/blob/4433aba09a1a4cf8ec13141f2a73436ab87a2366/server/server.js)
  lines 1779–1788 start active monitors, background jobs, update polling and
  cloudflared after listener setup; lines 1956–1970 select monitor.active=1.
  Setting the HTTP listener to loopback does not disable these outbound actions.
- [check-version.js](https://github.com/louislam/uptime-kuma/blob/4433aba09a1a4cf8ec13141f2a73436ab87a2366/server/check-version.js)
  `startInterval` immediately checks for updates unless `setting("checkUpdate")`
  is the boolean false. The value is not merely a string comparison.
- [cloudflared handler](https://github.com/louislam/uptime-kuma/blob/4433aba09a1a4cf8ec13141f2a73436ab87a2366/server/socket-handlers/cloudflared-socket-handler.js)
  `autoStart` falls back to cloudflaredTunnelToken; argv/environment tokens can
  override stored state. Empty stored token plus no override prevents launch.
- [settings.js](https://github.com/louislam/uptime-kuma/blob/4433aba09a1a4cf8ec13141f2a73436ab87a2366/server/settings.js)
  reads `setting.value` with JSON.parse and writes JSON.stringify. The fence must
  store false and empty string as JSON and independently decode/check them.
- [uptime-kuma-server.js](https://github.com/louislam/uptime-kuma/blob/4433aba09a1a4cf8ec13141f2a73436ab87a2366/server/uptime-kuma-server.js)
  `start` attempts NSCD service startup unless nscd is false; disable it in the
  clone. Maintenance loads stored schedules; deactivate clone maintenance too.
- [jobs.js](https://github.com/louislam/uptime-kuma/blob/4433aba09a1a4cf8ec13141f2a73436ab87a2366/server/jobs.js)
  contains local history cleanup/vacuum. Archive and pre-fence history evidence
  remain untouched; required history loss during native verification fails.
- Read-only PRAGMA inspection of the existing disposable pinned-image test DB
  confirms monitor(id,active,user_id), notification(id,active,is_default,user_id,
  config), monitor_notification(id,monitor_id,notification_id), maintenance(id,
  active), and setting(id,key,value,type). Activation fields are BOOLEAN; key
  and value are text-like. No credential values were read or printed.

**Decision:** validate the unchanged archive and record original identity/history
before an offline transaction fences only its ephemeral clone. Pause all monitors,
disable notification/default and maintenance activation, remove notification
bindings, and set checkUpdate/nscd false and cloudflaredTunnelToken empty. Require
pinned schema and unique setting keys, then independent postcondition checks
before starting any native process. Keep all other monitor/account/history data
and the original archive intact. Use only native login/read operations afterward;
never bootstrap or reconcile the clone. A separate service account, loopback
listener and declared deny-all policies add defense but are not described as a
general network sandbox. Child process environment is explicitly allowlisted.

**Alternatives rejected:** NetworkPolicy-only isolation lacks enforcement;
pausing via Socket.IO after startup races immediately resumed probes; monitor
flags alone miss updater/tunnel startup; changing cluster-wide CNI is unrelated
scope. Modifying the production DB or backup archive is prohibited. Replacing
native account/history proof with checksum-only verification loses acceptance.

**Required proof:** network-enabled positive/negative probe and notification
fixtures, pinned updater/tunnel guard tests with observable call/launch counters,
pre-start failure injection, unchanged archive and original identity/history,
and dedicated Job identity/mount assertions. The old network-none integration
is useful storage evidence but is not proof of this repair. Exact details are
in quickstart.md and contracts/native-api.md. No repaired implementation or live
safety is claimed by this design checkpoint.
