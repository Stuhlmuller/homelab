# OpenClaw

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
three consecutive failed liveness checks restart only the app container when
the gateway stops answering HTTP through the proxy. Readiness removes the pod
from the Service before that recovery threshold is reached. A TCP-only check is
not sufficient here because the proxy listener can accept a connection even
when its upstream gateway is unavailable.

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
origin allow-list current. When `DISCORD_BOT_TOKEN` is populated, it inspects
the official `@openclaw/discord` plugin and requires bundled origin plus a
`package.json` version equal to the running OpenClaw version. It then uses
[OpenClaw's config-only enable path](https://github.com/openclaw/openclaw/blob/2d2ddc43d0dcf71f31283d780f9fe9ff4cc04fe4/src/cli/plugins-cli.runtime.ts#L188-L227)
and verifies that the loaded runtime resolves to the same bundle directory and
version. A missing, replaced, or incompatible plugin fails startup. Bootstrap
never invokes the plugin installer, so neither ClawHub nor npm can supply code.
It then stores a SecretRef to the environment-backed token.

Keep the OpenClaw image new enough for the current official Discord plugin API.
The 2026-06-24 recovery moved the app, proxy, and bootstrap images to
`2026.6.10` because the current ClawHub Discord plugin requires plugin API
`2026.6.10` or newer and rejected the older `2026.6.6` runtime.

Discord bootstrap is skipped when the SSM value is still `REPLACE_ME`, so the
app can start before the real Discord bot token exists. After replacing the SSM
value, bump
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
hook-token policy.

After rotating the hook token, bump
`homelab.rst.io/openclaw-grafana-alert-hook-ssm-version` on OpenClaw so Argo CD
refreshes the Secret and rolls the pod that reads it.

## GitHub App Credentials

OpenClaw receives GitHub App identity through AWS SSM-backed ExternalSecrets:

| SSM parameter | Pod surface |
| --- | --- |
| `/homelab/openclaw/github-app/id` | `GITHUB_APP_ID` |
| `/homelab/openclaw/github-app/installation-id` | `GITHUB_APP_INSTALLATION_ID` |
| `/homelab/openclaw/github-app/private-key` | `/var/run/secrets/openclaw/github-app/private-key.pem` |

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

The bootstrap also enables the bundled `memory-wiki` plugin. OpenClaw uses that
plugin for Imported Insights and Memory Palace, so reload the Control UI tab
after the synced pod restarts if those views still show an enable-plugin prompt.

Startup bootstrap pins `agents.defaults.sandbox.mode` to `off`. OpenClaw
[2026.7.1 supports Docker, SSH, and OpenShell sandbox backends](https://github.com/openclaw/openclaw/blob/v2026.7.1/docs/gateway/sandboxing.md).
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

During startup, the bootstrap validates the persisted config before applying
desired state. It does not run automatic doctor repairs: doctor scans session
history on the NFS-backed PVC, so accumulated orphan transcripts can block the
pod before the gateway starts. Run migrations as explicit, reviewed maintenance
when an upgrade requires them. Bootstrap also pins `gateway.mode` to `local`,
which is required for the container-managed gateway process.

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
