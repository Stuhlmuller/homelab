# Wazuh SIEM

Wazuh 4.14.8 is the open-source homelab security log platform. Repository-owned
manager, indexer and dashboard resources use digest-pinned upstream images.
Fluent Bit collects container output on every Talos node, Kubernetes Metadata
audit records, Kubernetes events, and forwarded Talos service/kernel logs.
`logall_json=yes` and Filebeat archive indexing preserve non-alerting events as
well as security alerts. Initial rules alert on Kubernetes authentication/
authorization failures, warning events, Talos errors and the pipeline canary.
Container payloads remain under `data.log`; application-specific parsing and
rule tuning are separate work, so storage of a log does not imply its contents
trigger a built-in detection. Active response is not enabled.

**Staged, not deployed.** The Application targets `main` with automated sync
explicitly disabled. On 2026-10-03 after the Langfuse memory reservation,
`acer` had 2.82 GiB unreserved memory. Wazuh and its collectors request 7.12 GiB
there plus 1 GiB operating headroom, leaving a 5.30 GiB capacity shortfall. Do not
lower requests to force them onto the single control-plane node. Add capacity or
approve specific workload moves, then validate again before enabling sync in a
reviewed change. The current local volumes and central receiver are pinned to
`acer`; moving to a new node requires updating those selectors, volumes, Talos
endpoint and helper node inventory together.

## Data path and access

```text
node container files + Kubernetes audit -> Fluent Bit DaemonSet --\
Kubernetes Events API -----------------> Fluent Bit receiver -----+-> manager
Talos service/kernel logs -> LAN TCP30517 -> Fluent Bit receiver --/      |
                                                     alerts + archives |
                                                                       v
                                                                Wazuh indexer
                                                                       |
Octelium private client -> human authorization -> Istio -> Wazuh dashboard
```

Open `http://wazuh` through the authenticated Octelium private client. The
native Service `wazuh.default` is neither public nor anonymous and requires
`homelab-human-web-access`. `wazuh.stinkyboi.com` is only the internal Istio
routing host; no public DNS/tunnel route is created. Wazuh's own `admin` login
remains required. Retrieve its generated password through the approved secret
manager privately, never via Pod logs or chat.

Istio ambient STRICT mTLS protects Pod-to-Pod collection and core traffic;
AuthorizationPolicies allow named service accounts only. The sole plaintext
exception is Talos TCP input5170, exposed as NodePort30517 on `acer`, with
original node addresses retained and both policy layers restricted to the four
known Talos node IPs. This LAN leg has no peer cryptographic authentication;
its IP allow-list is not spoof-resistant. No router/NAS source is allowed yet.
Indexer/Filebeat connections verify their cert-manager-issued CA. The 4.14.8
Wazuh dashboard API plugin hardcodes `rejectUnauthorized:false`; dashboard to
manager HTTPS lacks certificate validation. Ambient STRICT authentication and
its exact service-account policy are required compensating controls. No indexer,
manager API, agent enrollment or syslog service is publicly exposed.

## Coverage contract

| Source | Declared path | Acceptance evidence |
| --- | --- | --- |
| All namespaces' container stdout/stderr | `/var/log/containers/*.log` on every node | Recent indexed records for all four node names |
| Istio access logs | Existing `/dev/stdout` setting | Real gateway/service request indexed |
| Fleet osquery status/results | Existing stdout plugins | Real device result indexed |
| Kubernetes API audit | `/var/log/audit/kube/kube-apiserver.log` | Recent `kubernetes.audit` record; live catch-all Metadata policy verified |
| Kubernetes events | Read-only API watch, durable cursor | Recent `kubernetes.event` record |
| Talos service/kernel logs | Committed logging and KmsgLogConfig patches | Real record from every node after guarded apply |
| End-to-end health signal | `wazuh-canary` CronJob stdout every five minutes | Matching archive **and** alert record |
| NAS/Plex/router/switch/firewall | Device forwarding not managed in this repo | Pending device identity, repository-owned configuration and live sender proof |
| Conventional Linux/macOS/Windows endpoints | Agent listener exists but ingress/enrollment not activated | Pending explicit inventory, declared install path and per-agent events |

