# Wazuh SIEM

Tags: #security #logging #wazuh #operations

Source: [Wazuh runbook](../../../clusters/homelab/apps/wazuh/README.md),
`IaC/terragrunt.stack.hcl`, `scripts/wazuh-{preflight,talos,verify}.py`.

Wazuh 4.14.8 plus Fluent Bit 5.1.3 is declared but **not deployed**. Automated
sync is disabled. On 2026-10-03 read-only inspection after the Langfuse memory
reservation found all four nodes Ready and only 2.82GiB unreserved on `acer`.
Wazuh and its collectors request 7.12GiB there plus 1GiB operating headroom:
the current capacity shortfall is 5.30GiB. Capacity must be added or specific
existing workloads moved before activation. `acer`
has about 397GiB disk free, but local-volume capacity is not a quota.

Declared sources: all namespaces' container output, existing Metadata audit
files, Kubernetes events, and Talos service/kernel JSON. Full archives are
indexed in addition to alerts. Fleet osquery and Istio access logs already use
stdout. Collector self-diagnostics are excluded to prevent feedback; queues
and record sizes are finite. Oversized admitted events require lossless
fragmentation before Wazuh's 64KiB syslog limit.

NOFX's pinned logger already duplicates its file output to stdout; OctoBot
console DEBUG and ClickHouse console trace are now declared to match their file
logs. Actual reconciliation and source proof remain pending.
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

Acceptance still requires protected merge, capacity, prerequisites, image
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
