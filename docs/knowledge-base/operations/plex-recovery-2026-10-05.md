---
date: 2026-10-05
tags:
  - operations
  - qnap
  - plex
status: service-restored
---

# QNAP Plex Recovery

Plex on the QNAP recovered on October 5 at 19:42 PDT after an operator ran the
bounded start helper. Identity and web checks return HTTP 200. The repository
validation gate passed. The original crash cause is not established.

## Evidence

Read-only inspection on October 5 found:

- QNAP `10.1.0.2` runs QTS `5.2.10` and Plex
  `1.43.3.10896-cb3ebc72d`. TCP ports `22`, `443`, `8080`, and `2049` respond;
  Plex port `32400` refuses connections.
- The main `Plex Media Server` process is absent, while plugin children remain.
  CrashUploader recorded `sessionStatus=crashed` at **October 2, 20:16:13 PDT**;
  the tuner log also reported its parent gone.
- `/share/CACHEDEV2_DATA` is 62% used, with about 1.3 TB free. The available
  kernel ring buffer contains no matching OOM record; this does not exclude
  an earlier OOM event.
- Photo transcoder activity appears near the crash in the logs. Timing alone
  does not establish the crash cause.
- SSH as `themanofrod` succeeds with UID `1000` and membership in
  `administrators`. Noninteractive `sudo -n` requires a password; SSH key
  authentication as `admin` was rejected.

The reachable NAS services and missing Plex process distinguish this incident
from the historical router-to-wired-network fault recorded in
[[operations/continuous-improvement]]. Do not treat surviving plugin processes
as proof that the server is running.

## Recovery Path

Use the repository-owned
[Plex recovery helper](../../../scripts/qnap-plex-recover.sh). Its default mode
only reports status:

```sh
bash scripts/qnap-plex-recover.sh
```

After the helper passes relevant validation, start the missing enabled server:

```sh
bash scripts/qnap-plex-recover.sh --start
```

The helper uses the installed vendor init script through `sudo` and `setsid`,
starts only an enabled package with no main server process, and does not restart
a healthy main process. A separate session keeps Plex detached from the SSH terminal.
It preserves the installed version, configuration, and libraries.
If elevation requires a password, run this command in an interactive operator
terminal and enter the password at the prompt; never place it in chat, git,
command arguments, or environment variables.

Recovery requires successful Plex identity and web checks, followed by an
authenticated client check that the expected libraries load and an existing
item plays. A running process alone is insufficient. If startup fails or the
process crashes again, retain private logs and investigate before another start.
No configuration or version change is included to roll back.

## Validation

- `bash -n` and repository-pinned ShellCheck passed for the helper.
- Five isolated command fixtures passed: stopped inspection, healthy no-op,
  running-but-unhealthy refusal, successful start, and rejected authentication.
- `nix develop --command bash scripts/ci/static-checks.sh` passed, including
  secret scans. This gate preceded the ClickHouse repair below.
- The first operator start removed orphan plugin processes but did not restore
  HTTP service. The launcher now uses QNAP's `/bin/setsid`; SSH terminal hangup
  was a plausible failure mechanism, not a confirmed cause of the original crash.
- The corrected operator start produced a new main server process at 19:42.
  Identity briefly returned 503, then identity and `/web/index.html` returned
  200. The read-only helper reported no recovery needed after SSH closed.
- Authenticated library inspection was unavailable because this SSH account
  cannot read Plex's credential file. The operator later confirmed login and playback, with slow start/seek; HTTP availability alone does not establish successful playback.

## Remaining Work

- Resolve the slow start/seek behavior recorded below; client login now works.
- Investigate the crash cause using private crash/log evidence if it recurs.
  Keep raw logs, tokens, account identifiers, and library details out of git.

## Hosted Web Client Follow-up

The operator subsequently reported an `app.plex.tv` secure-connection error on
the home-network Mac. Read-only checks from that Mac found:

- The server's `plex.direct` hostname resolves to the NAS through both the
  system resolver and a direct Cloudflare query.
- TLS 1.3 certificate verification succeeds for that hostname. The Let's
  Encrypt certificate is valid September 23 through December 22, 2026.
- HTTPS `/identity` returns 200. Requests carrying the `app.plex.tv` Origin
  and the corresponding OPTIONS preflight return 200 with that allowed origin.

