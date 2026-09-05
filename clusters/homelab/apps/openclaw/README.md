# OpenClaw

## Remaining 2026.8.2 state migration

The session SQLite import alone does not migrate workspace setup state.
After the coordinator ownership repair, the gateway rejected the retained
`openclaw-workspace-state.json` and requested `openclaw doctor --fix`.
Bootstrap now runs the pinned doctor's noninteractive repair once after
configuring plugins and secrets, with workspace suggestions disabled. It
keeps the existing external supervisor/service-repair policy and does not use
`--force` or `--allow-exec`. Because generic repair can rewrite unrelated skill
policy, bootstrap snapshots the reviewed config privately and restores it
atomically after doctor, even on failure. An interrupted repair restores that
snapshot before the next bootstrap applies configuration. Only doctor state
migrations persist; configuration remains owned by the reviewed bootstrap.

Existing state requires the verified pre-2026.8.2 archive before this step.
Doctor performs its upstream legacy-state migrations and startup readiness
checks, including workspace setup/attestations and any other detected legacy
stores. The session inventory is checked again afterward, and configuration
must validate before the separate `.doctor-state-migrated-to-2026.8.2` marker
is written. The original session-import marker is preserved. Failures block
the gateway and retain private `doctor-state-reports/latest.log` plus one
previous report; their contents must not be posted in this public repository.

The pinned CLI passed synthetic workspace migration and a repeat run. Local
bootstrap tests prove failed backup, doctor, session preservation, or config
validation cannot create the completion marker. Live gateway and Discord
readiness remain rollout gates. A manifest rollback cannot undo migrated
state; recovery requires the verified archive and its matching prior version,
following the existing offline restore procedure. Do not delete the archive
or archived legacy sources during the recovery soak.

OpenClaw targets Octelium app access as `openclaw.homelab`, while the stable UI
URL remains `https://openclaw.stinkyboi.com` and resolves to the Octelium
service address. Runtime config and agent state persist on the `openclaw` PVC
under `/data/openclaw`.

## Resource Profile

The app container requests `1` CPU and `2Gi` memory, with `1500m` CPU and `4Gi`
memory limits. Seven days of five-minute samples measured about `1` CPU and
`1.8Gi` memory at p95. Multiple pod series exceeded `4Gi`, maxima approached
`6Gi`, and three terminated as OOMKilled. On 2026-08-28, app memory climbed to
`5.36Gi` immediately before its 8 GiB worker stopped reporting. The `4Gi`
containment limit deliberately prefers an app OOM over starving Talos, kubelet,
and containerd; raise it only after the memory growth is fixed and 48 hours of
healthy measurements show node headroom. The CPU limit throttles rare bursts
before they can starve a four-core worker. It requests
`5Gi` and limits `6Gi` of ephemeral storage: the shared
Nix store uses about `2.7Gi`, while the separately capped Codex runtime can use
up to `2Gi`. The `5Gi` request reserves that expected footprint; the `6Gi`
limit leaves room for the writable layer and logs. The `operator-toolbox` init
container requests `1` CPU and `2Gi` memory and limits `1500m` CPU and `3Gi`
memory. The bootstrap init container requests `500m` CPU and `1Gi` memory and
limits `1200m` CPU and `2Gi` memory. The local TCP proxy stays small at `25m`
CPU and `64Mi` memory requested, with `50m` CPU and `128Mi` memory limits.

OpenClaw excludes the `acer` control-plane node and every Octelium dataplane
node from scheduling. The 2026-08-25 recovery found bit corruption in both
`acer`'s cached image and control-plane etcd records. The dataplane exclusion
keeps OpenClaw's measured memory peaks from evicting ingress proxies. Remove
either affinity only after the affected node role has dedicated capacity and
passes its documented validation.

## Workspace Runtime Setup

The OpenClaw PVC is backed by the QNAP NFS share, so files under `/data/openclaw`
can appear owned by `nobody:nogroup` inside the container even though the app
runs as the `node` user. Startup bootstrap avoids fighting that ownership
mapping with `chown`. Instead it creates the expected workspace scratch paths,
including `/data/openclaw/workspace/.openclaw/trash`, and points Git at a
shared global config file on the PVC with safe-directory entries for the
workspace and `/data/openclaw/src/*` checkouts.

