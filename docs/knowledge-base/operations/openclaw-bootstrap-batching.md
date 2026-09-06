# OpenClaw bootstrap batching

Related: [[openclaw-assistant-2026-09-05]], [[validation-gates]],
[[architecture/storage-and-state]].

## Measured startup cost

On September 6, 2026, Pod `openclaw-6547b6bb6d-bwtpl` started at 19:41:59 UTC
and became Ready at 20:05:15: **23 minutes 16 seconds**, with zero restarts.
The toolbox init ran for 7 minutes 29 seconds; bootstrap configuration ran for
13 minutes. Argo subsequently reported Healthy/Synced.

The previous successful Pod started at 18:16:06 UTC. Prometheus samples for
its exact UID bracket readiness between 18:39:22.610 and 18:39:52.610, or
23 minutes 17–47 seconds after start, plus unquantified exporter/watch delay.
These observations are startup measurements, not an upper bound or proof that
NAS latency alone causes the delay.

The Deployment uses Recreate and the default 600-second progress deadline.
It reported `ProgressDeadlineExceeded` during initialization, then recovered.
Pinned app-template 4.4.0 has no supported value for this field; adding a value
fails schema validation. This change leaves the deadline limitation open.
A chart or rendering integration change needs separate review.

## Supported configuration batches

Pinned OpenClaw 2026.9.1 provides `config set --batch-file`: ordered typed
assignments against the existing config, final schema validation, and one
config persistence operation per batch. See the
[pinned CLI documentation](https://github.com/openclaw/openclaw/blob/v2026.9.1/docs/cli/config.md)
and [implementation](https://github.com/openclaw/openclaw/blob/v2026.9.1/src/cli/config-cli-runner.ts).

Bootstrap groups the existing 16 assignments into six batches when both
optional credentials are populated. Without either credential, it uses three.
The legacy hook-token unset, assistant bootstrap, config validation, and Discord
plugin enable/check retain their ordering. Those commands can still write
configuration separately. Backup, migration, doctor, and session-preservation
gates remain in place.

Batch input is limited to 1 MiB and written to a private directory under `/tmp`,
with mode 0600 files and exit/signal cleanup. The hook token remains JSON-encoded
data; gateway and Discord tokens remain authored SecretRefs. Temporary batches
do not use the persistent volume. Reducing CLI invocations and writes addresses
measured repeated-command overhead; production latency improvement is unverified.

## Validation and rollout

`scripts/ci/openclaw-config-check.py` executes the actual shell with a narrow
CLI test double, checking conditional credentials, ordering, unrelated config
preservation, repeat runs, failure stops, and temporary-file cleanup. The separate
`OpenClaw native config` CI job uses the exact digest-pinned image and synthetic,
disposable state to verify vendor batch behavior. It checks typed edits,
SecretRefs, ordered duplicate paths, one write versus sequential writes,
dry-run behavior, rejected-batch atomicity, and the legacy hook-token sequence.
It starts no gateway and does not access a cluster, credentials, or backups.

After an approved merge, Argo replaces the Pod. Compare Pod start, init-container
completion, and Ready timestamps against the baseline above. Verify preserved
sessions, no unexpected restarts, and responsive gateway and Discord operation.
Roll back with a reviewed Git revert; another Recreate rollout incurs downtime.
Do not manually restart or modify the Pod to shorten the measurement.

Sources: `clusters/homelab/apps/openclaw/values.yaml`, the app README, and the
two configuration validation scripts under `scripts/ci/`.