NOFX's pinned logger already duplicates its file log to stdout. This change
also configures OctoBot's native console logger at DEBUG (matching its file
logger) and ClickHouse's native console at trace (matching existing file output).
Verify both streams after those app changes reconcile; no PVC scraping sidecar
is needed. OpenClaw private doctor reports and Octelium's native security
logstore still need an explicit export contract. Do not scrape PVCs, secrets,
database contents, or agent conversation stores indiscriminately to call coverage
complete.
Wazuh manager diagnostics already stream to stdout; its JSON API log is
collected natively from `/var/ossec/logs/api.json`. The indexer's native Docker
Log4j configuration sends ordinary, deprecation and slow logs to stdout.
Verify these own-service streams separately from alert/archive collection.
JVM GC/fatal-error diagnostic files still need a native console route; heap
dumps are sensitive memory artifacts and are not log-shipping inputs.
Talos log collection is not an installed Wazuh endpoint agent or host FIM.

Fluent Bit excludes only its own container diagnostic logs to prevent feedback
amplification during delivery errors. Each collector has a persistent 2 GiB
queue and durable file offsets on its node. A full queue, node loss, or a source
file rotating before consumption can lose events; TCP delivery is not an
end-to-end indexing acknowledgement. Records exceeding 24 KiB of serialized JSON and admitted by the 1 MiB
tail limit are fragmented before Wazuh's 64 KiB transport boundary; reconstruct
the original JSON using the fragment metadata when investigating. Lines over
1 MiB are skipped and must be recovered from the source. Security rules apply
to ordinary records; fragmented records are forensic evidence, not equivalent
rule evaluation. Prometheus alerts on delivery errors, dropped records and
missing collectors. Retrospective recovery is limited to files still present.

## Secrets and storage

The shared SSM unit generates four distinct credentials under `/homelab/wazuh/`:
`indexer-admin-password`, `api-password`, `dashboard-password` (the
`kibanaserver` service identity), and `agent-enrollment-password`. External
Secrets renders native config files and bcrypt hashes. No credential values,
raw certificates, demo users or secret environment variables belong in Git.

Indexer data (100 GiB) and manager state (50 GiB) use retained node-local volumes
on `acer`. QNAP squashes NFS ownership, making it unsuitable for these upstream
containers' active data directories. These static capacities are scheduling
metadata, not filesystem quotas: both volumes consume Talos EPHEMERAL. Keep
indexer disk watermarks enabled and monitor node free space. A node reinstall
can destroy local state despite `Retain`; PVC retention is not a backup.

A nightly Job at 04:30 America/Los_Angeles takes a native indexer snapshot
(`wazuh-*` and `.kibana*`, without global security state), then mirrors manager
alerts/archives `.gz` files closed for over 24 hours with SHA-256 verification.
It does not delete local raw files, prune NAS copies, or provide a complete
manager identity/database backup. Snapshots and manager archives use the retained
150GiB `wazuh-backups` NFS claim. Confirm an initial successful run; finite,
verified pruning and a quiesced manager-state backup are still production gates.
Index archives expire after 30 days and alerts after 90 days, but snapshots can
retain expired index data until a separate reviewed pruning policy is enabled.
Size these from measured daily ingest; no fixed retention period is guaranteed
to fit on disk.

Restoration also needs manager agent keys/API RBAC, SSM credentials and the
cert-manager CA. The NAS is a separate host but shares the homelab failure
domain; offsite copies and an isolated restore drill remain gaps. Never copy a
live Lucene data directory as a substitute for the snapshot API. Leaf certificates
last 90 days; renewal needs a reviewed Pod revision change until automatic reload
is implemented. Secret renewal alone does not prove processes reloaded keys.

## Rollout

1. Run `nix develop --command python3 -I scripts/wazuh-preflight.py`. Capacity
   must pass with operating headroom; review actual node memory usage too.