This keeps agent file cleanup and Git operations from failing on NFS ownership
metadata while preserving the PVC as the source of durable agent state.

Startup bootstrap also configures Claw's commits to be SSH-signed. The signing
key is generated once at `/data/openclaw/signing/claw_ed25519`, Git uses
`/data/openclaw/gitconfig` as its global config, and `commit.gpgsign=true`
prevents unsigned commits from being created by default. If the image does not
ship `ssh-keygen`, bootstrap unpacks `openssh-client` into
`/data/openclaw/tools` and points Git at that persistent helper.

The `operator-toolbox` init container installs the homelab operator tools with
Nix, shares `/toolbox/profile` with the app and bootstrap containers, and also
copies the complete init-container `/nix/store` with its database into the
shared `/nix` mount. Keep the store and database matched. Copying only the
profile closure while copying the full database leaves missing derivation paths,
which breaks fresh-pod `nix develop` runs against the homelab flake.

## Gateway Auth

The generated `/homelab/openclaw/app-secret` SSM parameter is exposed to the
pod as `OPENCLAW_GATEWAY_TOKEN`. Startup bootstrap stores
`gateway.auth.token` as a SecretRef to that environment value and pins
`gateway.auth.mode` to `token`, so the gateway does not depend on a generated
file under the container user's home directory.

If gateway startup reports a missing
`/home/node/.openclaw/secrets/gateway-auth-token.txt`, sync this desired state
and roll the pod. The environment token wins during startup auth resolution and
makes stale file-backed gateway token refs inactive.

If the Control UI reports
`unauthorized: device token mismatch (rotate/reissue device token)`, the browser
has a stale device-pairing token for the otherwise healthy gateway. Start with
read-only checks:

```sh
kubectl -n ai exec deploy/openclaw -c app -- openclaw gateway health
kubectl -n ai exec deploy/openclaw -c app -- openclaw devices list --json
```

If the gateway is healthy, refresh the browser's site data for the stable
`https://openclaw.stinkyboi.com` host reached through Octelium. Reconnect
through the current shared gateway-auth flow. To reissue a server-side token for
a paired Control UI device, identify the `clientId: openclaw-control-ui` record
and rotate its operator token:

```sh
kubectl -n ai exec deploy/openclaw -c app -- \
  openclaw devices rotate --device <device-id> --role operator
```

Treat any generated device token or token-bearing dashboard URL as secret
runtime material. Do not commit it or paste it into docs.

## Gateway Health

The gateway binds only to pod loopback on port `18789`; the `proxy` container
publishes it on service port `8080`. Both containers participate in pod
readiness through native HTTP probes against `/` on port `8080`, which avoids
spawning probe processes inside the containers while requiring the proxy to
connect to the gateway and relay a successful HTTP response.

The app container also owns startup and liveness probes. Startup allows up to
two minutes for the gateway to load persisted state and plugins. After startup,
36 consecutive failed liveness checks restart only the app container after
about six minutes without an HTTP response through the proxy. Readiness removes
the pod from the Service after two failures. A TCP-only check is not sufficient
here because the proxy listener can accept a connection even when its upstream
gateway is unavailable.

Use the event timestamps to distinguish expected startup failures from a live
stall, then verify the gateway itself:

```sh
kubectl -n ai get events \
  --field-selector involvedObject.kind=Pod \
  --sort-by=.lastTimestamp
kubectl -n ai exec deploy/openclaw -c app -- openclaw gateway health
```

## Discord Channel

The `openclaw-secrets` ExternalSecret reads the Discord bot token from
`/homelab/openclaw/discord-bot-token` and exposes it to the pod as
`DISCORD_BOT_TOKEN`.

On pod startup, the `bootstrap-config` init container keeps the Control UI
origin allow-list current. It installs the official external
`@openclaw/discord` package from npm at the exact running OpenClaw image version
in pod-local plugin storage before validating persisted config. Bootstrap pins
the install and does not fall back to a floating release. When
`DISCORD_BOT_TOKEN` is populated, it enables and runtime-checks the plugin, then
stores a SecretRef to the environment-backed token. A missing or incompatible
exact package fails startup.
The npm cache and extension directory are intentionally not on the NFS-backed
state PVC because OpenClaw rejects code plugins owned by the QNAP NFS `nobody`
mapping.

