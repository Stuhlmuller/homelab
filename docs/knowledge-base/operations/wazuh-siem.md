# Wazuh SIEM

Tags: #security #logging #wazuh #operations

Source: [Wazuh runbook](../../../clusters/homelab/apps/wazuh/README.md),
`IaC/terragrunt.stack.hcl`, `scripts/wazuh-{preflight,talos,verify}.py`.

Wazuh 4.14.8 plus Fluent Bit 5.1.3 merged in
[PR #1153](https://github.com/Stuhlmuller/homelab/pull/1153), but the runtime is
**not deployed** and automated sync is disabled. On 2026-10-04 read-only
inspection after the Langfuse memory reservation found all four nodes Ready
and only 2.82GiB unreserved on `acer`.
Wazuh and its collectors request 7.12GiB there plus 1GiB operating headroom:
the current capacity shortfall is 5.30GiB. The existing nodes together also lack
about 3.20GiB of unreserved memory for Wazuh plus headroom; moving workloads
between them cannot close that gap. Add capacity or obtain the operator's
selection of workloads to retire before activation. `acer` has about 394GiB
disk free, but local-volume capacity is not a quota.

The logging rollout required
[PR #1167](https://github.com/Stuhlmuller/homelab/pull/1167) to put ClickHouse's
generated ConfigMap before its Deployment sync wave. Argo's existing 900-second
timeout released the stale operation; Langfuse recovered Healthy/Synced at
`0ad30199`. OctoBot's mounted console and file levels were both verified DEBUG,
with console output directed to stdout. These prove source configuration and
recovery, not Wazuh ingestion.

On 2026-10-04 at 07:53:55 UTC, Kubernetes evicted a Langfuse ClickHouse Pod
from `zimaboard-1` for ephemeral-storage pressure: available `3759652Ki`, below
the `4333555065`-byte threshold. Pod status also records an earlier eviction
there on October 3. Kubernetes rescheduled the replacement onto `zimaboard-0`;
it was Ready with zero restarts and Langfuse was Healthy/Synced at 07:55:46 UTC.
This does not establish that `zimaboard-1` disk pressure is fixed. Before Wazuh
activation, check free disk, image usage and room for each persistent 2GiB
collector queue on every node; `acer` capacity alone is insufficient evidence.

Declared sources: all namespaces' container output, existing Metadata audit
files, Kubernetes events, and Talos service/kernel JSON. Full archives are
indexed in addition to alerts. Fleet osquery and Istio access logs already use
stdout. Collector self-diagnostics are excluded to prevent feedback; queues
and record sizes are finite. Oversized admitted events require lossless
fragmentation before Wazuh's 64KiB syslog limit.

NOFX's pinned logger already duplicates its file output to stdout; OctoBot
console DEBUG and ClickHouse console trace match their file logs. Both mounted
configurations were verified after reconciliation; Wazuh source receipts remain
pending.
Outstanding source coverage: NAS/Plex and network appliances; conventional
endpoint agents; OpenClaw private doctor reports; Octelium's native security
logstore. Wazuh API JSON is collected natively; manager/indexer console
streams require live verification. Native JVM GC/fatal reports now route to
stdout, verified with isolated local Java processes; heap dumps remain local
and are excluded from collection. Add a scoped declared export per source.
Do not treat database contents or AI conversation stores as generic logs.

Talos authenticated read-only checks confirmed v1.11.3, a catch-all Metadata
audit policy, and `vm.max_map_count=65530` on `acer`. The repository helper
strictly validates indexer/logging changes, preserves unrelated configuration,
and gates execution on reviewed current main, node readiness and no reboot.
No Talos settings have been applied for Wazuh.
Manager startup copies API TLS files into private ephemeral `wazuh`-owned
files and checks their keypair before starting daemons. Projected Secrets stay
read-only; leaf renewal requires a reviewed Pod revision and ingestion readback.

Acceptance still requires capacity, prerequisites, image
publication, Wazuh sync, Talos forwarding, private UI login, recent per-source
and per-node index counts, canary in both archives/alerts, first backup and an
isolated restore. No live ingestion, backup or restore success is claimed.
Declared snapshot retention keeps 14 days and at least three successful snapshots;
deletion requires a new success and API acknowledgement/readback. Raw archive
pruning and full manager-state backup remain separate gates.

## External-source preflight (2026-10-03)

Read-only checks used the documented NAS address and existing authenticated SSH
access. No settings were changed and no log contents were read.

- QNAP runs QTS 5.2.10, build date 20260731, with QuLog 1.8.2.956 enabled.
  Its installed UI exposes `/qulog/v1/rsyslog/client` destination CRUD and
  `/qulog/v1/rsyslog/client/config` sender settings. Unauthenticated requests
  return HTTP 200 with application `error_code:401`: status alone is not success.
  API authentication and delegated configuration rights remain unproven.
  Add a version-checked repository operator path preserving existing destinations,
  retention and volume settings, with readback and rollback, before enabling
  [native event/access forwarding](https://docs.qnap.com/operating-system/qts/5.2.x/en-us/configuring-log-sender-settings-66DE0C94.html).
- Named QuLog access masks for SAMBA, NFS, HTTPS and WebDAV were zero.
  Sending existing logs alone does not cover those access categories. Verify
  service support and enable the relevant categories through the same declared path.
- Plex's package was enabled and its `Library/Plex Media Server/Logs` directory
  existed under `/share/CACHEDEV2_DATA/.qpkg/PlexMediaServer`, but TCP 32400 refused
  connections. Directory mode was `0777`, owner `admin:administrators`: any local
  writer can modify log files. Verify intended Plex ownership and add a reviewed
  permission repair before claiming log integrity. QuLog's packaged rsyslog has
  no `imfile.so`; a separate supported, narrowly scoped file-forwarder is needed.
- The gateway HTTP page identifies Xfinity; exact model, firmware and remote-log
  export capability remain unknown. No managed switch/AP models or logging
  endpoints were found in repository docs. Inventory these before promising export.

Source context: [NAS inventory](../../../docs/storage-nfs.md),
[[qnap-monitoring-block-storage-research-2026-09-12]], and read-only named
configuration fields plus QuLog's installed `/mnt/ext/opt/QuLog/opt/www/app.js`.

Related: [[../architecture/gitops-flow]], [[../architecture/storage-and-state]],
[[../architecture/secrets-and-identity]], [[../workloads/inventory]].
