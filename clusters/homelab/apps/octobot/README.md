# OctoBot

OctoBot runs as the finance namespace trading bot with a real web UI. The app
uses the upstream `drakkarsoftware/octobot` Docker image and exposes only the
tailnet-only Istio route at `https://octobot.stinkyboi.com`.

This repository intentionally does not commit exchange API keys, trading
profiles, Telegram tokens, or live-trading startup configuration. Use the web
UI for first setup, start with paper trading, and keep exchange API keys scoped
to trading only with withdrawals disabled before enabling live execution.

## Runtime Contract

- Namespace: `finance`
- Image: `drakkarsoftware/octobot:2.1.1`
- Web UI port: `5001`
- Persistent state: `octobot-user`, `octobot-tentacles`, and `octobot-logs`
  PVCs on `nfs-default`
- Route: `https://octobot.stinkyboi.com`; no public Funnel route
- Secret source: none committed; OctoBot setup and exchange credentials are
  stored by the application on its persistent volumes

## Validate

Render the raw Kubernetes resources:

```sh
kubectl kustomize clusters/homelab/apps/octobot
```

Render the Helm release:

```sh
helm template octobot app-template \
  --repo https://bjw-s-labs.github.io/helm-charts \
  --version 4.4.0 \
  --namespace finance \
  --values clusters/homelab/apps/octobot/values.yaml
```

After Argo CD applies the Application, verify the workload and tailnet route:

```sh
kubectl -n argocd get application octobot
kubectl -n finance get deploy,pod,pvc,svc -l app.kubernetes.io/instance=octobot
curl -I https://octobot.stinkyboi.com
```

Expected result: one OctoBot pod is ready, the UI service listens on port
`5001`, the three NFS-backed PVCs are bound, and the FQDN is reachable only from
the tailnet.

## Operations

- Back up the PVCs before changing strategies, enabling real exchange accounts,
  or testing a major OctoBot upgrade.
- The `retired-workload-cleanup` hook removes stale finance PVCs from the
  retired trading runtime during Argo CD sync.
- Prefer paper trading and backtesting until the configuration is proven.
- Do not place exchange API keys in Git, Terragrunt inputs, Helm values,
  Kubernetes Secrets, or External Secrets without adding an explicit repository
  secret contract and runbook first.
- If live trading is enabled through the UI, document the strategy, exchange,
  backup point, and rollback notes in the related pull request.
- OctoBot image automation is pinned to `2.1.1` until a newer image can be
  tested against the current PVC-backed config. The `2.1.13` image rejected the
  persisted `config.trading.paused` key during startup migration and caused the
  pod to crash loop.