Discord channel configuration is skipped when the SSM value is still
`REPLACE_ME`, so the app can start before the real Discord bot token exists.
The exact package still installs because its storage is rebuilt with every new
pod. After replacing the SSM value, bump
`homelab.rst.io/openclaw-discord-bot-token-ssm-version` in `values.yaml` to the
resulting SSM parameter version so Argo CD rolls the pod and the startup
bootstrap re-runs.

## Grafana Login

The `openclaw-secrets` ExternalSecret also reads the dedicated Claw Grafana
login from AWS SSM:

| SSM parameter | Pod surface |
| --- | --- |
| `/homelab/openclaw/grafana/username` | `GRAFANA_USERNAME` |
| `/homelab/openclaw/grafana/password` | `GRAFANA_PASSWORD` |

After replacing those placeholders, bump
`homelab.rst.io/openclaw-grafana-login-ssm-version` in `values.yaml` to the
latest SSM parameter version so Argo CD rolls the pod and reloads the
environment variables.

Validate after sync:

```sh
kubectl -n ai exec deploy/openclaw -c app -- openclaw channels list
kubectl -n ai exec deploy/openclaw -c app -- openclaw channels status --probe
```

The Discord bot must be invited to the target server and channel with at least
the permissions OpenClaw reports as required for Discord, including viewing the
channel and sending messages.

## Agent Hook

OpenClaw exposes an authenticated agent hook for callers that send its native
`message` payload. The hook token is generated at
`/homelab/grafana/openclaw-alert-hook-token` and exposed to OpenClaw as
`GRAFANA_ALERT_HOOK_TOKEN` only in the bootstrap container.

Startup bootstrap enables OpenClaw hooks at `/hooks` when the token is
populated. Alertmanager does not call this endpoint: its standard webhook body
does not include OpenClaw's required `message` field. Homelab alerts are sent
through Alertmanager's native Discord receiver instead.

OpenClaw rejects SecretRef objects for `hooks.token`, so bootstrap expands
`GRAFANA_ALERT_HOOK_TOKEN` from the mounted Secret at pod startup, JSON-encodes
the actual runtime value, and writes that plain string to the PVC-backed
OpenClaw config. This keeps the token out of git while satisfying OpenClaw's
hook-token policy. If an older config contains the authored
`${GRAFANA_ALERT_HOOK_TOKEN}` reference, bootstrap removes that reference
before setting the literal value. OpenClaw 2026.8.2 otherwise restores the
reference during config writes, leaving the gateway without its bootstrap-only
environment variable. The removal and replacement happen during init, before
the gateway runs; a failure prevents startup rather than exposing an
unauthenticated hook.

After rotating the hook token, bump
`homelab.rst.io/openclaw-grafana-alert-hook-ssm-version` on OpenClaw so Argo CD
refreshes the Secret and rolls the pod that reads it.

## GitHub App Credentials

OpenClaw receives GitHub App identity through AWS SSM-backed ExternalSecrets:

<!-- markdownlint-disable MD013 -->

| SSM parameter | Pod surface |
| --- | --- |
| `/homelab/openclaw/github-app/id` | `GITHUB_APP_ID` |
| `/homelab/openclaw/github-app/installation-id` | `GITHUB_APP_INSTALLATION_ID` |
| `/homelab/openclaw/github-app/private-key` | `/var/run/secrets/openclaw/github-app/private-key.pem` |

<!-- markdownlint-enable MD013 -->

The pod sets `GITHUB_APP_PRIVATE_KEY_PATH` to
`/var/run/secrets/openclaw/github-app/private-key.pem`. The private key is
mounted as a file from `openclaw-github-app-private-key`, so the PEM is not
copied into the process environment. Other OpenClaw secret keys are mapped with
explicit `secretKeyRef` entries rather than a broad `envFrom` import.

After replacing any GitHub App SSM placeholder, bump
`homelab.rst.io/openclaw-github-app-credentials-ssm-version` in `values.yaml`
to the resulting SSM parameter version so Argo CD rolls the pod and reloads the
environment variables.