These checks establish working server TLS and system DNS, but do not reproduce
the browser's request path. Browser permissions, browser DNS, and hosted-client
discovery remain unverified. Do not disable Plex TLS or broadly change router
DNS/rebinding protection on the basis of this generic client error.
See [Plex secure connections](https://support.plex.tv/articles/206225077-how-to-use-secure-server-connections/)
and [Firefox local network permissions](https://support.mozilla.org/en-US/kb/control-personal-device-local-network-permissions-firefox).

## Slow Playback Start And Seek

The operator confirmed login works but reported long start/seek delays. During
October 5 playback around 21:10–21:14 PDT, read-only checks found:

- At 21:10:33, unrelated Plex requests stalled together: a library update took
  15.5 seconds, playback timeline 11.6 seconds, and metadata 10.1 seconds.
  Nearby DASH startup responses were 218–726 ms, segments up to 2.5 seconds,
  and subtitle delivery 2.1 seconds. No usable transcoder-speed counters were
  present in the inspected logs.
- Playback came from Firefox over the LAN. Video was copied into DASH, with
  audio conversion and subtitle extraction. Video re-encoding was not observed.
- NAS load reached about 17. One CPU snapshot showed 87% I/O wait, and later
  samples varied substantially. Many NFS workers were blocked on storage.
  Logical-volume waits reached roughly 80–326 ms in sampled intervals.
- A five-second NFS sample measured about 1.9 MB/s writes, 117 creates/s,
  62 removes/s, and 67 renames/s. This indicates significant small-file and
  metadata activity, without saturating network bandwidth.
- Mac-to-NAS latency averaged 4.8 ms with no loss across six probes; idle Plex
  identity requests took 10–12 ms. The data RAID had all four members present
  and no rebuild/scrub running. Available kernel logs showed no matching disk
  I/O/reset errors; SMART health was not inspected.
- No Kubernetes backup Jobs were active. Existing cAdvisor write metrics and
  media-service status did not conclusively identify the NFS workload generating
  the contention.
- Two authenticated Talos `/proc/1/mountstats` samples about five seconds apart
  localized metadata churn to `acer`: about 79 creates/s, 183 removes/s,
  74 renames/s, and 226 lookups/s. `zimaboard-0`, including its media mounts,
  was effectively idle; `zimaboard-1` had writes without metadata churn.
  Acer's 12 mounts exposed identical shared counters, so deduplicated totals
  identify the client node but cannot identify the responsible PVC. Its NFS
  consumers include ClickHouse, Harbor components, Octobot, Grafana/Alertmanager,
  Multica uploads, and the provisioner. Do not attribute the traffic to one app
  without additional evidence.

The simultaneous request delays and disk waits point to shared NAS storage
contention. Browser remuxing adds work but does not explain all of the observed
stalls. The subsequent checks below identified a retrying workload on `acer`; a
controlled improvement check remains open.

Related: [[architecture/storage-and-state]], [[runbooks/storage-nfs]],
[[operations/validation-gates]].

## Jellyfin Stop And ClickHouse Repair

At 21:23 PDT, after the operator stopped Jellyfin in QTS, read-only checks
confirmed its QPKG was disabled and no package processes remained. Jellyfin had
previously performed a 74-minute scan, but stopping it did not end the NAS load:
NFS still showed roughly 73 creates/s, 55 removes/s, and 66 renames/s.

ClickHouse on `acer` recorded **5,288 failed merges in ten minutes**, all in six
`system` diagnostic tables: `error_log`, `histogram_metric_log`,
`opentelemetry_span_log`, `part_log`, `query_log`, and `text_log`. Failures
repeated on the same parts with error 117 (`INCORRECT_DATA`) or 33
(`CANNOT_READ_ALL_DATA`), including malformed dictionaries, marks, and truncated
reads. No failed merge events for Langfuse's `default` database were found in
the preceding 24 hours; this is not a full integrity check. Corruption origin
remains unknown.

The repository repair removes the six logger configuration sections and uses
ClickHouse's native startup SQL to permanently detach those tables. It retains
all data and metadata, does not modify application tables, and runs idempotently
on restart or an empty installation. A generated ConfigMap hash triggers the
existing `Recreate` deployment. A disposable pinned-image test verifies retained
part checksums, an unaffected application sentinel, repeated startup, and fresh
startup before deployment. Local Docker is unavailable; CI must run that test.

Deployment and playback improvement are pending. Verify the six permanent
detachments, disappearance of merge retries, lower NAS metadata rates, readable
application tables, and actual Plex start/seek. See the
[Langfuse quarantine contract](../../../clusters/homelab/apps/langfuse/README.md#clickhouse-diagnostic-quarantine)
for rollback; restoring configuration alone cannot reattach retained tables.