2. Run the static, policy and focused Wazuh checks. Mirror all pinned images to
   Harbor using the reviewed image workflow before activating consumers.
3. From a clean reviewed `main`, reconcile shared prerequisites/AppProject and
   SecretStore allow-list, then dispatch the protected workflow:

   ```sh
   gh workflow run terragrunt-apply.yml --ref main \
     -f expected_sha=<full-reviewed-main-sha> -f argocd_app=wazuh
   ```

   This reconciles the **whole shared SSM/IAM unit** before only the Wazuh
   Application. Review its private plan for unrelated changes. It skips shared
   AppProject/SecretStore bootstrap, so their permissions must already be live.
   Registration with automated sync disabled does not install runtime Pods.
4. Validate then apply the indexer sysctl through the repo helper. The example
   client path is workstation-specific; it must be Talos 1.11.3 for these nodes.

   ```sh
   nix develop --command python3 -I scripts/wazuh-talos.py \
     --phase indexer --node 10.1.0.199 \
     --talosconfig /private/path/talosconfig --talosctl /path/to/talosctl-1.11.3
   ```

   Execution adds `--execute --expected-sha <full-reviewed-main-sha>` after
   validation. It preserves unrelated machine settings and uses no-reboot mode.
5. Enable Wazuh automated sync in `IaC/terragrunt.stack.hcl` through a reviewed
   change after the gates above pass, then run the same targeted apply for that
   exact new main SHA. Require healthy cert-manager/ExternalSecrets/storage,
   manager, indexer, dashboard, all four collectors and bootstrap Job.
6. Reconcile private access with `scripts/octelium-wazuh-reconcile.py` using
   isolated Python in the Nix shell. Its default is read-only; execution adds
   `--execute --expected-sha <full-reviewed-main-sha>` and verifies convergence.
7. Run `scripts/wazuh-talos.py --phase logs` for each of `10.1.0.199`, `.200`,
   `.201`, `.202` with its authenticated config and the same execution guards.
   It requires a healthy receiver and preserves other logging destinations.
   The existing Metadata audit policy is checked, not changed.
8. Run `nix develop --command python3 -I scripts/wazuh-verify.py`, then verify
   login, archive search, alert search, actual per-node Talos records and the
   first backup. Record only counts/identities/timestamps publicly, not raw logs.

Do not treat a green Argo status as proof that all sources are indexed. The
verification command checks recent source counts, all node container streams,
and both canary indices without printing credentials or log bodies. Kubernetes
events may be quiet; use an ordinary declared workload rollout to create a real
event before rerunning that check. External devices require their own receipt.

## Recovery and rollback

Disable collection destinations on Talos through `wazuh-talos.py --phase logs
--rollback` before removing the receiver. Disable the SIEM through reviewed
replica/Application changes and keep retained claims. Lowering the indexer
sysctl requires indexer replicas zero and the guarded `--phase indexer
--rollback` path; the recorded pre-change value is 65530. Never delete claims or
reset the security index to fix authentication.

Recover the CA and credentials before regenerating certs, manager identity
state before reconnecting agents, and index data through an isolated compatible
Wazuh indexer snapshot restore. Do not restore over live ingestion. Re-run source
and canary verification after restoration. Rotating subPath-mounted secrets or
certificates requires a reviewed Pod revision change and verified readback;
renewed Kubernetes Secret data alone does not prove processes reloaded it.

## Sources

- [Wazuh Kubernetes deployment](https://documentation.wazuh.com/current/deployment-options/deploying-with-kubernetes/index.html)
- [Wazuh 4.14.8 reference manifests](https://github.com/wazuh/wazuh-kubernetes/tree/v4.14.8)
- [Wazuh full event archives](https://documentation.wazuh.com/current/user-manual/manager/event-logging.html)
- [Talos 1.11 logging](https://docs.siderolabs.com/talos/v1.11/configure-your-talos-cluster/logging-and-telemetry/logging)
- [Fluent Bit Kubernetes events](https://docs.fluentbit.io/manual/data-pipeline/inputs/kubernetes-events)
