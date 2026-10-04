# Wazuh SIEM

Tags: #security #logging #wazuh #operations

Source: [Wazuh runbook](../../../clusters/homelab/apps/wazuh/README.md),
`IaC/terragrunt.stack.hcl`, `scripts/wazuh-{preflight,talos,verify}.py`.

Wazuh 4.14.8 plus Fluent Bit 5.1.3 merged in
[PR #1153](https://github.com/Stuhlmuller/homelab/pull/1153), but the runtime is
**not deployed** and automated sync is disabled. The capacity gate remains
blocked. Wazuh and its collectors request 7.12GiB on the central node plus
1GiB operating headroom. Moving workloads among existing nodes cannot resolve
an aggregate memory deficit. Add capacity or obtain the operator's selection
of workloads to retire before activation. Declared local-volume capacity is
not a filesystem quota.

The logging rollout required
[PR #1167](https://github.com/Stuhlmuller/homelab/pull/1167) to put ClickHouse's
generated ConfigMap before its Deployment sync wave. The console logging
configuration was verified after reconciliation. Source configuration does
not establish Wazuh ingestion.

[Protected staging run 37186920139](https://github.com/Stuhlmuller/homelab/actions/runs/37186920139)
succeeded at `0ad30199`: its ordered apply reconciles the four generated SSM
credential declarations before registering the Application. Live readback
confirmed `wazuh` targets `main`, `automated.enabled=false`, no active operation,
and no runtime namespace. Secret values were not read or displayed.

Before activation, check free disk, image usage and room for each persistent
2GiB collector queue on every node. The read-only preflight uses each kubelet's
eviction configuration and node/image filesystem statistics, reserves
queue/image/inode growth, and fails closed on missing statistics or
DiskPressure. A False DiskPressure condition alone does not establish enough
space for the new collector. Follow the canonical
[rollout gate](../../../clusters/homelab/apps/wazuh/README.md#rollout).

[Image publication attempt 1](https://github.com/Stuhlmuller/homelab/actions/runs/37186918652/attempts/1)
failed; verified publication remains an activation prerequisite. Re-run the
repository's protected publication workflow and require successful copy and
anonymous pull verification before activation. Keep detailed live diagnostics
outside this public repository.

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

The repository helper strictly validates Talos indexer/logging changes,
preserves unrelated configuration,
and gates execution on reviewed current main, node readiness and no reboot.
No Talos settings have been applied for Wazuh.
Manager startup copies API TLS files into private ephemeral `wazuh`-owned
files and checks their keypair before starting daemons. Projected Secrets stay
read-only; leaf renewal requires a reviewed Pod revision and ingestion readback.

Runtime acceptance requires capacity, prerequisites, verified image
publication, Wazuh sync, Talos forwarding, private UI login, recent per-source
and per-node index counts, canary in both archives/alerts, first backup and an
isolated restore. No live ingestion, backup or restore success is claimed.
Declared snapshot retention keeps 14 days and at least three successful snapshots;
deletion requires a new success and API acknowledgement/readback. Raw archive
pruning and full manager-state backup remain separate gates.

## External-source activation requirements

- Add a version-checked QNAP operator path preserving existing destinations,
  retention and volume settings, with authenticated readback and rollback,
  before enabling
  [native event/access forwarding](https://docs.qnap.com/operating-system/qts/5.2.x/en-us/configuring-log-sender-settings-66DE0C94.html).
- Verify QuLog service support and enable the relevant access-log categories
  through that declared path; forwarding alone does not enable log production.
- Verify Plex availability and log ownership before claiming coverage or log
  integrity. Add a reviewed permission repair when needed and a supported,
  narrowly scoped file forwarder.
- Inventory gateway, switch and access-point models and their supported log
  export mechanisms before promising network-appliance coverage.

Source context: [NAS inventory](../../../docs/storage-nfs.md),
[[qnap-monitoring-block-storage-research-2026-09-12]].

Related: [[../architecture/gitops-flow]], [[../architecture/storage-and-state]],
[[../architecture/secrets-and-identity]], [[../workloads/inventory]].
