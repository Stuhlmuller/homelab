# OpenClaw

OpenClaw targets Octelium app access as `openclaw.homelab`, while the stable UI
URL remains `https://openclaw.stinkyboi.com` and resolves to the Octelium
service address. Runtime config and agent state persist on the `openclaw` PVC
under `/data/openclaw`.

## Resource Profile

The app container requests `1` CPU and `2Gi` memory, with a `6Gi` memory limit
and no CPU limit so Codex-backed agent work can burst when node capacity is
available. The bootstrap init container requests `500m` CPU and `1Gi` memory
with a `3Gi` memory limit because it validates config and installs channel
plugins during startup. The local TCP proxy stays small at `25m` CPU and
`64Mi` memory requested with a `256Mi` memory limit.

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

## Discord Channel

The `openclaw-secrets` ExternalSecret reads the Discord bot token from
`/homelab/openclaw/discord-bot-token` and exposes it to the pod as
`DISCORD_BOT_TOKEN`.

On pod startup, the `bootstrap-config` init container keeps the Control UI
origin allow-list current. When `DISCORD_BOT_TOKEN` is populated, it installs
the official `@openclaw/discord` channel plugin into pod-local plugin storage,
enables the plugin, and stores a SecretRef to the environment-backed token.
The npm cache and extension directory are intentionally not on the NFS-backed
state PVC because OpenClaw rejects code plugins owned by the QNAP NFS `nobody`
mapping.

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

## Alertmanager Hook

Alertmanager can notify Claw directly through OpenClaw's authenticated hook
endpoint. The hook token is generated at
`/homelab/grafana/openclaw-alert-hook-token`, exposed to Alertmanager as the
`alertmanager-openclaw-alert-hook` Secret, and exposed to OpenClaw as
`GRAFANA_ALERT_HOOK_TOKEN`.

Startup bootstrap enables OpenClaw hooks at `/hooks` when the token is
populated. Alertmanager posts alert notifications to
`http://openclaw.ai.svc.cluster.local:8080/hooks/agent` with a bearer token, so
alerts create direct OpenClaw agent runs instead of relying on Claw watching the
Discord channel. The OpenClaw NetworkPolicy allows ingress to port `8080` from
the `monitoring` namespace for this path, and the `ai` namespace
AuthorizationPolicy allows the
`cluster.local/ns/monitoring/sa/prometheus-kube-prometheus-alertmanager`
principal through the ambient default deny.

OpenClaw rejects SecretRef objects for `hooks.token`, so bootstrap expands
`GRAFANA_ALERT_HOOK_TOKEN` from the mounted Secret at pod startup, JSON-encodes
the actual runtime value, and writes that plain string to the PVC-backed
OpenClaw config. This keeps the token out of git while satisfying OpenClaw's
hook-token policy.

After rotating the hook token, bump both
`homelab.rst.io/openclaw-alert-hook-ssm-version` on the Prometheus-owned
ExternalSecret and Alertmanager pod metadata, plus
`homelab.rst.io/openclaw-grafana-alert-hook-ssm-version` on OpenClaw so Argo CD
refreshes the delivery Secret and rolls the pods that read it.

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
`agentRuntime.id: "codex"`. OpenClaw 2026.6.1 routes canonical `openai/gpt-*`
agent refs through the Codex app-server harness when that runtime policy is
selected, so the PVC-backed Codex OAuth profile supplies the ChatGPT Pro auth
without storing an API key in SSM or git. The older `openai-codex/gpt-*` and
`codex/gpt-*` refs are compatibility routes, not the desired bootstrap default
for this deployment.

The bootstrap also enables the bundled `memory-wiki` plugin. OpenClaw uses that
plugin for Imported Insights and Memory Palace, so reload the Control UI tab
after the synced pod restarts if those views still show an enable-plugin prompt.

Startup bootstrap pins `agents.defaults.sandbox.mode` to `off`. The Codex
harness otherwise tries to create a Docker-backed sandbox for every Discord
agent run, but the OpenClaw application image does not ship Docker and this pod
does not run Docker-in-Docker. The containment boundary for this deployment is
the Kubernetes workload itself: the pod has its service account token disabled,
uses the committed NetworkPolicy and ambient mesh policies, and writes durable
agent state only under the OpenClaw PVC. If Docker or another sandbox runtime is
added to the workload later, revisit this setting before enabling it.

During startup, the bootstrap runs OpenClaw's safe doctor repairs when the
persisted PVC config no longer matches the current OpenClaw schema. This keeps
version upgrades from blocking on stale runtime config while preserving secrets
and OAuth state on the PVC. It also pins `gateway.mode` to `local`, which is
required for the container-managed gateway process.

Run the interactive login from a tailnet-connected operator machine:

```sh
kubectl -n ai exec -it deploy/openclaw -c app -- \
  openclaw models auth login --provider openai-codex --set-default
```

For a headless terminal or callback-hostile network, use the device-code flow:

```sh
kubectl -n ai exec deploy/openclaw -c app -- \
  openclaw models auth login --provider openai-codex --device-code --set-default
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
