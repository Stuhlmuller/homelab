# OpenClaw

OpenClaw runs behind the tailnet-only Istio gateway at
`https://openclaw.stinkyboi.com`. Runtime config and agent state persist on the
`openclaw` PVC under `/data/openclaw`.

## Discord Channel

The `openclaw-secrets` ExternalSecret reads the Discord bot token from
`/homelab/openclaw/discord-bot-token` and exposes it to the pod as
`DISCORD_BOT_TOKEN`.

On pod startup, the `bootstrap-config` init container keeps the Control UI
origin allow-list current and runs:

```sh
openclaw channels add --channel discord --name homelab-discord --use-env
```

The command is skipped when the SSM value is still `REPLACE_ME`, so the app can
start before the real Discord bot token exists. It is also skipped when
`homelab-discord` is already present, which keeps pod restarts idempotent.
After replacing the SSM value, bump
`homelab.rst.io/openclaw-discord-bot-token-ssm-version` in `values.yaml` to the
resulting SSM parameter version so Argo CD rolls the pod and the startup
bootstrap re-runs.

Validate after sync:

```sh
kubectl -n ai exec deploy/openclaw -c app -- openclaw channels list
kubectl -n ai exec deploy/openclaw -c app -- openclaw channels status --probe
```

The Discord bot must be invited to the target server and channel with at least
the permissions OpenClaw reports as required for Discord, including viewing the
channel and sending messages.

## ChatGPT Pro And Codex

Do not store ChatGPT passwords, browser cookies, or OpenAI API keys in this
repo for OpenClaw. ChatGPT Pro subscription access is separate from API-key
billing, but OpenAI Codex can sign in with a ChatGPT plan and store local
credentials on the OpenClaw PVC.

Run the interactive login from a tailnet-connected operator machine:

```sh
kubectl -n ai exec -it deploy/openclaw -c app -- \
  openclaw models auth login --provider openai-codex --set-default
```

Then set and verify the default model:

```sh
kubectl -n ai exec deploy/openclaw -c app -- \
  openclaw models set openai-codex/gpt-5.3-codex

kubectl -n ai exec deploy/openclaw -c app -- \
  openclaw models status --plain
```

Those OAuth credentials persist on the `/data/openclaw` volume and should not be
copied into SSM. If the PVC is replaced, repeat the interactive Codex login.
