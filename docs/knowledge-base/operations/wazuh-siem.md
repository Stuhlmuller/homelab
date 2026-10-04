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
streams require live verification. Add a scoped declared export per source.
Do not treat database contents or AI conversation stores as generic logs.

Talos authenticated read-only checks confirmed v1.11.3, a catch-all Metadata
audit policy, and `vm.max_map_count=65530` on `acer`. The repository helper
strictly validates indexer/logging changes, preserves unrelated configuration,
and gates execution on reviewed current main, node readiness and no reboot.
No Talos settings have been applied for Wazuh.

Acceptance still requires protected merge, capacity, prerequisites, image
publication, Wazuh sync, Talos forwarding, private UI login, recent per-source
and per-node index counts, canary in both archives/alerts, first backup and an
isolated restore. No live ingestion, backup or restore success is claimed.

Related: [[../architecture/gitops-flow]], [[../architecture/storage-and-state]],
[[../architecture/secrets-and-identity]], [[../workloads/inventory]].