## ChatGPT Pro And Codex

Do not store ChatGPT passwords, browser cookies, or OpenAI API keys in this
repo for OpenClaw. ChatGPT Pro subscription access is separate from API-key
billing, but OpenAI Codex can sign in with a ChatGPT plan and store local
credentials on the OpenClaw PVC.

The pod startup bootstrap enables the bundled `codex` plugin and sets the
default agent model to `openai/gpt-5.5` with model-scoped
`agentRuntime.id: "codex"`. OpenClaw 2026.6.10 routes canonical `openai/gpt-*`
agent refs through the Codex app-server harness when that runtime policy is
selected, so the PVC-backed Codex OAuth profile supplies the ChatGPT Pro auth
without storing an API key in SSM or git. The older `openai-codex/gpt-*` and
`codex/gpt-*` refs are compatibility routes, not the desired bootstrap default
for this deployment.

Keep OpenClaw at `2026.8.2` or newer while the Codex plugin is enabled.
`2026.7.1` can leave timed-out native hook relay processes orphaned until the
container reaches its memory limit; upstream
[PR #109446](https://github.com/openclaw/openclaw/pull/109446) fixes relay PID
ownership on Linux. The bootstrap keeps the effective concurrency at four
instead of adopting `2026.8.2`'s higher default.

The `2026.7.1` to `2026.8.2` rollout is fail-closed. The `Recreate` deployment
stops the gateway, then bootstrap writes a complete owner-only archive and
SHA-256 checksum under `/data/openclaw-backups` before invoking any `2026.8.2`
OpenClaw command. It verifies the tar stream and checksum before running the
targeted session SQLite migration and starting the new gateway. The archive
includes credentials, private transcripts, and the workspace. It stays on the
same QNAP-backed volume and is a migration checkpoint, not an independent NAS
backup. Reinstallable npm cache and external-plugin directories are excluded.
OpenClaw also preserves its migration originals and manifests; do not run
`openclaw update cleanup` before the 24-hour soak closes.

An image-only rollback below `2026.8.2` is unsafe after the session SQLite
migration and also restores the hook-relay leak. If rollback is required, use a
reviewed init-container maintenance change to replace `/data/openclaw` from the
verified pre-upgrade archive while the gateway is stopped; an overlay extraction
is not a restore. Validate the recovered state before reverting the image. This
discards post-upgrade state, so prefer repairing `2026.8.2` when possible.

The bootstrap also enables the bundled `memory-wiki` plugin. OpenClaw uses that
plugin for Imported Insights and Memory Palace, so reload the Control UI tab
after the synced pod restarts if those views still show an enable-plugin prompt.

Startup bootstrap pins `agents.defaults.sandbox.mode` to `off`. OpenClaw
[2026.8.2 supports Docker, SSH, and OpenShell sandbox backends](https://github.com/openclaw/openclaw/blob/v2026.8.2/docs/gateway/sandboxing.md).
This Talos pod has no Docker daemon, while the repository declares neither a
dedicated SSH target and trust material nor an OpenShell account/runtime.
Enabling `non-main` without a working backend makes Discord, group, and spawned
agent runs fail before reply.
The containment boundary is the Kubernetes workload: the service account token
is disabled and ambient mesh policy restricts ingress. The NetworkPolicy records
intent but flannel does not enforce it. Egress is not restricted, and all
sessions share the pod's persistent workspace, operator toolbox, and mounted
application credentials. If a sandbox backend is added later, document and
validate it before changing this setting.
Do not mount a host container-runtime socket into this workload.

After the verified offline backup, bootstrap migrates the four observed retired
config keys (`meta.lastTouchedAt`, `commands.ownerDisplay`,
`hooks.maxBodyBytes`, and `plugins.bundledDiscovery`) before invoking OpenClaw.
It preserves model metadata and copies a legacy model restriction into
`agents.defaults.modelPolicy.allow` only when no explicit policy exists.
The owner-only config replacement is atomic and leaves unrelated settings,
credentials, skill policy, and session files untouched. The retired hook body
limit is no longer written; OpenClaw 2026.8.2 enforces its built-in 256 KiB limit.

Bootstrap then installs the missing official external Discord plugin before
validating persisted config and applying desired state. An exact
installed version is reused; a missing or mismatched package gets four bounded
registry attempts so a transient reset cannot leave every restart dependent on
a fresh successful download. The versioned bootstrap runs the targeted session
SQLite inspect, dry-run, import, and post-import inspection once after its verified
backup. Reports are retained with owner-only permissions under
`/data/openclaw/session-sqlite-reports`, keeping only the latest and previous
report for each mode; logs contain totals instead of thousands
of transcript paths. The report gate accepts only the observed
`transcript_missing` warning for `agent:main:healthcheck-20260813` on agent
`main`. OpenClaw 2026.8.2 preserves that entry's metadata during import but
returns exit code 1 for any warning. Every other issue, malformed report, or
unexplained nonzero exit remains fatal. The original archive and any retained
legacy/trajectory files remain available; no replacement transcript is invented.
Before import, bootstrap saves every legacy session key and session ID in a
private inventory that survives retries. After inspection, a read-only SQLite
query verifies each identity still exists before writing the completion marker.
Missing or changed identities stop bootstrap even if doctor reports no issues.

The later doctor state gate restores the reviewed configuration so generic
repair cannot persist unrelated skill-policy changes. Gateway startup owns
its documented deterministic config migrations once startup is reached;
plugin installation itself rejects unmigrated config. Session identity
preservation remains mandatory after every migration step. Bootstrap also pins `gateway.mode` to `local`, which is
required for the container-managed gateway process. External-supervisor mode
makes Kubernetes the only lifecycle and image-update authority.

Run the interactive login after connecting through Octelium and exporting the
kubeconfig generated by `octelium config kubernetes-api.homelab`:

```sh
kubectl -n ai exec -it deploy/openclaw -c app -- \
  openclaw models auth login --provider openai --set-default
```

For a headless terminal or callback-hostile network, use the device-code flow:

```sh
kubectl -n ai exec deploy/openclaw -c app -- \
  openclaw models auth login --provider openai --device-code --set-default
```

Then verify the default model and plugin-backed runtime:

```sh
kubectl -n ai exec deploy/openclaw -c app -- \
  openclaw models status --json

kubectl -n ai exec deploy/openclaw -c app -- \
  openclaw models list --provider openai
```

Those OAuth credentials persist on the `/data/openclaw` volume and should not be
copied into SSM. If the PVC is replaced, repeat the interactive Codex login.

The per-agent Codex app-server home is an `emptyDir`, not part of the NFS-backed
OpenClaw home. Its native threads, SQLite indexes, caches, and diagnostics are
rebuildable and had grown large enough to stall app-server startup and gateway
turns over NFS. The volume is capped at `2Gi`, and pod replacement clears it.
OpenClaw auth, sessions, workspace, and application state remain on the PVC.

## Local identity coordinator

OpenClaw 2026.8.2 requires its coordinator directory to belong to the runtime
UID and have mode `0700`. The QNAP share reports UID/GID `65534` for persistent
state, while the image runs as UID `1000`; the gateway otherwise refuses
startup with `device identity coordinator directory belongs to another user`.

Mount a shared 16 MiB `emptyDir` only at
`/data/openclaw/tmp/openclaw-1000` in bootstrap and the gateway. The existing
root toolbox init sets this local volume to `1000:1000`, mode `0700`, before
OpenClaw runs. Upstream ownership and locking checks remain enabled. Device
identity, configuration, session SQLite databases, and backups stay on the
retained PVC; the old NAS lock directory is hidden, not removed.

This relies on the existing single-replica `Recreate` controller. All writers
must run in this Pod and share its coordinator mount. Do not run a second
Pod or external doctor process against the same PVC: separate local lock
volumes would not coordinate those writers. Stop the gateway through a
reviewed declarative maintenance change before any external state repair.
Revisit this storage design before introducing multiple replicas.

Validate the render and the full static gate before rollout. After Argo sync,
require the mounted directory to report UID/GID `1000:1000` and mode `0700`,
then verify gateway readiness, the Discord channel, and the migration marker.
Rollback removes the local mount through a reviewed PR; persistent data and
backup files remain, but the known NAS ownership failure would return unless
an alternative ownership-compatible storage path is deployed first.
